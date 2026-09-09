# -*- coding: utf-8 -*-
"""Demo vendors and purchase price lists for the restaurant ingredient master.

Covers implementation task 7.5 "Suppliers, price lists and lead times": a
vendor record per trade supplier, and a ``product.supplierinfo`` line per
ingredient carrying the agreed price, the minimum order quantity and the
delivery lead time in days.

Every ingredient gets a primary vendor at its standard cost, and most also get
a backup vendor a few percent dearer, so the purchase price list has something
to choose between. As with the recipes, these are PLAUSIBLE DEMO FIGURES, not
the customer's real trading terms.
"""

from .recipe_data import G, ML, UNIT

# Vendor name -> partner values plus the default lead time in days.
SUPPLIERS = {
    "Fenwick Butchers Ltd": {
        "street": "Unit 7, Smithfield Trade Park",
        "city": "Birmingham",
        "zip": "B5 5BS",
        "phone": "+44 121 496 0142",
        "email": "orders@fenwickbutchers.example",
        "delay": 1,
    },
    "Meadowfield Dairy Supplies": {
        "street": "Meadowfield Farm, Ashby Road",
        "city": "Leicester",
        "zip": "LE3 2GH",
        "phone": "+44 116 402 8830",
        "email": "trade@meadowfielddairy.example",
        "delay": 1,
    },
    "Greenacre Produce": {
        "street": "Bay 12, New Covent Garden Market",
        "city": "London",
        "zip": "SW8 5EL",
        "phone": "+44 20 7118 4477",
        "email": "sales@greenacreproduce.example",
        "delay": 1,
    },
    "Kingsway Wholesale Foods": {
        "street": "Kingsway Distribution Centre",
        "city": "Manchester",
        "zip": "M17 1AB",
        "phone": "+44 161 300 5521",
        "email": "accounts@kingswaywholesale.example",
        "delay": 3,
    },
    "Northgate Beverages": {
        "street": "Northgate Cellars, Dock Road",
        "city": "Liverpool",
        "zip": "L3 4BQ",
        "phone": "+44 151 909 2210",
        "email": "orders@northgatebeverages.example",
        "delay": 4,
    },
    "Aldworth Bakery": {
        "street": "14 Mill Lane",
        "city": "Coventry",
        "zip": "CV1 5RG",
        "phone": "+44 24 7655 1180",
        "email": "hello@aldworthbakery.example",
        "delay": 1,
    },
}

# Default minimum order quantity, expressed in the ingredient's own base UoM.
MIN_QTY_BY_UOM = {G: 1000.0, ML: 1000.0, UNIT: 12.0}

# A backup vendor is worth having on file even though it costs a little more.
BACKUP_PRICE_UPLIFT = 1.08

# Ingredient name -> (primary vendor, backup vendor or None).
# The backup is deliberately a broadliner for most specialist lines: it is
# dearer, but it can fill a gap the specialist cannot.
SOURCING = {
    # --- Butchery -----------------------------------------------------------
    "Ribeye Beef (raw)": ("Fenwick Butchers Ltd", None),
    "Beef Burger Patty 6oz": ("Fenwick Butchers Ltd", "Kingsway Wholesale Foods"),
    "Chicken Breast (raw)": ("Fenwick Butchers Ltd", "Kingsway Wholesale Foods"),
    "Streaky Bacon": ("Fenwick Butchers Ltd", "Kingsway Wholesale Foods"),
    # --- Dairy --------------------------------------------------------------
    "Halloumi Cheese": ("Meadowfield Dairy Supplies", "Kingsway Wholesale Foods"),
    "Cheddar Slice": ("Meadowfield Dairy Supplies", "Kingsway Wholesale Foods"),
    "Parmesan": ("Meadowfield Dairy Supplies", None),
    "Cream Cheese": ("Meadowfield Dairy Supplies", "Kingsway Wholesale Foods"),
    "Double Cream": ("Meadowfield Dairy Supplies", None),
    "Butter": ("Meadowfield Dairy Supplies", "Kingsway Wholesale Foods"),
    "Whole Milk": ("Meadowfield Dairy Supplies", None),
    "Egg": ("Meadowfield Dairy Supplies", "Greenacre Produce"),
    # --- Fruit & veg --------------------------------------------------------
    "Potato": ("Greenacre Produce", "Kingsway Wholesale Foods"),
    "White Onion": ("Greenacre Produce", "Kingsway Wholesale Foods"),
    "Tomato": ("Greenacre Produce", None),
    "Lettuce": ("Greenacre Produce", None),
    "Mixed Leaf Salad": ("Greenacre Produce", None),
    "Chestnut Mushroom": ("Greenacre Produce", None),
    "Garlic": ("Greenacre Produce", "Kingsway Wholesale Foods"),
    "Carrot": ("Greenacre Produce", "Kingsway Wholesale Foods"),
    "Celery": ("Greenacre Produce", None),
    # --- Dry goods & store --------------------------------------------------
    "Arborio Rice": ("Kingsway Wholesale Foods", None),
    "Plain Flour": ("Kingsway Wholesale Foods", "Aldworth Bakery"),
    "Caster Sugar": ("Kingsway Wholesale Foods", None),
    "Dark Chocolate": ("Kingsway Wholesale Foods", None),
    "Digestive Biscuit": ("Kingsway Wholesale Foods", "Aldworth Bakery"),
    "Ciabatta Loaf": ("Aldworth Bakery", "Kingsway Wholesale Foods"),
    "Brioche Bun": ("Aldworth Bakery", "Kingsway Wholesale Foods"),
    "Vegetable Stock": ("Kingsway Wholesale Foods", None),
    "Olive Oil": ("Kingsway Wholesale Foods", None),
    "Mayonnaise": ("Kingsway Wholesale Foods", None),
    # --- Cellar & bar -------------------------------------------------------
    "Lager Keg": ("Northgate Beverages", None),
    "House Red Wine": ("Northgate Beverages", None),
    "Cola 330ml Can": ("Northgate Beverages", "Kingsway Wholesale Foods"),
    "Sparkling Water 330ml Bottle": ("Northgate Beverages", "Kingsway Wholesale Foods"),
    "Orange Juice (carton)": ("Northgate Beverages", "Kingsway Wholesale Foods"),
    "Coffee Beans": ("Northgate Beverages", None),
}
