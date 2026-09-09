# -*- coding: utf-8 -*-
"""Reordering rules and stock costing policy for the bought-in material master.

P3.9 - costing method and valuation
-----------------------------------
The plant buys polymer on a moving market: the same grade lands at 1.36 and
then at 1.51 eight weeks later. Standard costing would bury that difference in
a price variance nobody looks at, so the packaging categories are put on FIFO,
which is also what makes the rolled-up cost of a reel mean something - the
extrusion order consumes the layers it actually received.

Valuation is deliberately left where the database has it. Switching a category
to automated ("real time") valuation without stock input, output and valuation
accounts set on it makes every subsequent stock move fail, and those accounts
come from the Malta chart of accounts that P2.2 has not loaded yet. The hook
therefore sets the costing method only, and logs what is still to be done.

P5.3 - reordering rules
-----------------------
A reorder point is only as good as the two numbers under it: how fast the
material goes out, and how long the vendor takes to replace it. Both are here.

``MONTHLY_USAGE`` is the run-rate in the product's own base unit - kilogrammes
for compound and ink, units for cores and cartons - at the production volume
the seeded BoMs and trading history describe. These are PLAUSIBLE DEMO FIGURES.
Replace them with the real consumption off the stock moves once the plant has
a few months of history in Odoo, which is the point at which a reorder point
stops being a guess.

The lead time is not repeated here: it is read off the primary vendor's price
list line, so correcting a vendor's lead time in Purchasing and re-running the
seed moves the reorder point with it.
"""

# Working days a month. Maltese plant, single shift five days a week.
WORKING_DAYS_PER_MONTH = 21.0

# Safety stock as a fraction of the lead time, floored at a few days. A resin
# 25 days out needs a deeper buffer in absolute terms than a carton 5 days out,
# because there is more time in which the forecast can be wrong.
SAFETY_FRACTION = 0.35
MIN_SAFETY_DAYS = 4.0

# How much cover an order brings in, over and above the reorder point. A month
# keeps the buyer placing roughly one order per material per month rather than
# a trickle of small ones, and is comfortably inside the shelf life of
# everything here.
COVER_DAYS = 30.0

# Material name -> consumption per month in the product's base unit.
MONTHLY_USAGE = {
    # Polymers. LDPE is the backbone of every grade the plant extrudes, the
    # other two are blended in.
    "LDPE Film Grade Resin": 12000.0,
    "LLDPE Octene Resin": 4500.0,
    "HDPE Blown Film Resin": 3000.0,
    # Colour and additives, at their loadings in the film BoMs.
    "White Masterbatch (TiO2)": 600.0,
    "Black Masterbatch": 450.0,
    "Blue Masterbatch": 150.0,
    "Slip / Antiblock Additive": 300.0,
    "Oxo-Biodegradable Additive": 120.0,
    # Only the stretch grade takes tackifier, at 4% of a grade the plant does
    # not run every week.
    "Polyisobutylene Tackifier": 80.0,
    # Ink. White carries the most because it is the base coat on every
    # reversed-out job.
    "Flexo Ink - Cyan": 60.0,
    "Flexo Ink - Magenta": 45.0,
    "Flexo Ink - Yellow": 45.0,
    "Flexo Ink - Black": 75.0,
    "Flexo Ink - White": 90.0,
    "Solvent-Based Ink Extender": 110.0,
    # Plates are cut per artwork, not consumed at a rate, but the plant keeps
    # blank sets in so a repeat job is not held up by a 7 day lead time.
    "Photopolymer Printing Plate Set": 3.0,
    # Converting consumables.
    'Paper Core 76mm (3")': 1400.0,
    'Paper Core 152mm (6")': 420.0,
    "Export Carton 600x400x400": 900.0,
}


def _round_up_to(value, multiple):
    """Round ``value`` up to the next whole ``multiple``."""
    if multiple <= 0:
        return round(value, 2)
    return multiple * -(-value // multiple)


def reorder_levels(monthly_usage, lead_days, min_order_qty):
    """Return ``(min_qty, max_qty)`` for one reordering rule.

    The reorder point is the stock the plant gets through while it waits for a
    replacement, plus a safety buffer proportional to that wait. The maximum
    adds a month of cover on top, then both are rounded up to whole minimum
    order quantities so the rule never proposes a purchase order the vendor
    would reject as below their minimum.

    That rounding is the only place the vendor's minimum is enforced. Odoo 19
    dropped the orderpoint's ``qty_multiple`` quantity in favour of
    ``replenishment_uom_id``, a unit of measure - and a vendor minimum of 750 kg
    is a quantity, not a unit the plant buys resin in, so there is no UoM to put
    there. Rounding both levels up here gives the same guarantee without one.
    """
    daily = monthly_usage / WORKING_DAYS_PER_MONTH
    safety_days = max(lead_days * SAFETY_FRACTION, MIN_SAFETY_DAYS)
    min_qty = daily * (lead_days + safety_days)
    max_qty = min_qty + daily * COVER_DAYS

    # The order the rule raises is (max - min), and that is what has to clear
    # the vendor's minimum - not the reorder point itself.
    if max_qty - min_qty < min_order_qty:
        max_qty = min_qty + min_order_qty

    return (
        round(_round_up_to(min_qty, min_order_qty), 2),
        round(_round_up_to(max_qty, min_order_qty), 2),
    )
