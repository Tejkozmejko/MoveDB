# -*- coding: utf-8 -*-
import logging

from .custom_print_data import (
    ARTWORK_ATTRIBUTE,
    ARTWORKS,
    BAG_LINE_MINUTES,
    CARTONS_PER_RUN,
    CORES_PER_RUN,
    CUSTOM_GRAMS_PER_BAG,
    CUSTOM_MARGIN,
    CUSTOM_PRINT_CODE,
    CUSTOM_PRINT_FILM,
    CUSTOM_PRINT_PRODUCT,
    CUSTOM_RUN_QTY,
    CUSTOM_WASTE_PCT,
    SLIT_MINUTES,
    artwork_description,
    artwork_inks,
    press_minutes,
)
from .landed_cost_data import LANDED_COSTS
from .material_data import (
    BAG_RUN_QTY,
    CATEG_ORDER,
    CATEG_PARENT,
    FILM_MARGIN,
    FINISHED_BAG_CATEG,
    FINISHED_BAGS,
    FINISHED_CATEG,
    INDUSTRIAL_CATEG,
    INDUSTRIAL_PACKAGING,
    KG,
    MANUFACTURED,
    RAW_CATEG,
    RAW_MATERIALS,
    ROOT_CATEG,
    SCRAP_COST,
    SCRAP_MATERIAL,
    SCRAP_OPENING_QTY,
    UNIT,
    WIP_CATEG,
)
from .pricing import bag_cost, bag_price, film_kg_per_bag, with_margin
from .quality_data import QUALITY_POINTS
from .replenishment_data import MONTHLY_USAGE, reorder_levels
from .supplier_data import (
    BACKUP_PRICE_UPLIFT,
    MIN_QTY_BY_UOM,
    MIN_QTY_OVERRIDE,
    SOURCING,
    SUPPLIERS,
)
from .traceability_data import UNTRACKED_MATERIALS, create_lot
from .transactions import seed_transactions
from .workcenter_data import WORKCENTERS

_logger = logging.getLogger(__name__)

# Fallback UoM names, used when the expected external id is not present in the
# database. These match the names shown in the UoM list.
_UOM_FALLBACK_NAME = {KG: "kg", UNIT: "Units"}


def _resolve_uoms(env):
    uoms = {}
    for xmlid, name in _UOM_FALLBACK_NAME.items():
        uom = env.ref(xmlid, raise_if_not_found=False)
        if not uom:
            uom = env["uom.uom"].search([("name", "=", name)], limit=1)
        if not uom:
            raise ValueError("Cannot resolve unit of measure %r" % name)
        uoms[xmlid] = uom
    return uoms


def _categories(env):
    """Return {category name: product.category}, creating any that are missing.

    The categories are nested rather than flat - see ``CATEG_PARENT``. An
    existing category found by name has its parent set if it has not got one,
    which is what pulls the three flat categories a previous version of this
    module created into the tree without touching the products underneath them.
    A category somebody has already filed somewhere deliberately is left where
    it is.
    """
    Categ = env["product.category"]
    categories = {}
    for name in CATEG_ORDER:
        categ = Categ.search([("name", "=", name)], limit=1)
        parent = categories.get(CATEG_PARENT.get(name))
        if not categ:
            categ = Categ.create(
                dict({"name": name}, **({"parent_id": parent.id} if parent else {}))
            )
        elif parent and not categ.parent_id:
            categ.parent_id = parent.id
        categories[name] = categ
    return categories


# Which balance-sheet stock account each packaging category is valued on, by
# preference order - the first name that exists in the company's chart wins.
# DEMO MAPPING: these are the generic Maltese chart's stock headings, chosen so
# raw material, work in progress and finished goods do not all land in one
# balance. Traplas' accountant must confirm them before go-live.
_VALUATION_ACCOUNT_NAMES = {
    ROOT_CATEG: ("Stocks",),
    RAW_CATEG: ("Stock of raw materials", "Stocks"),
    WIP_CATEG: ("Stock of raw materials", "Stocks"),
    FINISHED_CATEG: ("Stock of goods finished goods", "Stocks"),
    FINISHED_BAG_CATEG: ("Stock of goods finished goods", "Stocks"),
    INDUSTRIAL_CATEG: ("Stock of goods finished goods", "Stocks"),
}


def _valuation_account(env, company, categ_name):
    """Return the stock valuation account for a category, or an empty record."""
    Account = env["account.account"]
    for name in _VALUATION_ACCOUNT_NAMES.get(categ_name, ()):
        account = Account.search(
            [
                ("company_ids", "in", company.id),
                ("name", "=", name),
                ("account_type", "=", "asset_current"),
            ],
            limit=1,
        )
        if account:
            return account
    return Account.browse()


def _set_costing_policy(env, company, categories):
    """P3.9 - put the packaging categories on FIFO, return how many moved.

    Called before any product is created or any stock counted in, so the
    materials below are costed under the policy from their very first receipt
    rather than being converted after the fact.

    Only a category still sitting on Odoo's ``standard`` default is touched. A
    category somebody has deliberately put on average or FIFO already is left
    alone - costing method is an accounting decision, and a data module gets to
    make it once, on a category it has just created, not on every upgrade.

    Valuation is switched to automated (``real_time``) in the same pass, but
    only where the chart of accounts can actually back it. Odoo 19 no longer
    has the stock input/output interim accounts - a category needs a stock
    journal and a stock valuation account, and nothing else - so both are
    resolved from ``company``'s chart first and the category is left on manual
    if either is missing. Flipping a category to automated with no valuation
    account makes every later stock move fail, which is worse than a warning.

    The switch is also only safe here, before the first receipt: Odoo refuses
    to change the valuation of a category that already holds valued stock,
    because it cannot retrospectively write the journal entries the earlier
    moves never made. A category that already has layers is therefore left
    alone and named in the warning.
    """
    moved = 0
    for categ in categories.values():
        if categ.property_cost_method == "standard":
            categ.property_cost_method = "fifo"
            moved += 1

    journal = env["account.journal"].search(
        [("company_id", "=", company.id), ("code", "=", "STJ")], limit=1
    ) or env["account.journal"].search(
        [("company_id", "=", company.id), ("type", "=", "general")], limit=1
    )

    Layer = env["stock.valuation.layer"]
    for name, categ in categories.items():
        if categ.property_valuation == "real_time":
            continue
        account = categ.property_stock_valuation_account_id or _valuation_account(
            env, company, name
        )
        if not journal or not account:
            continue
        # An existing category carried over from an earlier install may already
        # be holding stock; only a category with no layers can be converted.
        if Layer.search_count([("product_id.categ_id", "=", categ.id)]):
            continue
        categ.property_stock_journal = journal.id
        categ.property_stock_valuation_account_id = account.id
        categ.property_valuation = "real_time"

    manual = [
        categ.display_name
        for categ in categories.values()
        if categ.property_valuation != "real_time"
    ]
    if manual:
        _logger.warning(
            "centric_manufacturing_demo: %s left on manual (periodic) stock "
            "valuation - either the chart of accounts has no stock journal and "
            "valuation account to point at, or the category already holds "
            "valued stock and Odoo will not convert it in place",
            ", ".join(manual),
        )
    return moved


def _product(env, name, vals):
    """Find a product template by name, or create it with ``vals``.

    Matching on name is what keeps the seed idempotent: a re-install or upgrade
    finds what it made last time and leaves it alone, including any cost or
    category someone has since corrected.
    """
    Template = env["product.template"]
    tmpl = Template.search([("name", "=", name)], limit=1)
    if not tmpl:
        tmpl = Template.create(dict(vals, name=name))
    return tmpl.product_variant_id


def _create_raw_materials(env, uoms, categories):
    """Create the bought-in material master, return {name: product.product}."""
    materials = {}
    for name, (uom_xmlid, cost, _qty) in RAW_MATERIALS.items():
        materials[name] = _product(
            env,
            name,
            {
                "type": "consu",
                "is_storable": True,
                "uom_id": uoms[uom_xmlid].id,
                "categ_id": categories[RAW_CATEG].id,
                "standard_price": cost,
                "purchase_ok": True,
                "sale_ok": False,
            },
        )

    # Recovered scrap: stocked and costed like a material, but produced by the
    # plant rather than bought, so it is not offered to purchasing.
    materials[SCRAP_MATERIAL] = _product(
        env,
        SCRAP_MATERIAL,
        {
            "type": "consu",
            "is_storable": True,
            "uom_id": uoms[KG].id,
            "categ_id": categories[RAW_CATEG].id,
            "standard_price": SCRAP_COST,
            "purchase_ok": False,
            "sale_ok": False,
        },
    )
    return materials


def _plant_company(env):
    """Return the company that owns the plant's work centres.

    The work centres were created by hand against the plant company, which is
    not necessarily the company the installing user happens to be working in.
    Everything company-dependent this hook creates - the BoMs and their
    operations above all - has to line up with them, or Odoo rejects the BoM
    for crossing companies. Fall back to the current company on a fresh
    database where no work centre exists yet.
    """
    workcenter = (
        env["mrp.workcenter"]
        .with_context(active_test=False)
        .search([("code", "in", list(WORKCENTERS))], limit=1)
    )
    return workcenter.company_id or env.company


def _create_workcenters(env, company):
    """Return {code: mrp.workcenter}, creating only the ones that are missing.

    An existing work centre is returned untouched. The press, slitter and
    granulator were set up by hand with rates and OEE targets that belong to
    the plant, and a data module has no business overwriting them.
    """
    Workcenter = env["mrp.workcenter"]
    workcenters = {}
    for code, vals in WORKCENTERS.items():
        workcenter = Workcenter.with_context(active_test=False).search(
            [("code", "=", code)], limit=1
        )
        if not workcenter:
            workcenter = Workcenter.create(dict(vals, code=code, company_id=company.id))
            _logger.info(
                "centric_manufacturing_demo: created work centre %s (%s)",
                code,
                vals["name"],
            )
        workcenters[code] = workcenter
    return workcenters


def _create_boms(env, uoms, categories, materials, workcenters, company):
    """Create a manufacturing BoM per made product and roll its cost up.

    Unlike a kit, these are ``normal`` BoMs: they are consumed by a
    manufacturing order, so the plant gets work orders, work centre load and a
    real WIP picture rather than a silent component explosion.

    ``MANUFACTURED`` is ordered so that a product's components are all defined
    before it is. That lets the cost roll up in a single pass - by the time the
    printed film is costed, the jumbo reel it consumes already carries the
    extrusion cost, which in turn already carries the regrind cost.
    """
    Bom = env["mrp.bom"]
    products = {}
    for name, spec in MANUFACTURED.items():
        product = _product(
            env,
            name,
            {
                "type": "consu",
                "is_storable": True,
                "uom_id": uoms[spec["uom"]].id,
                "categ_id": categories[spec["categ"]].id,
                "purchase_ok": False,
                "sale_ok": spec["sale_ok"],
            },
        )
        products[name] = product
        available = dict(materials, **products)

        run_qty = spec["qty"]
        cost = 0.0
        bom_lines = []
        for component_name, qty in spec["components"]:
            component = available[component_name]
            cost += component.standard_price * qty
            bom_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": component.id,
                        "product_qty": qty,
                        "product_uom_id": component.uom_id.id,
                    },
                )
            )

        operations = []
        for operation_name, code, minutes in spec["operations"]:
            workcenter = workcenters[code]
            cost += workcenter.costs_hour * minutes / 60.0
            operations.append(
                (
                    0,
                    0,
                    {
                        "name": operation_name,
                        "workcenter_id": workcenter.id,
                        "time_cycle_manual": minutes,
                    },
                )
            )

        # By-products: the scrap the line throws off, booked back into stock so
        # the granulator has something real to eat. Their cost share leaves the
        # good film, so it comes off the rolled-up cost before it is divided
        # across the run - otherwise the film carries the cost of its own waste
        # twice, once in the yield and once in the price.
        byproducts = []
        scrap_share = 0.0
        for byproduct_name, qty, cost_share in spec.get("byproducts", ()):
            byproduct = available[byproduct_name]
            scrap_share += cost_share
            byproducts.append(
                (
                    0,
                    0,
                    {
                        "product_id": byproduct.id,
                        "product_qty": qty,
                        "product_uom_id": byproduct.uom_id.id,
                        "cost_share": cost_share,
                    },
                )
            )
        cost *= 1.0 - scrap_share / 100.0

        vals = {
            "product_tmpl_id": product.product_tmpl_id.id,
            "product_qty": run_qty,
            "product_uom_id": product.uom_id.id,
            "type": "normal",
            # Pinned to the work centres' company: an operation may not point at
            # a work centre owned by a different company than its BoM.
            "company_id": company.id,
            "bom_line_ids": [(5, 0, 0)] + bom_lines,
            "operation_ids": [(5, 0, 0)] + operations,
            "byproduct_ids": [(5, 0, 0)] + byproducts,
        }
        existing = Bom.search(
            [
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
                ("company_id", "in", (False, company.id)),
            ],
            limit=1,
        )
        if existing:
            existing.write(vals)
        else:
            Bom.create(vals)

        # Cost per base unit, so it is comparable with the bought-in materials.
        unit_cost = cost / run_qty
        product.product_tmpl_id.standard_price = round(unit_cost, 4)
        if spec["sale_ok"]:
            # Reel sold as reel, priced per kilogramme off the rolled-up cost.
            product.product_tmpl_id.list_price = round(
                with_margin(unit_cost, FILM_MARGIN), 4
            )
    return products


def _create_converted(
    env,
    uoms,
    categories,
    materials,
    workcenters,
    products,
    company,
    specs,
    categ_name,
    default_workcenter="TP-BAGLINE",
    default_operation="Convert, seal and cut to bags",
):
    """P3/P3.2/P3.7/P6.4 - the converted ranges, where kilogrammes become units.

    Used twice: once for the finished bag range and once for the industrial
    packaging in ``INDUSTRIAL_PACKAGING``. They are the same problem - film in
    by weight, counted units out, offcut back to the granulator - so they get
    the same code rather than a copy of it with the numbers changed. What each
    range brings of its own is its category, its work centre and its run size.

    Each converted product gets three things the film products above do not
    need:

    * a **BoM sized in bags** that consumes film in kilogrammes. This is the
      whole kilogramme/unit bridge: Odoo cannot convert between the two UoM
      categories, so the rate lives in the BoM, derived from the bag's own
      weight and its conversion waste;
    * a **weight** in kilogrammes per bag, so the same rate is available to
      anyone reading the product rather than the BoM - carriage on a pallet of
      bags, or answering how many bags come out of a given reel;
    * a **sale price**, computed by ``pricing.py`` from the rolled-up film cost
      plus the bag line's time and the range's margin, rather than typed in.

    Returns {name: product.product}.
    """
    Bom = env["mrp.bom"]
    bags = {}
    available = dict(materials, **products)

    for name, spec in specs.items():
        film = available[spec["film"]]
        line = workcenters[spec.get("workcenter", default_workcenter)]
        run_qty = spec.get("run_qty", BAG_RUN_QTY)
        film_per_bag = film_kg_per_bag(spec["grams_per_bag"], spec["waste_pct"])
        run_film_kg = round(film_per_bag * run_qty, 3)

        extras_cost = sum(
            available[extra_name].standard_price * qty
            for extra_name, qty in spec["extras"]
        )
        cost = bag_cost(spec, film.standard_price, extras_cost, line.costs_hour, run_qty)

        bag = _product(
            env,
            name,
            {
                "type": "consu",
                "is_storable": True,
                # Counted, not weighed. The customer orders bags.
                "uom_id": uoms[UNIT].id,
                "categ_id": categories[categ_name].id,
                "default_code": spec["code"],
                "purchase_ok": False,
                "sale_ok": True,
                # The certification claim travels with the product onto the
                # quotation and the delivery note, which is where a customer
                # reads it and where it has to be accurate.
                "description_sale": spec["certification"],
            },
        )
        bags[name] = bag

        template = bag.product_tmpl_id
        template.standard_price = round(cost, 4)
        template.list_price = round(bag_price(cost, spec["margin"]), 4)
        # Kilogrammes per finished bag - the conversion, on the product itself.
        template.weight = round(spec["grams_per_bag"] / 1000.0, 5)

        bom_lines = [
            (
                0,
                0,
                {
                    "product_id": film.id,
                    "product_qty": run_film_kg,
                    "product_uom_id": film.uom_id.id,
                },
            )
        ]
        for extra_name, qty in spec["extras"]:
            extra = available[extra_name]
            bom_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": extra.id,
                        "product_qty": qty,
                        "product_uom_id": extra.uom_id.id,
                    },
                )
            )

        # The offcut the converting waste represents, back to the granulator.
        scrap_kg = round((film_per_bag - spec["grams_per_bag"] / 1000.0) * run_qty, 3)
        byproducts = [
            (
                0,
                0,
                {
                    "product_id": materials[SCRAP_MATERIAL].id,
                    "product_qty": scrap_kg,
                    "product_uom_id": materials[SCRAP_MATERIAL].uom_id.id,
                    "cost_share": 1.0,
                },
            )
        ]

        vals = {
            "product_tmpl_id": template.id,
            "product_qty": run_qty,
            "product_uom_id": bag.uom_id.id,
            "type": "normal",
            "company_id": company.id,
            "bom_line_ids": [(5, 0, 0)] + bom_lines,
            "operation_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "name": spec.get("operation", default_operation),
                        "workcenter_id": line.id,
                        "time_cycle_manual": spec["minutes"],
                    },
                ),
            ],
            "byproduct_ids": [(5, 0, 0)] + byproducts,
        }
        existing = Bom.search(
            [
                ("product_tmpl_id", "=", template.id),
                ("company_id", "in", (False, company.id)),
            ],
            limit=1,
        )
        if existing:
            existing.write(vals)
        else:
            Bom.create(vals)

        _logger.info(
            "centric_manufacturing_demo: %s - %.4g kg film per unit, run of %g, "
            "cost %.4f, price %.4f",
            spec["code"],
            film_per_bag,
            run_qty,
            cost,
            template.list_price,
        )
    return bags


def _create_custom_print_products(env, uoms, categories, materials, workcenters,
                                  products, company):
    """P3.8 - the custom printed bag: one variant per customer artwork, made to
    order.

    Three pieces, and the order matters:

    1. an **attribute** whose values are the live artworks, so Odoo generates a
       variant per artwork and a sales order line names the artwork rather than
       carrying it as a comment nobody can report on;
    2. the **make to order and manufacture routes** on the template, so
       confirming an order raises a works order for the quantity ordered
       instead of trying to reserve printed bags that by definition are not in
       stock;
    3. a **bill of materials per variant**, because a three colour job is not
       the same recipe as a one colour job - it consumes another ink and costs
       another deck of press time.

    See ``custom_print_data`` on why the plate sets are not components.

    Returns {variant display name: product.product}.
    """
    Bom = env["mrp.bom"]
    available = dict(materials, **products)
    film = available[CUSTOM_PRINT_FILM]
    press = workcenters["TP-FLEXO6"]
    slitter = workcenters["TP-SLIT"]
    bag_line = workcenters["TP-BAGLINE"]

    # ---- 1. the artwork attribute and its values --------------------------
    Attribute = env["product.attribute"]
    Value = env["product.attribute.value"]
    attribute = Attribute.search([("name", "=", ARTWORK_ATTRIBUTE)], limit=1)
    if not attribute:
        attribute = Attribute.create(
            {
                "name": ARTWORK_ATTRIBUTE,
                # A variant each: the artwork changes the recipe, so it has to
                # be a real product that can be costed, forecast and reported
                # on, not a decoration on the order line.
                "create_variant": "always",
                "display_type": "radio",
            }
        )
    values = {}
    for artwork_name in ARTWORKS:
        value = Value.search(
            [("name", "=", artwork_name), ("attribute_id", "=", attribute.id)], limit=1
        )
        if not value:
            value = Value.create(
                {"name": artwork_name, "attribute_id": attribute.id}
            )
        values[artwork_name] = value

    # ---- 2. the template, with the routes that make it made to order ------
    routes = env["stock.route"].browse()
    for xmlid in ("stock.route_warehouse0_mto", "mrp.route_warehouse0_manufacture"):
        route = env.ref(xmlid, raise_if_not_found=False)
        if not route:
            continue
        if not route.active:
            # Odoo ships Replenish on Order archived, on the grounds that most
            # databases never want it. This one does: it is the whole point of
            # a custom printed bag.
            route.active = True
        routes |= route
    if len(routes) < 2:
        _logger.warning(
            "centric_manufacturing_demo: make-to-order or manufacture route not "
            "found - the custom print range will be created but will not "
            "replenish on order"
        )

    template = env["product.template"].search(
        [("name", "=", CUSTOM_PRINT_PRODUCT)], limit=1
    )
    if not template:
        template = env["product.template"].create(
            {
                "name": CUSTOM_PRINT_PRODUCT,
                "type": "consu",
                "is_storable": True,
                "uom_id": uoms[UNIT].id,
                "categ_id": categories[FINISHED_BAG_CATEG].id,
                "default_code": CUSTOM_PRINT_CODE,
                "purchase_ok": False,
                "sale_ok": True,
                "weight": round(CUSTOM_GRAMS_PER_BAG / 1000.0, 5),
                "route_ids": [(6, 0, routes.ids)],
                "attribute_line_ids": [
                    (
                        0,
                        0,
                        {
                            "attribute_id": attribute.id,
                            "value_ids": [(6, 0, [v.id for v in values.values()])],
                        },
                    )
                ],
            }
        )
    else:
        # An upgrade that adds an artwork: extend the existing attribute line
        # rather than replacing it, so variants already sold keep their ids and
        # their history.
        line = template.attribute_line_ids.filtered(
            lambda l: l.attribute_id == attribute
        )[:1]
        if line:
            missing = [
                value.id for value in values.values() if value not in line.value_ids
            ]
            if missing:
                line.value_ids = [(4, value_id) for value_id in missing]

    # ---- 3. a bill of materials per artwork -------------------------------
    film_per_bag = film_kg_per_bag(CUSTOM_GRAMS_PER_BAG, CUSTOM_WASTE_PCT)
    run_film_kg = round(film_per_bag * CUSTOM_RUN_QTY, 3)
    scrap_kg = round(
        (film_per_bag - CUSTOM_GRAMS_PER_BAG / 1000.0) * CUSTOM_RUN_QTY, 3
    )
    carton = available["Export Carton 600x400x400"]
    core = available['Paper Core 76mm (3")']
    scrap = materials[SCRAP_MATERIAL]

    variants = {}
    costs = {}
    for artwork_name, spec in ARTWORKS.items():
        value = values[artwork_name]
        variant = template.product_variant_ids.filtered(
            lambda v: value in v.product_template_variant_value_ids.product_attribute_value_id
        )[:1]
        if not variant:
            _logger.warning(
                "centric_manufacturing_demo: no variant generated for artwork "
                "%r, bill of materials skipped",
                artwork_name,
            )
            continue
        variants[artwork_name] = variant

        colours = spec["colours"]
        bom_lines = [
            (0, 0, {
                "product_id": film.id,
                "product_qty": run_film_kg,
                "product_uom_id": film.uom_id.id,
            }),
            (0, 0, {
                "product_id": core.id,
                "product_qty": CORES_PER_RUN,
                "product_uom_id": core.uom_id.id,
            }),
            (0, 0, {
                "product_id": carton.id,
                "product_qty": CARTONS_PER_RUN,
                "product_uom_id": carton.uom_id.id,
            }),
        ]
        cost = film.standard_price * film_per_bag
        cost += (
            core.standard_price * CORES_PER_RUN
            + carton.standard_price * CARTONS_PER_RUN
        ) / CUSTOM_RUN_QTY
        for ink_name, qty in artwork_inks(colours):
            ink = available[ink_name]
            cost += ink.standard_price * qty / CUSTOM_RUN_QTY
            bom_lines.append(
                (0, 0, {
                    "product_id": ink.id,
                    "product_qty": qty,
                    "product_uom_id": ink.uom_id.id,
                })
            )

        operations = []
        minutes = press_minutes(colours)
        if minutes:
            cost += press.costs_hour * minutes / 60.0 / CUSTOM_RUN_QTY
            operations.append(
                (0, 0, {
                    "name": "Mount plates %s and print %s colour"
                            % (spec["plate_ref"], colours),
                    "workcenter_id": press.id,
                    "time_cycle_manual": minutes,
                })
            )
            cost += slitter.costs_hour * SLIT_MINUTES / 60.0 / CUSTOM_RUN_QTY
            operations.append(
                (0, 0, {
                    "name": "Slit to bag web width",
                    "workcenter_id": slitter.id,
                    "time_cycle_manual": SLIT_MINUTES,
                })
            )
        cost += bag_line.costs_hour * BAG_LINE_MINUTES / 60.0 / CUSTOM_RUN_QTY
        operations.append(
            (0, 0, {
                "name": "Convert, seal and cut to bags",
                "workcenter_id": bag_line.id,
                "time_cycle_manual": BAG_LINE_MINUTES,
            })
        )

        vals = {
            "product_tmpl_id": template.id,
            # Pinned to the variant: this recipe is this artwork's, and a BoM
            # left at template level would print the bakery's job on the
            # co-operative's order.
            "product_id": variant.id,
            "product_qty": CUSTOM_RUN_QTY,
            "product_uom_id": variant.uom_id.id,
            "type": "normal",
            "company_id": company.id,
            "bom_line_ids": [(5, 0, 0)] + bom_lines,
            "operation_ids": [(5, 0, 0)] + operations,
            "byproduct_ids": [
                (5, 0, 0),
                (0, 0, {
                    "product_id": scrap.id,
                    "product_qty": scrap_kg,
                    "product_uom_id": scrap.uom_id.id,
                    "cost_share": 1.0,
                }),
            ],
        }
        existing = Bom.search(
            [
                ("product_id", "=", variant.id),
                ("company_id", "in", (False, company.id)),
            ],
            limit=1,
        )
        if existing:
            existing.write(vals)
        else:
            Bom.create(vals)

        variant.write(
            {
                "default_code": "%s-%s" % (CUSTOM_PRINT_CODE, colours or "PLAIN"),
                "description_sale": artwork_description(artwork_name, spec),
                # Cost is genuinely per variant - it is a field on the variant,
                # not on the template - so each artwork carries its own.
                "standard_price": round(cost, 4),
            }
        )
        costs[artwork_name] = cost

    # ---- 4. price per artwork ---------------------------------------------
    # The sale price is a template field, so a variant cannot simply be given
    # its own. Odoo's mechanism for this is ``price_extra`` on the attribute
    # value: the template carries the cheapest artwork's price and each value
    # adds what it costs over that one. Which is also how the plant talks about
    # it - a price for the bag, plus so much a colour.
    if costs:
        base_cost = min(costs.values())
        base_price = bag_price(base_cost, CUSTOM_MARGIN)
        template.list_price = round(base_price, 4)
        for artwork_name, cost in costs.items():
            variant = variants[artwork_name]
            ptav = variant.product_template_variant_value_ids.filtered(
                lambda v: v.attribute_id == attribute
            )[:1]
            price = bag_price(cost, CUSTOM_MARGIN)
            if ptav:
                ptav.price_extra = round(price - base_price, 4)
            _logger.info(
                "centric_manufacturing_demo: artwork %s - %s colour, cost %.4f, "
                "price %.4f",
                artwork_name,
                ARTWORKS[artwork_name]["colours"],
                cost,
                price,
            )
    return variants


def _enable_traceability(env, warehouse, tracked):
    """P4.8 - turn on lot tracking and put the tracked products on it.

    Three things have to be true before a resin batch can be traced to a
    delivered pallet, and all three are done here:

    1. **The feature is on.** Lots and serial numbers are behind a settings
       group; without it the fields exist but no user can see or fill them.
    2. **The products are tracked.** Only the ones that can carry a defect
       forward - see ``traceability_data`` on why cores, cartons and recovered
       scrap are not.
    3. **The transfers ask for a lot.** A receipt has to be allowed to *create*
       one, because the number comes off the supplier's delivery note and Odoo
       has never seen it before; everything internal picks from lots that
       already exist.

    A product that already has stock and no lots may refuse to change tracking,
    which is Odoo protecting a valuation it cannot retrospectively split. That
    is a per-product savepoint and a warning, not a failed install: the rest of
    the chain is still worth having, and the log names what needs doing by
    hand.
    """
    lot_group = env.ref("stock.group_production_lot", raise_if_not_found=False)
    if not lot_group:
        _logger.warning(
            "centric_manufacturing_demo: lot/serial group not found, "
            "traceability skipped"
        )
        return 0
    internal_user = env.ref("base.group_user", raise_if_not_found=False)
    if internal_user and lot_group not in internal_user.implied_ids:
        internal_user.write({"implied_ids": [(4, lot_group.id)]})

    turned_on = 0
    for product in tracked:
        template = product.product_tmpl_id
        if template.tracking != "none":
            continue
        try:
            with env.cr.savepoint():
                template.tracking = "lot"
            turned_on += 1
        except Exception as error:  # noqa: BLE001 - one product, not the install
            _logger.warning(
                "centric_manufacturing_demo: could not put %s on lot tracking "
                "- %s",
                template.display_name,
                error,
            )

    # Receipts mint lot numbers off the supplier's delivery note; everything
    # else consumes numbers that already exist.
    if warehouse.in_type_id:
        warehouse.in_type_id.write({"use_create_lots": True, "use_existing_lots": True})
    for picking_type in (
        warehouse.out_type_id | warehouse.int_type_id | warehouse.pick_type_id
    ):
        picking_type.use_existing_lots = True
    manufacturing_type = env["stock.picking.type"].search(
        [("code", "=", "mrp_operation"), ("warehouse_id", "=", warehouse.id)]
    )
    # A works order both creates a lot - the run it just made - and consumes
    # the reel and resin lots it was fed.
    manufacturing_type.write({"use_create_lots": True, "use_existing_lots": True})
    return turned_on


def _warehouse(env, company):
    """Return the plant's warehouse, creating one if the company has none.

    A company that had Inventory installed after it was created never got the
    warehouse Odoo normally makes for it, which is the state the plant company
    was found in: no warehouse means no stock location, so opening counts,
    receipts, manufacturing orders and deliveries all have nowhere to go and
    silently do nothing. Everything downstream of this in the seed depends on
    it existing.
    """
    Warehouse = env["stock.warehouse"]
    warehouse = Warehouse.search([("company_id", "=", company.id)], limit=1)
    if not warehouse:
        warehouse = Warehouse.create(
            {
                "name": "%s Plant" % company.name,
                # Short, and prefixed on every picking reference the plant
                # produces, so it wants to read as the site rather than the
                # company: TP/IN/00001.
                "code": "TP",
                "company_id": company.id,
            }
        )
        _logger.info(
            "centric_manufacturing_demo: created warehouse %s for %s",
            warehouse.code,
            company.display_name,
        )
    return warehouse


def _set_opening_stock(env, warehouse, materials, company):
    """Apply a one-off opening count for every bought-in material.

    Only materials that currently hold no stock are counted in, so upgrading
    the module does not silently reset a live store.

    A tracked material is counted in **under a lot** (P4.8). Opening stock with
    no lot on it is a hole at the very start of the traceability chain: the
    first reel the plant extrudes would trace back to nothing at all, which is
    the one answer a recall cannot accept. One lot per material, standing for
    "what was on the floor at cutover" - which is what it honestly is, and the
    plant should split it against the real delivery notes before go-live.
    """
    location = warehouse.lot_stock_id
    Quant = env["stock.quant"].with_context(inventory_mode=True)

    counted = 0
    opening = {name: qty for name, (_uom, _cost, qty) in RAW_MATERIALS.items()}
    opening[SCRAP_MATERIAL] = SCRAP_OPENING_QTY
    for name, qty in opening.items():
        product = materials[name]
        # Scoped to the plant's own stock location: whether a material is
        # already counted in is a question about this warehouse, not about
        # every company on the database.
        if product.with_context(location=location.id).qty_available:
            continue
        vals = {
            "product_id": product.id,
            "location_id": location.id,
            "inventory_quantity": qty,
        }
        if product.tracking != "none":
            vals["lot_id"] = create_lot(env, product, company).id
        Quant.create(vals).action_apply_inventory()
        counted += 1
    return counted


def _create_suppliers(env):
    """Create any missing vendor partner, return {name: res.partner}."""
    Partner = env["res.partner"]
    partners = {}
    for name, vals in SUPPLIERS.items():
        partner = Partner.search([("name", "=", name)], limit=1)
        if not partner:
            partner = Partner.create(
                {
                    "name": name,
                    "company_type": "company",
                    "supplier_rank": 1,
                    "street": vals["street"],
                    "city": vals["city"],
                    "zip": vals["zip"],
                    "phone": vals["phone"],
                    "email": vals["email"],
                }
            )
        partners[name] = partner
    return partners


def _create_price_lists(env, partners, materials):
    """Add a purchase price list line per material/vendor pair.

    Existing lines for the same product and vendor are left alone - agreed
    terms are the buyer's to change, not the module's.
    """
    Supplierinfo = env["product.supplierinfo"]
    created = 0
    for material_name, (primary, backup) in SOURCING.items():
        product = materials.get(material_name)
        if not product:
            _logger.warning(
                "centric_manufacturing_demo: material %r not found, sourcing skipped",
                material_name,
            )
            continue

        uom_xmlid, cost, _qty = RAW_MATERIALS[material_name]
        min_qty = MIN_QTY_OVERRIDE.get(material_name, MIN_QTY_BY_UOM[uom_xmlid])
        candidates = [(primary, cost, 1)]
        if backup:
            candidates.append((backup, round(cost * BACKUP_PRICE_UPLIFT, 4), 2))

        for vendor_name, price, sequence in candidates:
            partner = partners[vendor_name]
            if Supplierinfo.search(
                [
                    ("partner_id", "=", partner.id),
                    ("product_tmpl_id", "=", product.product_tmpl_id.id),
                ],
                limit=1,
            ):
                continue
            Supplierinfo.create(
                {
                    "partner_id": partner.id,
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "price": price,
                    "min_qty": min_qty,
                    "delay": SUPPLIERS[vendor_name]["delay"],
                    "sequence": sequence,
                    "currency_id": env.company.currency_id.id,
                }
            )
            created += 1
    return created


def _create_orderpoints(env, warehouse, materials):
    """P5.3 - a reordering rule per bought-in material, return how many made.

    The rule is built from the material's run-rate and the lead time on its
    primary vendor's price list line, so the two numbers that drive it are both
    visible in Odoo rather than hard-coded here. A material with no vendor line
    is skipped: a reorder point with nobody to buy from raises a replenishment
    Odoo cannot source, which just fills the buyer's screen with errors.

    An existing rule for the same product and location is left alone.
    """
    Orderpoint = env["stock.warehouse.orderpoint"]
    location = warehouse.lot_stock_id
    created = 0

    for name, monthly in MONTHLY_USAGE.items():
        product = materials.get(name)
        if not product:
            _logger.warning(
                "centric_manufacturing_demo: material %r not found, reordering "
                "rule skipped",
                name,
            )
            continue
        if Orderpoint.with_context(active_test=False).search(
            [("product_id", "=", product.id), ("location_id", "=", location.id)],
            limit=1,
        ):
            continue

        # Cheapest first is Odoo's own ordering on the price list, but the
        # buyer's preference is the sequence, so take the first line as primary.
        seller = product.seller_ids.sorted(lambda s: (s.sequence, s.id))[:1]
        if not seller:
            _logger.warning(
                "centric_manufacturing_demo: %r has no vendor price list line, "
                "reordering rule skipped",
                name,
            )
            continue

        min_qty, max_qty = reorder_levels(
            monthly, float(seller.delay), seller.min_qty
        )
        Orderpoint.create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "warehouse_id": warehouse.id,
                "company_id": warehouse.company_id.id,
                "product_min_qty": min_qty,
                "product_max_qty": max_qty,
            }
        )
        created += 1
    return created


def _create_landed_cost_products(env):
    """P5.4 - the landed cost service products, if Landed Costs is installed.

    ``landed_cost_ok`` only exists once ``stock_landed_costs`` is installed,
    and that module is not a dependency here - see ``landed_cost_data``. When
    it is absent this is a no-op and the install carries on; install the app
    and upgrade this module and the products appear.
    """
    Template = env["product.template"]
    if "landed_cost_ok" not in Template._fields:
        _logger.info(
            "centric_manufacturing_demo: stock_landed_costs is not installed, "
            "landed cost products skipped"
        )
        return 0

    created = 0
    for name, (split_method, cost, description) in LANDED_COSTS.items():
        if Template.search([("name", "=", name)], limit=1):
            continue
        Template.create(
            {
                "name": name,
                "type": "service",
                "landed_cost_ok": True,
                "split_method_landed_cost": split_method,
                "standard_price": cost,
                "purchase_ok": True,
                "sale_ok": False,
                "description": description,
            }
        )
        created += 1
    return created


def _create_quality_points(env, warehouse, materials, products, bags, company):
    """P7.1 - quality checkpoints, if Quality Control is installed.

    Same conditional treatment as the landed costs, and for the same reason:
    Quality is a separate app. The points attached to a manufacturing operation
    additionally need ``quality_mrp`` for ``quality.point`` to carry an
    ``operation_id`` at all; without it those points are still created, just
    against the product rather than pinned to the operation, which is the
    weaker but still useful half of the check.
    """
    if "quality.point" not in env:
        _logger.info(
            "centric_manufacturing_demo: quality_control is not installed, "
            "quality checkpoints skipped"
        )
        return 0

    Point = env["quality.point"]
    fields = Point._fields
    available = dict(materials, **dict(products, **bags))

    test_types = {}
    for technical_name in ("passfail", "measure", "instructions"):
        test_type = env.ref(
            "quality_control.test_type_%s" % technical_name, raise_if_not_found=False
        )
        if test_type:
            test_types[technical_name] = test_type

    manufacturing_type = env["stock.picking.type"].search(
        [("code", "=", "mrp_operation"), ("warehouse_id", "=", warehouse.id)], limit=1
    )
    incoming_type = warehouse.in_type_id

    created = 0
    for title, spec in QUALITY_POINTS.items():
        if Point.search([("title", "=", title)], limit=1):
            continue

        products_on_point = [
            available[name].product_tmpl_id.id
            for name in spec["products"]
            if name in available
        ]
        picking_type = incoming_type if spec["picking_type"] == "incoming" else manufacturing_type
        if not picking_type:
            _logger.warning(
                "centric_manufacturing_demo: no picking type for quality point "
                "%r, skipped",
                title,
            )
            continue

        vals = {
            "title": title,
            "picking_type_ids": [(6, 0, [picking_type.id])],
            "product_ids": [(6, 0, products_on_point)],
            "note": spec["note"],
            "company_id": company.id,
        }
        test_type = test_types.get(spec["test_type"])
        if test_type:
            vals["test_type_id"] = test_type.id
        if spec["test_type"] == "measure":
            vals.update(
                norm=spec["norm"],
                tolerance_min=spec["tolerance_min"],
                tolerance_max=spec["tolerance_max"],
                norm_unit=spec["norm_unit"],
            )

        # quality_mrp is what lets a point name the operation it is checked at.
        # Without it the point still applies, just to the order as a whole.
        if spec["operation"] and "operation_id" in fields:
            operation = env["mrp.routing.workcenter"].search(
                [("name", "=", spec["operation"]), ("company_id", "=", company.id)],
                limit=1,
            )
            if operation:
                vals["operation_id"] = operation.id

        Point.create({key: value for key, value in vals.items() if key in fields})
        created += 1
    return created


def post_init_hook(env):
    # Everything is seeded in the plant's company, whichever company the user
    # running the install happens to be in. Rebinding the environment also puts
    # the warehouse lookup and the vendor price lines in the right company.
    company = _plant_company(env)
    env = env(
        context=dict(
            env.context,
            allowed_company_ids=[company.id]
            + [cid for cid in env.context.get("allowed_company_ids", []) if cid != company.id],
        )
    )

    uoms = _resolve_uoms(env)
    categories = _categories(env)
    # Before any product exists or any stock is counted in: the costing method
    # has to be the one in force when the first layer lands, not one applied to
    # it afterwards.
    costed = _set_costing_policy(env, company, categories)
    materials = _create_raw_materials(env, uoms, categories)
    workcenters = _create_workcenters(env, company)
    products = _create_boms(env, uoms, categories, materials, workcenters, company)
    # The bags come after the film: their BoMs consume it, and their prices are
    # computed from the cost it has just rolled up. The industrial range is the
    # same machinery over a different table - see _create_converted.
    bags = _create_converted(
        env,
        uoms,
        categories,
        materials,
        workcenters,
        products,
        company,
        FINISHED_BAGS,
        FINISHED_BAG_CATEG,
    )
    industrial = _create_converted(
        env,
        uoms,
        categories,
        materials,
        workcenters,
        products,
        company,
        INDUSTRIAL_PACKAGING,
        INDUSTRIAL_CATEG,
    )
    artworks = _create_custom_print_products(
        env, uoms, categories, materials, workcenters, products, company
    )
    warehouse = _warehouse(env, company)
    # Before the opening count and before anything trades: a product put on lot
    # tracking after it already holds stock leaves that stock unlabelled, which
    # is a hole at the start of the chain rather than the end of it.
    tracked = [
        product
        for product in list(materials.values())
        + list(products.values())
        + list(bags.values())
        + list(industrial.values())
        + list(artworks.values())
        if product.product_tmpl_id.name not in UNTRACKED_MATERIALS
        and product.product_tmpl_id.name != SCRAP_MATERIAL
    ]
    on_lots = _enable_traceability(env, warehouse, tracked)
    counted = _set_opening_stock(env, warehouse, materials, company)
    partners = _create_suppliers(env)
    price_lines = _create_price_lists(env, partners, materials)
    # After the price lists: the reorder point reads its lead time and minimum
    # order quantity off the vendor line the call above has just made.
    orderpoints = _create_orderpoints(env, warehouse, materials)
    landed = _create_landed_cost_products(env)
    checkpoints = _create_quality_points(
        env, warehouse, materials, products, dict(bags, **industrial), company
    )
    _logger.info(
        "centric_manufacturing_demo: seeded %s - %s categories put on FIFO, "
        "%s materials, %s work centres, %s BoMs, %s bags, %s industrial items, "
        "%s custom print artworks, %s products put on lot tracking, "
        "%s opening counts, %s vendors, %s purchase price lines, "
        "%s reordering rules, %s landed cost products and %s quality checkpoints",
        company.display_name,
        costed,
        len(materials),
        len(workcenters),
        len(products),
        len(bags),
        len(industrial),
        len(artworks),
        on_lots,
        counted,
        len(partners),
        price_lines,
        orderpoints,
        landed,
        checkpoints,
    )

    # The trading history comes last and only once the master data is in
    # place: it buys the materials above, consumes them through the BoMs above
    # and sells the result, so it has nothing to work with until they exist.
    seed_transactions(env, company, partners, materials, products)
