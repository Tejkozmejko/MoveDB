{
    "name": "Centric Restaurant Demo Data",
    "summary": "Ingredient master, dish recipes (kit BoMs), opening stock and supplier terms for the restaurant POS.",
    "description": """
Fills in the parts of the restaurant rollout that need data rather than
configuration:

* an ingredient master (raw meat, veg, dairy, dry goods, drinks) as storable
  products with a purchase cost per base unit;
* a recipe for every menu dish, stored as a *kit* BoM (type ``phantom``) so
  that selling the dish in the POS explodes into component stock moves and
  actually depletes ingredients - no custom backflush code needed;
* a rolled-up cost price on each dish, computed from its recipe, so POS margin
  and food-cost reporting has real numbers to work with;
* an opening stock count for every ingredient;
* a vendor per trade supplier, and a purchase price list line per ingredient
  with the agreed price, minimum order quantity and delivery lead time - a
  primary vendor for every ingredient plus a dearer backup for most.

The quantities and costs here are PLAUSIBLE DEMO FIGURES, not the customer's
real portion sizes or supplier prices. Replace them before go-live.

Everything runs from a post-init hook and is idempotent: re-installing or
upgrading will not duplicate products, recipes, stock or vendor terms.
""",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "author": "Centric",
    "license": "LGPL-3",
    # mrp: the kit BoMs. stock: opening quants. point_of_sale: the menu.
    "depends": ["point_of_sale", "mrp", "stock"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
