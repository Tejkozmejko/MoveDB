# -*- coding: utf-8 -*-
import logging

from .landed_cost_data import LANDED_COSTS
from .material_data import (
    BAG_RUN_QTY,
    CATEG_ORDER,
    CATEG_PARENT,
    FILM_MARGIN,
    FINISHED_BAG_CATEG,
    FINISHED_BAGS,
    KG,
    MANUFACTURED,
    RAW_CATEG,
    RAW_MATERIALS,
    SCRAP_COST,
    SCRAP_MATERIAL,
    SCRAP_OPENING_QTY,
    UNIT,
)
from .pricing import bag_cost, bag_price, film_kg_per_bag, with_margin
from .quality_data import QUALITY_POINTS
from .supplier_data import (
    BACKUP_PRICE_UPLIFT,
    MIN_QTY_BY_UOM,
    MIN_QTY_OVERRIDE,
    SOURCING,
    SUPPLIERS,
)
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


def _create_bags(env, uoms, categories, materials, workcenters, products, company):
    """P3/P3.2/P6.4 - the finished bag range, where kilogrammes become units.

    Each bag gets three things the film products above do not need:

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
    bag_line = workcenters["TP-BAGLINE"]
    bags = {}
    available = dict(materials, **products)

    for name, spec in FINISHED_BAGS.items():
        film = available[spec["film"]]
        film_per_bag = film_kg_per_bag(spec["grams_per_bag"], spec["waste_pct"])
        run_film_kg = round(film_per_bag * BAG_RUN_QTY, 3)

        extras_cost = sum(
            available[extra_name].standard_price * qty
            for extra_name, qty in spec["extras"]
        )
        cost = bag_cost(spec, film.standard_price, extras_cost, bag_line.costs_hour)

        bag = _product(
            env,
            name,
            {
                "type": "consu",
                "is_storable": True,
                # Counted, not weighed. The customer orders bags.
                "uom_id": uoms[UNIT].id,
                "categ_id": categories[FINISHED_BAG_CATEG].id,
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
        scrap_kg = round(
            (film_per_bag - spec["grams_per_bag"] / 1000.0) * BAG_RUN_QTY, 3
        )
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
            "product_qty": BAG_RUN_QTY,
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
                        "name": "Convert, seal and cut to bags",
                        "workcenter_id": bag_line.id,
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
            "centric_manufacturing_demo: bag %s - %.4g kg film per bag, "
            "cost %.4f, price %.4f",
            spec["code"],
            film_per_bag,
            cost,
            template.list_price,
        )
    return bags


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


def _set_opening_stock(env, warehouse, materials):
    """Apply a one-off opening count for every bought-in material.

    Only materials that currently hold no stock are counted in, so upgrading
    the module does not silently reset a live store.
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
        Quant.create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "inventory_quantity": qty,
            }
        ).action_apply_inventory()
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
    materials = _create_raw_materials(env, uoms, categories)
    workcenters = _create_workcenters(env, company)
    products = _create_boms(env, uoms, categories, materials, workcenters, company)
    # The bags come after the film: their BoMs consume it, and their prices are
    # computed from the cost it has just rolled up.
    bags = _create_bags(
        env, uoms, categories, materials, workcenters, products, company
    )
    warehouse = _warehouse(env, company)
    counted = _set_opening_stock(env, warehouse, materials)
    partners = _create_suppliers(env)
    price_lines = _create_price_lists(env, partners, materials)
    landed = _create_landed_cost_products(env)
    checkpoints = _create_quality_points(
        env, warehouse, materials, products, bags, company
    )
    _logger.info(
        "centric_manufacturing_demo: seeded %s - %s materials, %s work centres, "
        "%s BoMs, %s bags, %s opening counts, %s vendors, %s purchase price lines, "
        "%s landed cost products and %s quality checkpoints",
        company.display_name,
        len(materials),
        len(workcenters),
        len(products),
        len(bags),
        counted,
        len(partners),
        price_lines,
        landed,
        checkpoints,
    )

    # The trading history comes last and only once the master data is in
    # place: it buys the materials above, consumes them through the BoMs above
    # and sells the result, so it has nothing to work with until they exist.
    seed_transactions(env, company, partners, materials, products)
