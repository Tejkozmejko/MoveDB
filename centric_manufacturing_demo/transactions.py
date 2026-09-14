# -*- coding: utf-8 -*-
"""Seed the trading history described in ``transaction_data``.

Design notes
------------
**Idempotence.** Every document carries a reference from the data tables
(``partner_ref`` on a purchase order, ``origin`` on a manufacturing order,
``client_order_ref`` on a sales order). A document already carrying it is
skipped whole, so re-installing or upgrading the module never duplicates an
order or double-counts stock.

**Failure is not fatal.** A demo seed must never take an install down with it.
Each document is built inside a savepoint: if it fails - typically because a
component ran short, an accounting period is locked, or the bank journal has no
outstanding account configured - the savepoint is rolled back, a warning is
logged naming the document, and the seed carries on with the next one. The
summary line at the end reports how many failed.

**Backdating.** Odoo stamps documents with the wall clock. The dates in the
data tables are re-applied afterwards - order dates, invoice dates, stock move
dates and work order durations - so the demo has a trading history with shape
to it rather than everything landing on the install date. Backdating is
best-effort: a field that will not take a past date is left alone.
"""

import logging
from datetime import timedelta

from odoo import fields

from .ecotax_data import (
    COLLECTION_POINT_OF_SALE,
    ECO_CONTRIBUTION,
    LINE_TAX_FIELDS,
    PRODUCT_TAX_FIELDS,
    customer_tax_field,
)
from .traceability_data import create_lot
from .transaction_data import (
    CUSTOMERS,
    MANUFACTURING_ORDERS,
    PURCHASE_ORDERS,
    SALE_MARKUP,
    SALES_ORDERS,
)

_logger = logging.getLogger(__name__)

# Cumulative document lifecycles: reaching a status means every status before
# it was reached too. ``_reaches`` is how the builders ask "should I go this
# far?" without a ladder of string comparisons.
PURCHASE_FLOW = ["draft", "confirmed", "received", "billed", "paid"]
PRODUCTION_FLOW = ["draft", "confirmed", "progress", "done"]
SALE_FLOW = ["draft", "sent", "confirmed", "delivered", "invoiced", "paid"]


def _reaches(flow, status, step):
    """True when ``status`` is at or past ``step`` in ``flow``."""
    return flow.index(status) >= flow.index(step)


def _dt(days):
    """A datetime ``days`` from now - negative for the past."""
    return fields.Datetime.now() + timedelta(days=days)


class _Skip(Exception):
    """Raised to abandon one document without failing the others."""


# ---------------------------------------------------------------------------
# Partners and prices
# ---------------------------------------------------------------------------


def _create_customers(env):
    """Create any missing customer partner, return {name: res.partner}."""
    Partner = env["res.partner"]
    Term = env["account.payment.term"]
    partners = {}
    for name, vals in CUSTOMERS.items():
        partner = Partner.search([("name", "=", name)], limit=1)
        if not partner:
            values = {
                "name": name,
                "company_type": "company",
                "customer_rank": 1,
                "street": vals["street"],
                "city": vals["city"],
                "zip": vals["zip"],
                "phone": vals["phone"],
                "email": vals["email"],
            }
            # The payment terms come from whichever chart of accounts is
            # installed and are not guaranteed to exist under these names, so
            # a miss just leaves the customer on the company default.
            term = Term.search([("name", "=", vals["payment_term"])], limit=1)
            if term:
                values["property_payment_term_id"] = term.id
            partner = Partner.create(values)
        partners[name] = partner
    return partners


def _set_sale_prices(env, products):
    """Price the finished goods off their rolled-up cost.

    Only a product still sitting on Odoo's default price of 1.00 is touched.
    Once someone has priced it properly, that is a commercial decision and the
    seed keeps its hands off.
    """
    priced = 0
    for name, markup in SALE_MARKUP.items():
        product = products.get(name)
        if not product:
            continue
        template = product.product_tmpl_id
        if template.list_price not in (0.0, 1.0):
            continue
        template.list_price = round(template.standard_price * markup, 2)
        priced += 1
    return priced


# ---------------------------------------------------------------------------
# Shared document plumbing
# ---------------------------------------------------------------------------


def _backdate(records, dt, field="date"):
    """Best-effort: stamp ``field`` on ``records`` with ``dt``.

    Stock moves and pickings are written by the transfer machinery with the
    wall clock. Rewriting them afterwards is what gives the demo a history
    instead of a single busy afternoon. A field that refuses the write is not
    worth failing a document over.
    """
    if not records:
        return
    try:
        # Its own savepoint: backdating is cosmetic, but a failed write would
        # otherwise leave the cursor aborted and take the whole document -
        # which is not cosmetic - down with it.
        with records.env.cr.savepoint():
            records.write({field: dt})
    except Exception:  # noqa: BLE001 - cosmetic only
        _logger.debug(
            "centric_manufacturing_demo: could not backdate %s.%s",
            records._name,
            field,
        )


def _label_incoming_lots(picking, company):
    """P4.8 - give every tracked line on a receipt a lot number.

    An incoming line is the one place in the chain where a lot number does not
    already exist: it comes off the supplier's delivery note, and Odoo has
    never seen it. Everything downstream - an extrusion order consuming resin,
    a delivery shipping bags - takes the lots reservation already found on the
    quants, so it needs nothing here.

    Without this a receipt of a tracked material simply refuses to validate,
    and the seeded purchase history would arrive as a pile of warnings.
    """
    if picking.picking_type_id.code != "incoming":
        return
    for move in picking.move_ids:
        if move.product_id.tracking == "none":
            continue
        for line in move.move_line_ids:
            if line.lot_id or line.lot_name:
                continue
            line.lot_id = create_lot(picking.env, move.product_id, company).id


def _validate_picking(picking, dt, company=None):
    """Reserve, fill in and validate a transfer, then backdate it."""
    if picking.state in ("done", "cancel"):
        return
    picking.action_assign()
    for move in picking.move_ids:
        # Ship exactly what was ordered: a partial would raise the backorder
        # wizard, and a demo has no business leaving backorders behind.
        move.quantity = move.product_uom_qty
        move.picked = True
    # After the quantities, so the move lines the quantity created are all
    # there to be labelled.
    _label_incoming_lots(picking, company or picking.company_id)
    result = picking.button_validate()
    if isinstance(result, dict) and result.get("res_model"):
        # Belt and braces: if a confirmation wizard still appears, answer it
        # rather than leaving the transfer half done.
        wizard = (
            picking.env[result["res_model"]]
            .with_context(**result.get("context", {}))
            .create({})
        )
        if hasattr(wizard, "process"):
            wizard.process()
    if picking.state != "done":
        # Loudly, not quietly. A transfer that did not validate used to return
        # as though it had, so the order carried on to invoicing and failed
        # there with "nothing has been delivered" - a message about the invoice
        # for a problem with the picking. Naming the picking, and whatever
        # Odoo asked for instead, puts the actual cause in the warning.
        asked = result.get("res_model") if isinstance(result, dict) else None
        raise _Skip(
            "%s was not validated (still %s)%s"
            % (
                picking.name,
                picking.state,
                " - Odoo asked for %s" % asked if asked else "",
            )
        )
    _backdate(picking.move_ids, dt)
    _backdate(picking.move_ids.move_line_ids, dt)
    _backdate(picking, dt, "date_done")
    _backdate(picking, dt, "scheduled_date")


def _post_move(move, dt):
    """Date an invoice or bill in the past and post it."""
    move.invoice_date = _date_of(dt)
    move.date = _date_of(dt)
    move.action_post()


def _date_of(dt):
    return dt.date() if hasattr(dt, "date") else dt


def _pay(env, move, company, dt):
    """Pay an invoice or bill in full off the company's bank journal."""
    journal = env["account.journal"].search(
        [("type", "=", "bank"), ("company_id", "=", company.id)], limit=1
    )
    if not journal:
        raise _Skip("no bank journal in %s" % company.display_name)
    wizard = (
        env["account.payment.register"]
        .with_context(active_model="account.move", active_ids=move.ids)
        .create({"payment_date": _date_of(dt), "journal_id": journal.id})
    )
    wizard.action_create_payments()


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------


def _build_purchase(env, spec, company, partners, materials):
    vendor = partners.get(spec["vendor"])
    if not vendor:
        raise _Skip("vendor %r missing" % spec["vendor"])

    ordered_on = _dt(spec["days"])
    lines = []
    for product_name, qty in spec["lines"]:
        product = materials.get(product_name)
        if not product:
            raise _Skip("material %r missing" % product_name)
        lines.append(
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "name": product.display_name,
                    "product_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    # Buy at cost, so the goods-received value and the bill
                    # agree and the stock valuation stays tidy.
                    "price_unit": product.standard_price or 1.0,
                    "date_planned": ordered_on + timedelta(days=7),
                },
            )
        )

    order = env["purchase.order"].create(
        {
            "partner_id": vendor.id,
            "partner_ref": spec["ref"],
            "company_id": company.id,
            "date_order": ordered_on,
            "order_line": lines,
        }
    )

    status = spec["status"]
    if not _reaches(PURCHASE_FLOW, status, "confirmed"):
        return order

    order.button_confirm()
    _backdate(order, ordered_on, "date_approve")

    if not _reaches(PURCHASE_FLOW, status, "received"):
        return order

    for picking in order.picking_ids:
        _validate_picking(picking, ordered_on + timedelta(days=7), company)

    if not _reaches(PURCHASE_FLOW, status, "billed"):
        return order

    order.action_create_invoice()
    bill = order.invoice_ids.filtered(lambda m: m.state == "draft")
    if not bill:
        raise _Skip("no draft bill was created")
    billed_on = ordered_on + timedelta(days=10)
    _post_move(bill, billed_on)

    if _reaches(PURCHASE_FLOW, status, "paid"):
        _pay(env, bill, company, billed_on + timedelta(days=20))
    return order


def _create_purchases(env, company, partners, materials):
    Order = env["purchase.order"]
    made = failed = 0
    for spec in PURCHASE_ORDERS:
        if Order.search_count(
            [("partner_ref", "=", spec["ref"]), ("company_id", "=", company.id)]
        ):
            continue
        try:
            with env.cr.savepoint():
                _build_purchase(env, spec, company, partners, materials)
            made += 1
        except Exception as error:  # noqa: BLE001
            failed += 1
            _logger.warning(
                "centric_manufacturing_demo: purchase %s skipped - %s",
                spec["ref"],
                error,
            )
    return made, failed


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------


def _run_workorders(mo):
    """Start and finish every work order, with its expected duration booked.

    Starting and finishing a work order back to back would log a few seconds
    of machine time, which makes the work centre load and the cost of the
    finished reel meaningless. The productivity entry is backdated by the
    operation's expected duration instead, so the press and the extruder carry
    a believable number of hours.
    """
    for workorder in mo.workorder_ids:
        if workorder.state in ("done", "cancel"):
            continue
        workorder.button_start()
        expected = workorder.duration_expected or 0.0
        if expected:
            _backdate(
                workorder.time_ids.filtered(lambda t: not t.date_end),
                fields.Datetime.now() - timedelta(minutes=expected),
                "date_start",
            )
        workorder.button_finish()


# The field a works order records its own lot on, newest name first. Odoo 19
# made it a many2many - one order may now produce several lots - and reading the
# old single-lot name raised on every order, so no manufacturing order in the
# trading history could be built, and nothing downstream of production had any
# stock to ship.
PRODUCING_LOT_FIELDS = ("lot_producing_ids", "lot_producing_id")


def _set_producing_lot(env, mo, product, company):
    """Give ``mo`` the lot for the run it is about to make, unless it has one.

    Resolved off the model rather than hard-coded, for the same reason the tax
    fields are in ``ecotax_data``: the name moved between versions, and the
    cost of guessing wrong is every order in the table, not one.
    """
    name = next((f for f in PRODUCING_LOT_FIELDS if f in mo._fields), None)
    if not name:
        raise _Skip("mrp.production has no field to record the produced lot on")
    if mo[name]:
        return
    lot = create_lot(env, product, company)
    mo[name] = lot.id if mo._fields[name].type == "many2one" else [(6, 0, [lot.id])]


def _build_production(env, spec, company, products):
    product = products.get(spec["product"])
    if not product:
        raise _Skip("product %r missing" % spec["product"])
    bom = env["mrp.bom"]._bom_find(product, company_id=company.id).get(product)
    if not bom:
        raise _Skip("no bill of materials for %r" % spec["product"])

    started_on = _dt(spec["days"])
    mo = env["mrp.production"].create(
        {
            "product_id": product.id,
            "product_qty": spec["qty"],
            "product_uom_id": product.uom_id.id,
            "bom_id": bom.id,
            "company_id": company.id,
            "origin": spec["ref"],
            "date_start": started_on,
        }
    )

    status = spec["status"]
    if not _reaches(PRODUCTION_FLOW, status, "confirmed"):
        return mo

    mo.action_confirm()
    mo.action_assign()

    # P4.8 - the run's own lot, assigned as soon as the order is confirmed
    # rather than at the end: the shop floor is asked for it when the first
    # operation is recorded, so an order left live on the extrusion line needs
    # it too. This is the link the whole chain hangs on - the reel this order
    # produces carries a number and the resin lots consumed sit under it, so
    # Odoo's traceability report walks from the resin batch to the reel to the
    # printed film to the delivered pallet without anybody reading the
    # extrusion log book.
    if product.tracking != "none":
        _set_producing_lot(env, mo, product, company)

    if not _reaches(PRODUCTION_FLOW, status, "progress"):
        return mo

    if not _reaches(PRODUCTION_FLOW, status, "done"):
        # Left on the machine: start the first operation and stop there, so
        # the shopfloor view and the work centre load have something live.
        if mo.workorder_ids:
            mo.workorder_ids[0].button_start()
        return mo

    _run_workorders(mo)
    mo.qty_producing = mo.product_qty
    for move in mo.move_raw_ids:
        # Consume the recipe exactly. Setting this by hand rather than leaving
        # it to the wizard is what keeps ``button_mark_done`` from stopping to
        # ask about under-consumption.
        move.quantity = move.product_uom_qty
        move.picked = True
    mo.with_context(skip_backorder=True, skip_consumption=True).button_mark_done()

    finished_on = started_on + timedelta(hours=8)
    _backdate(mo.move_raw_ids | mo.move_finished_ids, finished_on)
    _backdate(mo, finished_on, "date_finished")
    return mo


def _create_productions(env, company, products):
    Production = env["mrp.production"]
    made = failed = 0
    for spec in MANUFACTURING_ORDERS:
        if Production.search_count(
            [("origin", "=", spec["ref"]), ("company_id", "=", company.id)]
        ):
            continue
        try:
            with env.cr.savepoint():
                _build_production(env, spec, company, products)
            made += 1
        except Exception as error:  # noqa: BLE001
            failed += 1
            _logger.warning(
                "centric_manufacturing_demo: manufacturing order %s skipped - %s",
                spec["ref"],
                error,
            )
    return made, failed


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


def _eco_contribution_tax(env, company):
    """P8.2 - the carrier bag levy tax, if the master data hook managed to make it.

    Looked up by name rather than passed down from ``hooks``, because tax
    creation is allowed to fail on a database whose chart of accounts will not
    carry it - see ``hooks._create_eco_contribution_tax``. An empty recordset
    here means the levy simply does not appear on the seeded orders, which is a
    poorer demo but a working one.
    """
    return env["account.tax"].search(
        [
            ("name", "=", ECO_CONTRIBUTION["name"]),
            ("company_id", "=", company.id),
        ],
        limit=1,
    )


def _apply_eco_contribution(order, spec, eco_tax):
    """P8.2 - put the levy on this order's lines, or deliberately take it off.

    The levy reaches an order line by itself: it is on the carrier bag
    products' customer taxes, and a sales order line takes its taxes from the
    product. So the interesting case is the *subtraction* - an order seeded to
    demonstrate the point-of-sale model has to have the levy removed from lines
    that would otherwise carry it, which is exactly what a plant invoicing
    under that model does.

    The re-adding branch is not redundant even though the product default
    covers it. A price list, a fiscal position, or somebody having edited the
    product can all leave a line without the tax, and an order that says it is
    demonstrating the invoiced model has to actually demonstrate it. It is
    guarded on the product carrying the levy in the first place, so it can
    never bolt a carrier bag levy onto a line of film or a refuse sack.
    """
    if not eco_tax:
        return
    lines = order.order_line
    if not lines:
        return
    # Resolved rather than hard-coded - see ``ecotax_data.customer_tax_field``
    # on why, and on what reading the wrong name would cost.
    line_field = customer_tax_field(lines, LINE_TAX_FIELDS)
    product_field = (
        customer_tax_field(lines.product_id, PRODUCT_TAX_FIELDS)
        if lines.product_id
        else None
    )
    if not line_field or not product_field:
        _logger.warning(
            "centric_manufacturing_demo: no customer tax field on %s, so the "
            "eco-contribution is not applied to %s",
            lines._name,
            spec["ref"],
        )
        return

    point_of_sale = spec.get("eco_collection") == COLLECTION_POINT_OF_SALE
    for line in lines:
        carries = eco_tax in line[line_field]
        if point_of_sale:
            if carries:
                line[line_field] = [(3, eco_tax.id)]
        elif not carries and eco_tax in line.product_id[product_field]:
            line[line_field] = [(4, eco_tax.id)]


def _build_sale(env, spec, company, customers, products, eco_tax=None):
    customer = customers.get(spec["customer"])
    if not customer:
        raise _Skip("customer %r missing" % spec["customer"])

    ordered_on = _dt(spec["days"])
    lines = []
    for product_name, qty in spec["lines"]:
        product = products.get(product_name)
        if not product:
            raise _Skip("product %r missing" % product_name)
        lines.append(
            (
                0,
                0,
                {
                    "product_id": product.id,
                    "name": product.display_name,
                    "product_uom_qty": qty,
                    "price_unit": product.product_tmpl_id.list_price,
                },
            )
        )

    order = env["sale.order"].create(
        {
            "partner_id": customer.id,
            "client_order_ref": spec["ref"],
            "company_id": company.id,
            "date_order": ordered_on,
            "order_line": lines,
        }
    )

    # Before the quotation is sent or confirmed: the taxes on a confirmed
    # order are what the delivery note and the invoice are built from, so this
    # has to happen while the document is still a draft.
    _apply_eco_contribution(order, spec, eco_tax)

    status = spec["status"]
    if status == "sent":
        order.action_quotation_sent()
        return order
    if not _reaches(SALE_FLOW, status, "confirmed"):
        return order

    order.action_confirm()
    _backdate(order, ordered_on, "date_order")

    if not _reaches(SALE_FLOW, status, "delivered"):
        return order

    delivered_on = ordered_on + timedelta(days=3)
    for picking in order.picking_ids:
        _validate_picking(picking, delivered_on, company)

    if not _reaches(SALE_FLOW, status, "invoiced"):
        return order

    invoice = order._create_invoices()
    if not invoice:
        raise _Skip("no draft invoice was created")
    _post_move(invoice, delivered_on)

    if _reaches(SALE_FLOW, status, "paid"):
        _pay(env, invoice, company, delivered_on + timedelta(days=25))
    return order


def _create_sales(env, company, customers, products):
    Order = env["sale.order"]
    # Resolved once rather than per order: it is the same record every time,
    # and a search inside the loop would run it for the film orders that have
    # nothing to do with the levy.
    eco_tax = _eco_contribution_tax(env, company)
    made = failed = 0
    for spec in SALES_ORDERS:
        if Order.search_count(
            [("client_order_ref", "=", spec["ref"]), ("company_id", "=", company.id)]
        ):
            continue
        try:
            with env.cr.savepoint():
                _build_sale(env, spec, company, customers, products, eco_tax)
            made += 1
        except Exception as error:  # noqa: BLE001
            failed += 1
            _logger.warning(
                "centric_manufacturing_demo: sales order %s skipped - %s",
                spec["ref"],
                error,
            )
    return made, failed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def seed_transactions(env, company, suppliers, materials, products):
    """Seed customers, purchases, production and sales, in that order.

    The order is the supply chain: purchases bring the components in,
    production turns them into finished film, sales ship it out. Running them
    any other way leaves orders unreserved.

    ``suppliers``, ``materials`` and ``products`` are the maps the master data
    hook has already built, passed in rather than looked up again so the two
    halves of the seed cannot drift apart on a renamed product.

    ``products`` is every made product, weighed and counted alike - the film
    and the reels plus the bag, industrial and waste sack ranges merged in by
    ``hooks._seed``. It used to be the film alone, which quietly meant a bag
    could not be manufactured or sold by the trading history no matter what
    ``transaction_data`` asked for: the lookup simply missed and the document
    was skipped with a warning nobody read as a missing feature.
    """
    env = env(context=dict(env.context, mail_notrack=True, tracking_disable=True))
    customers = _create_customers(env)
    priced = _set_sale_prices(env, products)
    purchases, purchase_failures = _create_purchases(env, company, suppliers, materials)
    productions, production_failures = _create_productions(env, company, products)
    sales, sale_failures = _create_sales(env, company, customers, products)

    failures = purchase_failures + production_failures + sale_failures
    _logger.info(
        "centric_manufacturing_demo: traded %s - %s customers, %s priced products, "
        "%s purchase orders, %s manufacturing orders, %s sales orders, %s skipped",
        company.display_name,
        len(customers),
        priced,
        purchases,
        productions,
        sales,
        failures,
    )
    return failures
