# -*- coding: utf-8 -*-
import logging

from .material_data import (
    FINISHED_CATEG,
    KG,
    MANUFACTURED,
    RAW_CATEG,
    RAW_MATERIALS,
    SCRAP_COST,
    SCRAP_MATERIAL,
    SCRAP_OPENING_QTY,
    UNIT,
    WIP_CATEG,
)
from .supplier_data import (
    BACKUP_PRICE_UPLIFT,
    MIN_QTY_BY_UOM,
    MIN_QTY_OVERRIDE,
    SOURCING,
    SUPPLIERS,
)
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
    """Return {category name: product.category}, creating any that are missing."""
    Categ = env["product.category"]
    categories = {}
    for name in (RAW_CATEG, WIP_CATEG, FINISHED_CATEG):
        categ = Categ.search([("name", "=", name)], limit=1)
        if not categ:
            categ = Categ.create({"name": name})
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


def _create_workcenters(env):
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
            workcenter = Workcenter.create(dict(vals, code=code))
            _logger.info(
                "centric_manufacturing_demo: created work centre %s (%s)",
                code,
                vals["name"],
            )
        workcenters[code] = workcenter
    return workcenters


def _create_boms(env, uoms, categories, materials, workcenters):
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

        vals = {
            "product_tmpl_id": product.product_tmpl_id.id,
            "product_qty": run_qty,
            "product_uom_id": product.uom_id.id,
            "type": "normal",
            "bom_line_ids": [(5, 0, 0)] + bom_lines,
            "operation_ids": [(5, 0, 0)] + operations,
        }
        existing = Bom.search([("product_tmpl_id", "=", product.product_tmpl_id.id)], limit=1)
        if existing:
            existing.write(vals)
        else:
            Bom.create(vals)

        # Cost per base unit, so it is comparable with the bought-in materials.
        product.product_tmpl_id.standard_price = round(cost / run_qty, 4)
    return products


def _set_opening_stock(env, materials):
    """Apply a one-off opening count for every bought-in material.

    Only materials that currently hold no stock are counted in, so upgrading
    the module does not silently reset a live store.
    """
    warehouse = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
    if not warehouse:
        _logger.warning("centric_manufacturing_demo: no warehouse, opening stock skipped")
        return 0
    location = warehouse.lot_stock_id
    Quant = env["stock.quant"].with_context(inventory_mode=True)

    counted = 0
    opening = {name: qty for name, (_uom, _cost, qty) in RAW_MATERIALS.items()}
    opening[SCRAP_MATERIAL] = SCRAP_OPENING_QTY
    for name, qty in opening.items():
        product = materials[name]
        if product.qty_available:
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


def post_init_hook(env):
    uoms = _resolve_uoms(env)
    categories = _categories(env)
    materials = _create_raw_materials(env, uoms, categories)
    workcenters = _create_workcenters(env)
    products = _create_boms(env, uoms, categories, materials, workcenters)
    counted = _set_opening_stock(env, materials)
    partners = _create_suppliers(env)
    price_lines = _create_price_lists(env, partners, materials)
    _logger.info(
        "centric_manufacturing_demo: %s materials, %s work centres, %s BoMs, "
        "%s opening counts, %s vendors and %s purchase price lines",
        len(materials),
        len(workcenters),
        len(products),
        counted,
        len(partners),
        price_lines,
    )
