# Centric Restaurant Demo Data

Closes the data-shaped gaps in the restaurant rollout plan: tasks **7.3**
(recipes / BoMs), **7.4** (stock depletion on sale), **9.2** (food-cost and
margin figures) and **10.3** (opening stock).

## What it does

Installing the module runs a post-init hook that:

1. creates a **`Restaurant Ingredients`** product category and **37 storable
   ingredient products** (butchery, dairy, veg, dry goods, cellar), each with a
   purchase cost per base unit (per g, per ml or per unit);
2. creates a **kit BoM (`type = phantom`)** for each of the 18 menu dishes and
   flips the dish to storable;
3. writes the **rolled-up recipe cost** onto each dish's `standard_price`;
4. applies an **opening stock count** for every ingredient.

## Why kit BoMs rather than manufacturing orders

Standard Odoo POS does not raise a manufacturing order when a dish is sold, so
a `normal` BoM would never consume anything. A `phantom` BoM is exploded by the
stock engine when the POS picking's moves are confirmed, so selling a Ribeye
Steak generates component moves for beef, potato, butter, garlic and mushroom
and depletes them from the storeroom. No custom backflush code required.

## The numbers are made up

Portion sizes and supplier costs are plausible mid-market UK figures chosen to
make the reporting work end to end. They are **not** the customer's real
recipes. Edit `recipe_data.py` and re-run, or adjust the BoMs in the UI, before
this is used for anything financial.

## Re-running

The hook is idempotent — ingredients are matched by name, BoMs are rewritten
rather than duplicated, and opening stock is only applied to ingredients
currently holding zero. Upgrading the module will not reset a live storeroom.
