# -*- coding: utf-8 -*-
"""Demo ingredient master, recipes and opening stock for the restaurant POS.

All figures are plausible placeholders for a mid-market UK restaurant, not the
customer's real portions or supplier prices. Costs are per *base unit* of the
ingredient's UoM (per gram, per ml, or per unit), which is how Odoo stores
``standard_price`` when the product UoM is g or ml.
"""

# UoM external ids, resolved at run time.
G = "uom.product_uom_gram"
ML = "uom.product_uom_millilitre"
UNIT = "uom.product_uom_unit"

# name -> (uom xmlid, cost per base unit in GBP, opening stock qty in that uom)
INGREDIENTS = {
    # --- Butchery -----------------------------------------------------------
    "Ribeye Beef (raw)": (G, 0.024, 12000),
    "Beef Burger Patty 6oz": (UNIT, 1.80, 120),
    "Chicken Breast (raw)": (G, 0.0075, 15000),
    "Streaky Bacon": (G, 0.0090, 3000),
    # --- Dairy --------------------------------------------------------------
    "Halloumi Cheese": (G, 0.0110, 4000),
    "Cheddar Slice": (UNIT, 0.18, 200),
    "Parmesan": (G, 0.0140, 1500),
    "Cream Cheese": (G, 0.0050, 3000),
    "Double Cream": (ML, 0.0032, 4000),
    "Butter": (G, 0.0065, 5000),
    "Whole Milk": (ML, 0.0011, 20000),
    "Egg": (UNIT, 0.22, 180),
    # --- Fruit & veg --------------------------------------------------------
    "Potato": (G, 0.0012, 40000),
    "White Onion": (G, 0.0011, 8000),
    "Tomato": (G, 0.0028, 6000),
    "Lettuce": (G, 0.0035, 3000),
    "Mixed Leaf Salad": (G, 0.0060, 4000),
    "Chestnut Mushroom": (G, 0.0040, 5000),
    "Garlic": (G, 0.0080, 800),
    "Carrot": (G, 0.0011, 6000),
    "Celery": (G, 0.0018, 3000),
    # --- Dry goods & store --------------------------------------------------
    "Arborio Rice": (G, 0.0022, 8000),
    "Plain Flour": (G, 0.0009, 10000),
    "Caster Sugar": (G, 0.0010, 8000),
    "Dark Chocolate": (G, 0.0090, 3000),
    "Digestive Biscuit": (G, 0.0040, 2000),
    "Ciabatta Loaf": (UNIT, 0.90, 60),
    "Brioche Bun": (UNIT, 0.35, 200),
    "Vegetable Stock": (ML, 0.0006, 30000),
    "Olive Oil": (ML, 0.0050, 10000),
    "Mayonnaise": (G, 0.0040, 3000),
    # --- Cellar & bar -------------------------------------------------------
    "Lager Keg": (ML, 0.0022, 100000),
    "House Red Wine": (ML, 0.0048, 30000),
    "Cola 330ml Can": (UNIT, 0.42, 240),
    "Sparkling Water 330ml Bottle": (UNIT, 0.30, 240),
    "Orange Juice (carton)": (ML, 0.0015, 20000),
    "Coffee Beans": (G, 0.0220, 5000),
}

# Menu dish name -> [(ingredient name, qty in that ingredient's own UoM), ...]
RECIPES = {
    "Craft Lager Pint": [("Lager Keg", 568)],
    "House Red 250ml": [("House Red Wine", 250)],
    "Cappuccino": [("Coffee Beans", 18), ("Whole Milk", 150)],
    "Americano": [("Coffee Beans", 18)],
    "Orange Juice": [("Orange Juice (carton)", 250)],
    "Sparkling Water 330ml": [("Sparkling Water 330ml Bottle", 1)],
    "Cola 330ml": [("Cola 330ml Can", 1)],
    "Baked Cheesecake": [
        ("Cream Cheese", 120),
        ("Digestive Biscuit", 40),
        ("Butter", 20),
        ("Caster Sugar", 30),
        ("Double Cream", 40),
    ],
    "Chocolate Brownie": [
        ("Dark Chocolate", 60),
        ("Butter", 40),
        ("Caster Sugar", 50),
        ("Plain Flour", 30),
        ("Egg", 1),
    ],
    "House Salad": [
        ("Mixed Leaf Salad", 60),
        ("Tomato", 50),
        ("White Onion", 20),
        ("Olive Oil", 10),
    ],
    "Skin-on Fries": [("Potato", 250), ("Olive Oil", 10)],
    "Vegetable Risotto": [
        ("Arborio Rice", 90),
        ("Chestnut Mushroom", 80),
        ("White Onion", 40),
        ("Parmesan", 25),
        ("Butter", 20),
        ("Vegetable Stock", 400),
    ],
    "Grilled Chicken": [
        ("Chicken Breast (raw)", 220),
        ("Potato", 200),
        ("Mixed Leaf Salad", 40),
        ("Olive Oil", 15),
    ],
    "Beef Burger": [
        ("Beef Burger Patty 6oz", 1),
        ("Brioche Bun", 1),
        ("Cheddar Slice", 1),
        ("Streaky Bacon", 30),
        ("Lettuce", 20),
        ("Tomato", 25),
        ("Mayonnaise", 15),
        ("Potato", 150),
    ],
    "Ribeye Steak": [
        ("Ribeye Beef (raw)", 250),
        ("Potato", 200),
        ("Butter", 25),
        ("Garlic", 5),
        ("Chestnut Mushroom", 60),
    ],
    "Halloumi Fries": [
        ("Halloumi Cheese", 180),
        ("Plain Flour", 20),
        ("Olive Oil", 20),
    ],
    "Soup of the Day": [
        ("Carrot", 100),
        ("White Onion", 60),
        ("Celery", 60),
        ("Vegetable Stock", 350),
        ("Double Cream", 30),
        ("Ciabatta Loaf", 0.25),
    ],
    "Garlic Bread": [
        ("Ciabatta Loaf", 0.5),
        ("Butter", 30),
        ("Garlic", 10),
        ("Parmesan", 10),
    ],
}
