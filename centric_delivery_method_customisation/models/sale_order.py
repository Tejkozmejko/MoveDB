from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Invoice creation is gated on the REAL delivery state only: at least one
    # delivery order (stock.picking to a customer location) linked to the sale
    # order must be validated (state == 'done') - i.e. the order is partially
    # or fully delivered. Only an order where NOTHING has been delivered yet is
    # blocked. We deliberately do NOT gate on delivery_status, the van "ready
    # to deliver" stage, PACK completion or any computed/UI field - those can
    # read "ready" while the delivery order is still unvalidated, which let
    # invoices slip through. See _centric_delivery_blocks_invoicing, the single
    # source of truth.

    centric_van_status = fields.Selection(
        [
            ("van_ready", "Van Ready"),
            ("van_not_ready", "Van Not Ready"),
        ],
        string="Van Status",
        compute="_compute_centric_van_status",
    )
    centric_driver_id = fields.Many2one(
        "hr.employee",
        string="Driver",
        copy=True,
        index=True,
        help="Employee (driver) on this route/delivery. Set per order alongside "
             "the shipping method; flows to the delivery, the invoice and the "
             "payment collector. The same route can have a different driver each "
             "delivery.",
    )
    centric_delivery_status = fields.Selection(
        [
            ("pending", "Not Delivered"),
            ("started", "Started"),
            ("partial", "Partially Delivered"),
            ("ready", "Ready for Delivery"),
            ("full", "Fully Delivered"),
        ],
        string="Centric Delivery Status",
        compute="_compute_centric_sale_statuses",
    )
    centric_invoice_status = fields.Selection(
        [
            ("upselling", "Upselling Opportunity"),
            ("invoiced", "Invoiced"),
            ("ready_to_invoice", "Ready to Invoice"),
            # Shown while the invoice gate would block creation - i.e. nothing
            # has been delivered to the customer yet. Keeps the UI truthful:
            # never advertise "Ready to Invoice" for an order that cannot be
            # invoiced. A partially delivered order is invoiceable, so it does
            # NOT show this state.
            ("blocked", "Awaiting Delivery"),
            ("no", "Nothing to Invoice"),
        ],
        string="Centric Invoice Status",
        compute="_compute_centric_sale_statuses",
    )
    # Read-only, formatted view of the selected Delivery Address so the
    # salesperson can confirm the destination at a glance without opening the
    # customer contact. It does NOT replace partner_shipping_id (the real
    # delivery partner stays selected) - it only renders that partner cleanly.
    # NB: label intentionally differs from partner_shipping_id's "Delivery
    # Address" to avoid a duplicate-label warning on sale.order. It is shown
    # with nolabel in the form, so this string is not user-visible there.
    centric_shipping_address_display = fields.Text(
        string="Delivery Address Details",
        compute="_compute_centric_shipping_address_display",
        help="Formatted address of the selected Delivery Address "
        "(partner_shipping_id), shown read-only on the sales order.",
    )
    centric_invoicing_closed = fields.Boolean(
        string="Invoicing Closed (Fully Credited)",
        compute="_compute_centric_invoicing_closed",
        store=True,
        copy=False,
        help="Set automatically when this order has been invoiced and then FULLY "
             "credited (a full credit note was issued). Such an order is kept out "
             "of the Sales 'To Invoice' workflow so a deliberate credit is not "
             "mistaken for a new amount to bill.",
    )
    # Dynamic domain for the Delivery Address selector (partner_shipping_id).
    # Core Odoo puts NO domain on that field, so its dropdown lists every contact
    # in the database. This restricts it to the selected customer's delivery
    # addresses - the type='delivery' child contacts under the customer's
    # company - plus the customer's own company/HQ address. Kept as a computed
    # domain field so the (multi-company + commercial-partner) logic lives in
    # Python; the form binds it via domain="centric_shipping_partner_domain".
    centric_shipping_partner_domain = fields.Binary(
        string="Delivery Address Domain",
        compute="_compute_centric_shipping_partner_domain",
    )

    @api.depends("partner_id", "company_id")
    def _compute_centric_shipping_partner_domain(self):
        for order in self:
            commercial = order.partner_id.commercial_partner_id
            if not commercial:
                # No customer chosen yet: don't restrict. partner_shipping_id is
                # required and auto-fills once a customer is picked.
                order.centric_shipping_partner_domain = []
                continue
            order.centric_shipping_partner_domain = [
                "|",
                ("company_id", "=", False),
                ("company_id", "=", order.company_id.id),
                "|",
                # The selected customer itself AND its company/HQ address. The
                # customer is included so that a customer which is itself a child
                # contact (a branch modelled as a sub-contact) - whose Delivery
                # Address auto-fills to that very contact - stays selectable in
                # the dropdown. For a plain company customer this is the same id
                # as the commercial partner, so it adds nothing.
                ("id", "in", [order.partner_id.id, commercial.id]),
                # Its delivery-address contacts (type='delivery' descendants).
                "&",
                ("id", "child_of", commercial.id),
                ("type", "=", "delivery"),
            ]

    @api.depends("partner_shipping_id")
    def _compute_user_id(self):
        """Make the order's Salesperson follow the DELIVERY LOCATION.

        Native Odoo derives the salesperson from the customer; we keep that (via
        super) and then give precedence to the selected Delivery Address: if
        partner_shipping_id has an assigned salesperson
        (res.partner.centric_salesperson_id), the order's Salesperson is set to
        that user. partner_shipping_id is added to the (merged) dependency list,
        so changing the delivery location on the order re-runs this and re-points
        the salesperson to whoever is assigned to the new location. A location
        with no assigned salesperson leaves the native value untouched - it never
        clears an existing salesperson.
        """
        super()._compute_user_id()
        salesman_group = self.env.ref(
            "sales_team.group_sale_salesman", raise_if_not_found=False)
        current_user = self.env.user
        # A user who can see ALL sales orders (All Documents / manager) keeps
        # access whoever the order is assigned to; a plain "Own Documents Only"
        # rep does not.
        current_sees_all = current_user.has_group(
            "sales_team.group_sale_salesman_all_leads")
        for order in self:
            location_salesperson = order.partner_shipping_id.centric_salesperson_id
            if not location_salesperson:
                continue
            # Only honour a delivery-location salesperson that is genuinely valid
            # for this order - in the Sales group AND the order's company -
            # matching sale.order.user_id's own domain. A Many2one domain is a UI
            # filter only and is never re-validated on write, so without this a
            # mis-assigned non-sales / cross-company user could silently become
            # the order owner (invisible in "My Orders", skewing reporting).
            if salesman_group and salesman_group not in location_salesperson.all_group_ids:
                continue
            if order.company_id and order.company_id not in location_salesperson.company_ids:
                continue
            # Never reassign the order away from the current user in a way that
            # would lock THEM out of it: an "Own Documents Only" rep who is
            # neither the location salesperson nor the customer's own salesperson
            # would lose access - and Odoo raises AccessError on create. In that
            # case keep the native (customer-derived / creator) salesperson.
            # Managers / All-Documents users, the target salesperson themselves,
            # and reps who own the customer (restricted reps) all keep access.
            if (
                location_salesperson != current_user
                and not current_sees_all
                and order.partner_id.commercial_partner_id.user_id != current_user
            ):
                continue
            order.user_id = location_salesperson

    @api.depends(
        "partner_shipping_id",
        "partner_shipping_id.name",
        "partner_shipping_id.commercial_partner_id",
        "partner_shipping_id.street",
        "partner_shipping_id.street2",
        "partner_shipping_id.city",
        "partner_shipping_id.state_id",
        "partner_shipping_id.zip",
        "partner_shipping_id.country_id",
    )
    def _compute_centric_shipping_address_display(self):
        for order in self:
            order.centric_shipping_address_display = order._centric_format_shipping_address()

    def _centric_format_shipping_address(self):
        """Build a clean, multi-line address block for the selected delivery
        partner, mirroring how the address reads in the Contacts app.

        The data is pulled exclusively from ``partner_shipping_id`` native
        address fields, so it works for every customer/address with no
        hardcoding. The contact's own name is shown only when it differs from
        the company it belongs to: this avoids a redundant
        "ASIAN ROOTS LTD / ASIAN ROOTS LTD" heading while still surfacing a
        distinct delivery-site name (e.g. "KAISEKI - ...") when one exists.
        """
        self.ensure_one()
        partner = self.partner_shipping_id
        if not partner:
            return False

        lines = []
        if partner.name and partner.name != partner.commercial_partner_id.name:
            lines.append(partner.name)
        # Native, country-aware formatting. ``without_company=True`` drops the
        # parent-company line (we handle the name ourselves above), and Odoo's
        # address format naturally omits empty components, so a missing
        # Street 2 / State / ZIP never leaves a blank line or broken layout.
        formatted = partner._display_address(without_company=True) or ""
        lines += [line.strip() for line in formatted.splitlines() if line.strip()]

        return "\n".join(lines) or False

    @api.model
    def default_get(self, fields_list):
        """Seed the Delivery Date (commitment_date) with TODAY - the day the
        order is being entered - so a new order is same-day by default.

        Only fills the value when the field is actually requested and nothing has
        already set it (e.g. a context ``default_commitment_date``), so an
        explicit value is never overridden. It is a plain default: the field stays
        fully editable, and the user can pick any other date or clear it entirely.
        The value is pinned to local noon exactly like every other Delivery Date
        (see ``_centric_normalize_delivery_date_value``) so it reads as a clean,
        time-less date everywhere it flows (picking, invoice, reports)."""
        defaults = super().default_get(fields_list)
        if "commitment_date" in fields_list and not defaults.get("commitment_date"):
            defaults["commitment_date"] = self._centric_default_delivery_date()
        return defaults

    @api.model
    def _centric_default_delivery_date(self):
        """Today, pinned to local noon and returned as a naive-UTC datetime for
        storage - the same shape ``_centric_normalize_delivery_date_value``
        produces, so the default is indistinguishable from a user-picked date."""
        return self._centric_normalize_delivery_date_value(fields.Datetime.now())

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("commitment_date"):
                vals["commitment_date"] = self._centric_normalize_delivery_date_value(
                    vals["commitment_date"]
                )
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("commitment_date"):
            vals["commitment_date"] = self._centric_normalize_delivery_date_value(
                vals["commitment_date"]
            )
        result = super().write(vals)
        if "carrier_id" in vals:
            if not self.env.context.get("centric_skip_picking_carrier_sync"):
                pickings = self._centric_stock_pickings().filtered(lambda picking: picking.state != "cancel")
                if pickings:
                    pickings.with_context(centric_skip_sale_carrier_sync=True).write({
                        "carrier_id": vals["carrier_id"],
                    })
            self._centric_sync_invoice_carrier()
        if "centric_driver_id" in vals and not self.env.context.get("centric_skip_picking_driver_sync"):
            pickings = self._centric_stock_pickings().filtered(lambda picking: picking.state != "cancel")
            if pickings:
                pickings.with_context(centric_skip_sale_driver_sync=True).write({
                    "centric_driver_id": vals["centric_driver_id"],
                })
        if "commitment_date" in vals:
            self._centric_sync_picking_scheduled_date()
        return result

    def _action_confirm(self):
        self._centric_apply_contact_delivery_method()
        result = super()._action_confirm()
        self._centric_stock_pickings()._centric_auto_fill_available_quantities()
        for order in self.filtered("centric_driver_id"):
            pickings = order._centric_stock_pickings().filtered(
                lambda picking: picking.state != "cancel" and not picking.centric_driver_id)
            if pickings:
                pickings.with_context(centric_skip_sale_driver_sync=True).write({
                    "centric_driver_id": order.centric_driver_id.id,
                })
        # Keep the delivery's Scheduled Date aligned with the order Delivery Date
        # (commitment_date) once the pickings exist.
        self._centric_sync_picking_scheduled_date()
        return result

    def _centric_sync_picking_scheduled_date(self):
        """Push the order's Delivery Date (commitment_date) onto the Scheduled Date
        of every picking in the delivery chain.

        Core only propagates commitment_date to the stock move *deadline*, so the
        Scheduled Date the warehouse sees would otherwise drift from the Delivery
        Date the office sets. Setting picking.scheduled_date runs the standard
        inverse that re-dates all the picking's moves, so the two stay interlinked
        whenever the Delivery Date changes.

        This covers multi-step routes: with a Pick / Pack / Ship warehouse the
        first steps are *internal* transfers (e.g. Stock -> Packing Zone), so we
        must not restrict to customer-bound pickings. We sync every still-open
        picking of the delivery chain (everything except incoming receipts /
        returns), so the Pick the warehouse works from shows the Delivery Date too.
        """
        for order in self.filtered("commitment_date"):
            pickings = order._centric_stock_pickings().filtered(
                lambda picking: (
                    picking.state not in ("done", "cancel")
                    and picking.picking_type_code != "incoming"
                )
            )
            if pickings:
                pickings.scheduled_date = order.commitment_date

    @api.onchange("commitment_date")
    def _centric_onchange_commitment_date_strip_time(self):
        """Live UI feedback: the moment a Delivery Date is picked, drop any time
        and pin it to local noon so the form shows the same clean date that
        create()/write() will store. The input itself hides the time picker
        (options={'show_time': False}); this keeps the in-memory value consistent
        for anything that reads commitment_date before the record is saved."""
        for order in self:
            if order.commitment_date:
                normalized = order._centric_normalize_delivery_date_value(order.commitment_date)
                if normalized != order.commitment_date:
                    order.commitment_date = normalized

    centric_delivery_date = fields.Date(
        # Deliberately NOT "Delivery Date": that is core's label for
        # commitment_date, which this field writes through to, and two fields on
        # one model sharing a label makes Odoo log a warning on every registry
        # load (ir_model._reflect_fields), turning the build amber. The caption
        # users actually see is pinned on the <field> tags and the <label> in
        # views/sale_order_views.xml, so the form is unchanged.
        string="Delivery Date (day)",
        compute="_compute_centric_delivery_date",
        inverse="_inverse_centric_delivery_date",
        readonly=False,
        help="The day the order is to be delivered.",
    )

    def _centric_local_day(self, value):
        """A stored naive-UTC datetime as the calendar day the user sees."""
        if not value:
            return False
        tz = pytz.timezone(self.env.user.tz or "UTC")
        return pytz.utc.localize(value).astimezone(tz).date()

    @api.onchange("commitment_date", "expected_date")
    def _onchange_commitment_date(self):
        """Only warn when the delivery DAY really is before the expected day.

        OVERRIDES 'sale'. Core compares two instants, which does not survive our
        Delivery Date being a date: every value is anchored to local noon, while
        ``expected_date`` is ``now() + customer_lead`` -- an actual wall-clock
        time. So on any order raised after midday, today's delivery date (local
        noon) sits before "now" and core warned that a same-day delivery was
        "too soon", on every single order.

        Comparing calendar days instead keeps the warning meaningful: it still
        fires when the goods genuinely cannot arrive in time (a lead time that
        pushes the expected date to a later day), and stays quiet when the
        delivery day is the expected day.
        """
        if not (self.commitment_date and self.expected_date):
            return None
        commitment_day = self._centric_local_day(self.commitment_date)
        expected_day = self._centric_local_day(self.expected_date)
        if commitment_day < expected_day:
            # Same condition core tests, so it produces its own message.
            return super()._onchange_commitment_date()
        return None

    @api.depends("commitment_date")
    def _compute_centric_delivery_date(self):
        """The stored datetime seen as a plain day in the user's timezone.

        ``commitment_date`` has to stay a Datetime -- core seeds the
        procurement / stock.move / stock.picking deadline chain from it -- but a
        Datetime field always offers a time picker, and the time is meaningless
        here because every value is pinned to local noon anyway. This Date field
        is what the form shows, so the user gets a plain calendar.

        Not stored: ``commitment_date`` stays the single source of truth, and
        noon is far enough from either day boundary that converting back and
        forth can never land on the wrong day.
        """
        for order in self:
            order.centric_delivery_date = order._centric_local_day(
                order.commitment_date
            )

    def _inverse_centric_delivery_date(self):
        """Write the picked day back as local noon, or clear the date.

        Local noon is built directly rather than passed through
        ``_centric_normalize_delivery_date_value``: that helper reads its input
        as naive UTC, so handing it a bare midday would land on the following
        day for any timezone at UTC+12 or beyond. The result is identical to
        what the helper produces for the same day, so values written here and
        values normalised on write are indistinguishable.
        """
        tz = pytz.timezone(self.env.user.tz or "UTC")
        for order in self:
            if not order.centric_delivery_date:
                order.commitment_date = False
                continue
            local_noon = tz.localize(
                datetime.combine(order.centric_delivery_date, time(12, 0))
            )
            order.commitment_date = local_noon.astimezone(pytz.utc).replace(tzinfo=None)

    def _centric_normalize_delivery_date_value(self, value):
        """Force a Delivery Date (commitment_date) to 12:00 in the editing user's
        timezone, returned as a naive UTC datetime for storage.

        commitment_date stays a Datetime on purpose: core sale_stock seeds the
        procurement / stock.move / stock.picking *deadline* chain from it, and this
        module also copies it onto the picking Scheduled Date (line ~187) and the
        invoice Delivery Date (_prepare_invoice / account_move._compute_delivery_date)
        - all of which require a real datetime. The office only cares about the
        date, so the time is removed by anchoring the value at local NOON:
          * it discards whatever time the datetime widget would otherwise keep, and
          * noon sits ~12h from either day boundary, so converting the stored value
            back to the user timezone (invoice delivery_date, picking scheduled
            date, the QWeb reports) always lands on the date that was picked - no
            off-by-one. Midnight is deliberately NOT used: it sits on the day
            boundary a timezone/DST offset can roll into the previous/next day.

        Accepts a string (web client) or a datetime; returns the value unchanged
        when falsy so clearing the Delivery Date still works.
        """
        value = fields.Datetime.to_datetime(value)
        if not value:
            return value
        tz = pytz.timezone(self.env.user.tz or "UTC")
        local_noon = pytz.utc.localize(value).astimezone(tz).replace(
            hour=12, minute=0, second=0, microsecond=0
        )
        return local_noon.astimezone(pytz.utc).replace(tzinfo=None)

    def _centric_apply_contact_delivery_method(self):
        for order in self.filtered(lambda sale_order: not sale_order.carrier_id):
            carrier = order._centric_contact_delivery_method()
            if carrier:
                order.carrier_id = carrier

    def _centric_contact_delivery_method(self):
        self.ensure_one()
        partners = self._centric_delivery_method_partners()
        company = self.company_id or self.env.company

        for field_name in (
            "property_delivery_carrier_id",
            "centric_secondary_delivery_carrier_id",
        ):
            for partner in partners:
                carrier = partner.with_company(company)[field_name]
                if carrier and (not carrier.company_id or carrier.company_id == company):
                    return carrier
        return self.env["delivery.carrier"]

    def _centric_delivery_method_partners(self):
        self.ensure_one()
        partners = self.env["res.partner"]
        seen_partner_ids = set()
        for partner in (
            self.partner_shipping_id,
            self.partner_id,
            self.partner_shipping_id.commercial_partner_id,
            self.partner_id.commercial_partner_id,
        ):
            if partner and partner.id not in seen_partner_ids:
                partners |= partner
                seen_partner_ids.add(partner.id)
        return partners

    def _centric_stock_pickings(self):
        pickings = self.mapped("picking_ids")
        references = self.mapped("stock_reference_ids")
        if references:
            pickings |= self.env["stock.picking"].search([
                ("reference_ids", "in", references.ids),
            ])
        return pickings

    def _centric_split_order_carried_fields(self):
        """Field names that must follow the order through a delivery split.

        Splitting an order because one loadsheet category ships ahead of the
        others is bookkeeping, not a new sale: the customer placed one order
        and gets one set of paperwork, issued under two numbers. Anything that
        describes the *order as the customer sees it* therefore belongs on both
        halves.

        Fields marked ``copy=False`` are the ones that need saying out loud,
        because ``copy()`` drops them. That flag is about the Duplicate action -
        a duplicated order should start clean - so it is right where it is and
        the split opts back in here instead. Modules that add such a field
        extend this list; the container itself claims nothing.
        """
        return []

    def _centric_split_order_carried_values(self):
        """``_centric_split_order_carried_fields`` resolved to copy() defaults.

        Empty values are skipped so a module can list a field unconditionally
        without stamping a blank over whatever ``copy()`` would have produced.
        """
        self.ensure_one()
        return {
            name: self[name]
            for name in self._centric_split_order_carried_fields()
            if name in self._fields and self[name]
        }

    def _centric_active_workflow_pickings(self):
        return self._centric_stock_pickings().filtered(
            lambda picking: picking.state != "cancel" and picking._centric_is_van_workflow_stage()
        )

    def _centric_is_ready_for_delivery(self):
        self.ensure_one()
        workflow_pickings = self._centric_active_workflow_pickings()
        blocking_pickings = workflow_pickings.filtered(
            lambda picking: picking.state != "done" and picking._centric_van_stage_sequence() < 30
        )
        delivery_pickings = workflow_pickings.filtered(
            lambda picking: picking.state != "done"
            and picking._centric_van_stage_sequence() >= 30
        )
        return bool(delivery_pickings) and not blocking_pickings

    def _centric_ready_delivery_pickings(self):
        return self._centric_active_workflow_pickings().filtered(
            lambda picking: picking.state != "done" and picking._centric_van_stage_sequence() >= 30
        )

    def _centric_sync_invoice_carrier(self):
        invoices = self.mapped("order_line.invoice_lines.move_id").filtered(
            lambda move: move.move_type in ("out_invoice", "out_refund", "out_receipt")
        )
        if invoices:
            invoices._compute_carrier_id()

    @api.depends(
        "delivery_status",
        "invoice_status",
        "picking_ids.state",
        "picking_ids.picking_type_id",
        "picking_ids.centric_loadsheet_category_id",
        "order_line.invoice_lines.move_id.state",
        "order_line.qty_delivered",
        "order_line.product_uom_qty",
        "stock_reference_ids",
    )
    def _compute_centric_sale_statuses(self):
        delivery_status_map = {
            "pending": "pending",
            "started": "started",
            "partial": "partial",
            "full": "full",
        }
        for order in self:
            ready_for_delivery = order._centric_is_ready_for_delivery()
            core_delivery_status = order.delivery_status
            # QUANTITY-aware "Fully Delivered": core delivery_status counts
            # delivery orders, not quantities, so an order whose remainder was
            # CANCELLED (validate-without-backorder / backorders disabled) reads
            # 'full' with goods still undelivered. Never show "Fully Delivered"
            # while any ordered stockable quantity has not shipped - show
            # "Partially Delivered" instead. Same for the invoiced shortcut
            # below: invoicing the delivered part must not repaint the order as
            # fully delivered.
            under_delivered = order._centric_has_undelivered_quantities()

            if order.invoice_status == "invoiced":
                order.centric_delivery_status = "partial" if under_delivered else "full"
            elif core_delivery_status in ("partial", "full"):
                # Root-cause fix: as soon as a delivery picking is validated,
                # reflect the standard Odoo delivery_status (Partially / Fully
                # Delivered) right away - even if a backorder delivery is still
                # pending. Previously this stayed on "Ready for Delivery" until
                # an invoice was created, because the "ready" branch below won
                # over the real delivered state.
                if core_delivery_status == "full" and under_delivered:
                    order.centric_delivery_status = "partial"
                else:
                    order.centric_delivery_status = core_delivery_status
            elif ready_for_delivery:
                order.centric_delivery_status = "ready"
            else:
                order.centric_delivery_status = delivery_status_map.get(core_delivery_status) or "pending"

            # Keep the invoice status strictly consistent with the invoice gate
            # (_centric_check_deliveries_completed): an order is blocked only
            # while NOTHING has been delivered to the customer yet, so the
            # status must never read "Ready to Invoice" in that case. Same
            # single source of truth as the gate - the real stock.picking.state,
            # not delivery_status / the van "ready" stage / any computed UI
            # field.
            delivery_blocks_invoice = order._centric_delivery_blocks_invoicing()
            if order.invoice_status == "invoiced":
                order.centric_invoice_status = "invoiced"
            elif delivery_blocks_invoice:
                order.centric_invoice_status = "blocked"
            elif order.invoice_status == "to invoice":
                order.centric_invoice_status = "ready_to_invoice"
            elif order.invoice_status == "upselling":
                order.centric_invoice_status = "upselling"
            else:
                order.centric_invoice_status = "no"

    # ------------------------------------------------------------------
    # Fully-credited orders leave the "To Invoice" workflow
    # ------------------------------------------------------------------
    @api.depends(
        "order_line.qty_invoiced",
        "order_line.invoice_lines.move_id.state",
        "order_line.invoice_lines.move_id.move_type",
    )
    def _compute_centric_invoicing_closed(self):
        for order in self:
            order.centric_invoicing_closed = order._centric_is_fully_credited()

    def _centric_is_fully_credited(self):
        """True when the order has been invoiced AND then fully credited.

        We require at least one posted customer invoice and one posted credit note
        on the order's lines (so a mere reset-to-draft of an invoice, which also
        drops qty_invoiced, never counts as a credit), and then check that every
        line's net invoiced quantity is back to zero or below -- i.e. a *full*
        credit note. A partial credit leaves a positive qty_invoiced, so the order
        stays billable. qty_invoiced is Odoo's own net of invoices minus credits,
        so this stays perfectly consistent with the standard invoice_status."""
        self.ensure_one()
        posted_lines = self.order_line.invoice_lines.filtered(
            lambda line: line.move_id.state == "posted"
        )
        move_types = posted_lines.move_id.mapped("move_type")
        if "out_invoice" not in move_types or "out_refund" not in move_types:
            return False
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        product_lines = self.order_line.filtered(lambda line: not line.display_type)
        return all(
            float_compare(line.qty_invoiced, 0.0, precision_digits=precision) <= 0
            for line in product_lines
        )

    @api.depends("centric_invoicing_closed")
    def _compute_invoice_status(self):
        # Keep a fully-credited order out of the Sales "To Invoice" list: the
        # credit note was issued deliberately, so the order should not advertise
        # itself as billable again. (Manual re-invoicing from the order is still
        # possible if genuinely needed -- this only changes the surfaced status.)
        super()._compute_invoice_status()
        for order in self:
            if order.centric_invoicing_closed and order.invoice_status == "to invoice":
                order.invoice_status = "no"

    def _prepare_invoice(self):
        # The invoice's Delivery Date should reflect the planned Delivery Date set
        # on the order (commitment_date), not the actual delivery (effective_date)
        # that core sale_stock fills in here. Office staff enter the promised
        # delivery date on the order and expect the same date on the invoice.
        values = super()._prepare_invoice()
        if self.commitment_date:
            values["delivery_date"] = fields.Datetime.context_timestamp(self, self.commitment_date)
        return values

    def _create_invoices(self, grouped=False, final=False, date=None):
        """Enforce the delivery gate, then create AND immediately post the
        invoice(s) so a draft never persists.

        This is the single backend choke point every Sales Order -> customer
        invoice flow goes through: the direct "Create Invoice" buttons
        (``action_centric_create_and_post_invoices``) and any direct programmatic
        / API / RPC call, including the standard advance-payment wizard's
        ``delivered`` branch if it is ever invoked. Gating here (the lowest common
        level) means no UI, batch or API path can bypass the rule.

        Order of operations:
          1. delivery gate - block unless the order is partially or fully
             delivered, i.e. at least one delivery order to the customer is
             validated (stock.picking.state == 'done'); see
             _centric_delivery_blocks_invoicing. Runs before anything else so
             no invoice is ever built for an order with no validated delivery;
          2. super() creates the draft invoice(s);
          3. invoice lines are split by delivered lot while still draft;
          4. the invoices are posted, idempotently (see _centric_post_invoices),
             leaving no draft behind.
        """
        self._centric_check_deliveries_completed()
        invoices = super()._create_invoices(grouped=grouped, final=final, date=date)
        if invoices:
            invoices._centric_split_invoice_lines_by_delivered_lot()
            self._centric_post_invoices(invoices)
        return invoices

    def _centric_post_invoices(self, invoices):
        """Post freshly created Sales Order invoices so none is ever left in
        draft.

        Idempotent by design: only ``draft`` moves are posted, so a caller that
        posts again, a re-run, or an already-posted invoice never triggers a
        double post. Controlled internal flows that must keep a draft can defer
        posting with the ``centric_skip_invoice_auto_post`` context key; normal
        operation always posts.
        """
        if self.env.context.get("centric_skip_invoice_auto_post"):
            return invoices
        invoices_to_post = invoices.filtered(lambda invoice: invoice.state == "draft")
        if invoices_to_post:
            invoices_to_post.action_post()
        return invoices

    def _centric_delivery_blocks_invoicing(self):
        """Single source of truth for the invoice gate: ``True`` while NOTHING
        has been delivered to the customer yet - i.e. no stock picking to a
        customer location is validated (``state == 'done'``). An order that is
        partially or fully delivered is invoiceable.

        Only the real picking state is used - never ``delivery_status``, the van
        "ready to deliver" stage, PACK completion or any computed/UI field, any
        of which can read "ready" while the delivery is still unvalidated.
        Cancelled pickings are ignored. Only pickings whose destination is a
        customer location count as deliveries, because in multi-step routes a
        validated PICK/PACK moves stock between internal zones without anything
        reaching the customer - such an order is correctly still blocked. An
        order with no picking at all (service-only), or whose pickings are all
        cancelled, is never blocked.
        """
        self.ensure_one()
        active_pickings = self.picking_ids.filtered(
            lambda picking: picking.state != "cancel"
        )
        if not active_pickings:
            return False
        return not any(
            picking.state == "done"
            and picking.location_dest_id.usage == "customer"
            for picking in active_pickings
        )

    def _centric_has_undelivered_quantities(self):
        """``True`` while any stockable order line has shipped less than its
        ordered quantity (``qty_delivered < product_uom_qty``).

        Used to keep the displayed delivery status honest by QUANTITY: core
        ``delivery_status`` only counts delivery orders, so a cancelled
        remainder (validate without backorder) makes it read 'full' while goods
        are still undelivered. Service lines are ignored - they do not ship
        through pickings and would otherwise pin every mixed order on
        "Partially Delivered" forever.
        """
        self.ensure_one()
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        return any(
            float_compare(
                line.qty_delivered,
                line.product_uom_qty,
                precision_digits=precision,
            ) < 0
            for line in self.order_line
            if not line.display_type and line.product_id.type != "service"
        )

    def _centric_orders_blocking_invoice(self):
        """Return the orders in ``self`` where nothing has been delivered yet
        and that must therefore not be invoiced (see
        ``_centric_delivery_blocks_invoicing``). Partially or fully delivered
        orders, service-only orders, and orders whose delivery orders are all
        cancelled are never blocked."""
        return self.filtered(lambda order: order._centric_delivery_blocks_invoicing())

    def _centric_check_deliveries_completed(self):
        """Raise a clear UserError if any order being invoiced has no validated
        delivery yet (nothing delivered to the customer). Safe in batch (reports
        every offending order) and bypassable through the
        ``centric_skip_delivery_invoice_check`` context key for controlled
        programmatic flows that must not be gated."""
        if self.env.context.get("centric_skip_delivery_invoice_check"):
            return

        blocking_orders = self._centric_orders_blocking_invoice()
        if not blocking_orders:
            return

        message = _(
            "Invoice cannot be created yet: nothing has been delivered for this "
            "sale order. Validate (Done) at least one delivery order first - "
            "partially delivered orders can be invoiced."
        )
        if len(self) > 1 or blocking_orders != self:
            message += "\n\n" + _(
                "Orders with nothing delivered yet: %s"
            ) % ", ".join(blocking_orders.mapped("display_name"))
        raise UserError(message)

    def action_centric_create_and_post_invoices(self):
        """Single "Create Invoice" action used by every Sales Order button
        (form and list/batch). It fully replaces the standard advance-payment
        wizard: no popup, no invoice-type or down-payment selection. One click
        creates one regular customer invoice per order - ``_create_invoices``
        enforces the delivery gate (every delivery order must already be
        validated/Done), splits lines by delivered lot and posts immediately, so
        the result is never a draft - then opens the print dialog.

        The invoice no longer auto-validates "ready" deliveries: a delivery order
        must be validated through the normal warehouse flow first, otherwise
        creation is blocked. ``final=True``/``grouped=True`` reproduce exactly
        what the wizard used to pass (deduct_down_payments default True,
        consolidated_billing False), so batch invoicing behaviour is unchanged.
        """
        invoices = self._create_invoices(grouped=True, final=True)
        return self._centric_print_invoices(invoices)

    def _centric_print_invoices(self, invoices):
        """Deliver the posted invoice(s) as an HTML page in a new browser tab so
        the browser print dialog opens automatically, instead of only
        downloading the PDF.

        The print dialog itself is triggered by the gated auto-print snippet in
        the ``account.report_invoice_document`` template
        (centric_invoice_customisation), and each invoice is emitted twice (see
        ``account.move._centric_invoice_auto_print_action``) so the print run
        produces 2 copies. The invoice form/list is returned as a fallback
        whenever the print URL cannot be built, so invoice creation never blocks
        on the printing step.
        """
        invoice_action = self.action_view_invoice(invoices=invoices)
        invoice_report = self.env.ref("account.account_invoices", raise_if_not_found=False)
        if not invoice_report or not invoices:
            return invoice_action

        return invoices._centric_invoice_auto_print_action(invoice_report)

    @api.depends("carrier_id", "company_id", "warehouse_id")
    def _compute_centric_van_status(self):
        carriers = self.mapped("carrier_id")
        companies = self.mapped("company_id")
        if not carriers or not companies:
            self.centric_van_status = False
            return

        pickings = self.env["stock.picking"].search([
            ("carrier_id", "in", carriers.ids),
            ("company_id", "in", companies.ids),
            ("state", "not in", ("cancel", "done")),
        ]).filtered(lambda picking: picking._centric_is_van_workflow_stage())

        for order in self:
            if not order.carrier_id:
                order.centric_van_status = False
                continue

            van_pickings = pickings.filtered(
                lambda picking: (
                    picking.carrier_id == order.carrier_id
                    and picking.company_id == order.company_id
                    and (
                        not order.warehouse_id
                        or picking.picking_type_id.warehouse_id == order.warehouse_id
                    )
                )
            )
            if not van_pickings:
                order.centric_van_status = False
            elif any(picking._centric_van_stage_sequence() < 30 for picking in van_pickings):
                order.centric_van_status = "van_not_ready"
            else:
                order.centric_van_status = "van_ready"
