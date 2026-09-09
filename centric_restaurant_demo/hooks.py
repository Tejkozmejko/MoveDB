# -*- coding: utf-8 -*-
import logging

from .recipe_data import INGREDIENTS, RECIPES, G, ML, UNIT
from .supplier_data import BACKUP_PRICE_UPLIFT, MIN_QTY_BY_UOM, SOURCING, SUPPLIERS

_logger = logging.getLogger(__name__)

# Fallback UoM names, used when the expected external id is not present in the
# database (the millilitre xmlid in particular has been renamed across
# versions). These match the names shown in the UoM list.
_UOM_FALLBACK_NAME = {G: "g", ML: "ml", UNIT: "Units"}

INGREDIENT_CATEG = "Restaurant Ingredients"


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


def _ingredient_category(env):
    Categ = env["product.category"]
    categ = Categ.search([("name", "=", INGREDIENT_CATEG)], limit=1)
    if not categ:
        categ = Categ.create({"name": INGREDIENT_CATEG})
    return categ


def _create_ingredients(env, uoms, categ):
    """Create any missing ingredient product, return {name: product.product}."""
    Template = env["product.template"]
    products = {}
    for name, (uom_xmlid, cost, _qty) in INGREDIENTS.items():
        uom = uoms[uom_xmlid]
        tmpl = Template.search([("name", "=", name)], limit=1)
        if not tmpl:
            tmpl = Template.create(
                {
                    "name": name,
                    "type": "consu",
                    "is_storable": True,
                    "uom_id": uom.id,
                    "categ_id": categ.id,
                    "standard_price": cost,
                    "available_in_pos": False,
                    "purchase_ok": True,
                    "sale_ok": False,
                }
            )
        products[name] = tmpl.product_variant_id
    return products


def _create_recipes(env, ingredients):
    """Create a kit (phantom) BoM per dish and roll the cost up onto the dish.

    A phantom BoM is exploded by the stock engine when the move is confirmed,
    so a POS sale of the dish generates component moves and depletes the
    ingredients. That is what makes food-cost reporting possible without any
    custom backflush code.
    """
    Template = env["product.template"]
    Bom = env["mrp.bom"]
    for dish_name, lines in RECIPES.items():
        tmpl = Template.search(
            [("name", "=", dish_name), ("available_in_pos", "=", True)], limit=1
        )
        if not tmpl:
            _logger.warning("centric_restaurant_demo: menu item %r not found, skipped", dish_name)
            continue

        # A dish only generates stock moves - and therefore only explodes its
        # kit - if it is stock tracked.
        if not tmpl.is_storable:
            tmpl.is_storable = True

        # Odoo forbids a kit BoM on a product that has a reordering rule
        # ("You can not create a kit-type bill of materials for products that
        # have at least one reordering rule"). Making the dish storable can
        # leave auto-generated orderpoints behind, so clear them first - a dish
        # is produced from its recipe, never replenished as a stocked good.
        orderpoints = env["stock.warehouse.orderpoint"].sudo().with_context(active_test=False).search(
            [("product_id", "in", tmpl.product_variant_ids.ids)]
        )
        if orderpoints:
            orderpoints.unlink()

        cost = 0.0
        bom_lines = []
        for ingredient_name, qty in lines:
            product = ingredients[ingredient_name]
            cost += product.standard_price * qty
            bom_lines.append(
                (0, 0, {"product_id": product.id, "product_qty": qty, "product_uom_id": product.uom_id.id})
            )

        existing = Bom.search([("product_tmpl_id", "=", tmpl.id)], limit=1)
        if existing:
            existing.write({"type": "phantom", "product_qty": 1.0, "bom_line_ids": [(5, 0, 0)] + bom_lines})
        else:
            Bom.create(
                {
                    "product_tmpl_id": tmpl.id,
                    "product_qty": 1.0,
                    "product_uom_id": tmpl.uom_id.id,
                    "type": "phantom",
                    "bom_line_ids": bom_lines,
                }
            )

        # Roll the recipe cost onto the dish so POS margin reporting is real.
        tmpl.standard_price = round(cost, 4)


def _set_opening_stock(env, uoms, ingredients):
    """Apply a one-off opening count for every ingredient.

    Only ingredients that currently hold no stock are counted in, so upgrading
    the module does not silently reset a live storeroom.
    """
    warehouse = env["stock.warehouse"].search(
        [("company_id", "=", env.company.id)], limit=1
    )
    if not warehouse:
        _logger.warning("centric_restaurant_demo: no warehouse, opening stock skipped")
        return
    location = warehouse.lot_stock_id
    Quant = env["stock.quant"].with_context(inventory_mode=True)

    for name, (_uom_xmlid, _cost, qty) in INGREDIENTS.items():
        product = ingredients[name]
        if product.qty_available:
            continue
        Quant.create(
            {
                "product_id": product.id,
                "location_id": location.id,
                "inventory_quantity": qty,
            }
        ).action_apply_inventory()


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


def _create_price_lists(env, partners, ingredients):
    """Add a purchase price list line per ingredient/vendor pair.

    ``price`` is per base unit of the ingredient's own UoM, matching how
    ``standard_price`` is stored, so the primary vendor's price reconciles with
    the cost that the kit BoMs roll up onto the dishes. Existing lines for the
    same product/vendor are left alone - agreed terms are the buyer's to
    change, not the module's.
    """
    Supplierinfo = env["product.supplierinfo"]
    created = 0
    for ingredient_name, (primary, backup) in SOURCING.items():
        product = ingredients.get(ingredient_name)
        if not product:
            _logger.warning(
                "centric_restaurant_demo: ingredient %r not found, sourcing skipped",
                ingredient_name,
            )
            continue

        uom_xmlid, cost, _qty = INGREDIENTS[ingredient_name]
        min_qty = MIN_QTY_BY_UOM[uom_xmlid]
        candidates = [(primary, cost, 1)]
        if backup:
            candidates.append((backup, round(cost * BACKUP_PRICE_UPLIFT, 4), 2))

        for vendor_name, price, sequence in candidates:
            partner = partners[vendor_name]
            existing = Supplierinfo.search(
                [
                    ("partner_id", "=", partner.id),
                    ("product_tmpl_id", "=", product.product_tmpl_id.id),
                ],
                limit=1,
            )
            if existing:
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
    categ = _ingredient_category(env)
    ingredients = _create_ingredients(env, uoms, categ)
    _create_recipes(env, ingredients)
    _set_opening_stock(env, uoms, ingredients)
    partners = _create_suppliers(env)
    price_lines = _create_price_lists(env, partners, ingredients)
    _logger.info(
        "centric_restaurant_demo: %s ingredients, %s recipes, opening stock applied, "
        "%s vendors and %s purchase price lines",
        len(ingredients),
        len(RECIPES),
        len(partners),
        price_lines,
    )
