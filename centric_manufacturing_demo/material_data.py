# -*- coding: utf-8 -*-
"""Material master and bills of materials for the flexible packaging plant.

The figures here are PLAUSIBLE DEMO FIGURES for a blown-film and flexo print
operation - resin grades, masterbatch loadings, ink coverage and cycle times of
the right order of magnitude - not the customer's real formulations or
contracted prices. Replace them before go-live.

Units
-----
Film and compound are bought, made and costed in kilogrammes; cores, cartons
and plate sets are counted in units. ``standard_price`` is always per base unit
of the product's own UoM, so a purchase price list line at the same price
reconciles with the cost the BoMs roll up.
"""

KG = "uom.product_uom_kgm"
UNIT = "uom.product_uom_unit"

ROOT_CATEG = "Packaging"
RAW_CATEG = "Packaging Raw Materials"
WIP_CATEG = "Packaging Semi-Finished"
FINISHED_CATEG = "Packaging Finished Goods"
FINISHED_BAG_CATEG = "Packaging Finished Bags"

# The category tree, child -> parent. The three original categories were flat,
# which meant Inventory reported the plant as three unrelated headings with no
# subtotal; nesting them under one root gives valuation and the stock reports a
# single "Packaging" line that adds up, without moving any product between
# categories. Finished bags hang off finished goods rather than sitting beside
# it, because a bag is a finished good - it is just counted in units instead of
# weighed in kilogrammes.
CATEG_PARENT = {
    RAW_CATEG: ROOT_CATEG,
    WIP_CATEG: ROOT_CATEG,
    FINISHED_CATEG: ROOT_CATEG,
    FINISHED_BAG_CATEG: FINISHED_CATEG,
}

# Parents first, so a category is always created after the one it hangs off.
CATEG_ORDER = (ROOT_CATEG, RAW_CATEG, WIP_CATEG, FINISHED_CATEG, FINISHED_BAG_CATEG)

# name -> (uom xmlid, cost per base unit, opening stock quantity)
RAW_MATERIALS = {
    # Polymers
    "LDPE Film Grade Resin": (KG, 1.42, 24000),
    "LLDPE Octene Resin": (KG, 1.58, 9000),
    "HDPE Blown Film Resin": (KG, 1.36, 6000),
    # Colour and additives
    "White Masterbatch (TiO2)": (KG, 2.95, 1200),
    "Black Masterbatch": (KG, 2.40, 900),
    "Blue Masterbatch": (KG, 3.10, 400),
    "Slip / Antiblock Additive": (KG, 3.75, 600),
    "Oxo-Biodegradable Additive": (KG, 6.20, 250),
    # Inks and press consumables
    "Flexo Ink - Cyan": (KG, 8.40, 180),
    "Flexo Ink - Magenta": (KG, 8.90, 140),
    "Flexo Ink - Yellow": (KG, 8.10, 140),
    "Flexo Ink - Black": (KG, 7.60, 220),
    "Flexo Ink - White": (KG, 9.50, 260),
    "Solvent-Based Ink Extender": (KG, 5.40, 300),
    "Photopolymer Printing Plate Set": (UNIT, 240.00, 12),
    # Converting consumables
    'Paper Core 76mm (3")': (UNIT, 0.85, 4000),
    'Paper Core 152mm (6")': (UNIT, 1.95, 1200),
    "Export Carton 600x400x400": (UNIT, 1.15, 2500),
}

# Recovered film scrap. Bought from nobody - it comes off the extrusion and
# slitting lines - so it is deliberately absent from SOURCING, but it is still
# a stocked, costed material because the regrind BoM consumes it.
SCRAP_MATERIAL = "Production Film Scrap (LDPE)"
SCRAP_COST = 0.35
SCRAP_OPENING_QTY = 3200

# Manufactured products, in dependency order: a BoM may only consume materials
# or products defined above it, which is what lets the cost roll up in one
# pass.
#
# Each entry is:
#   name: {
#       "uom": uom xmlid,
#       "categ": product category name,
#       "qty": how many base units one run of the BoM produces,
#       "sale_ok": whether it is sold to customers,
#       "components": [(component name, quantity per run), ...],
#       "operations": [(operation name, work centre code, minutes), ...],
#       "byproducts": [(product name, quantity per run, cost share %), ...],
#   }
#
# ``byproducts`` is what closes the regrind loop (P4.6). Every line that
# handles film throws some off - edge trim on the extruder, the set-up waste a
# press makes reaching colour, the offcut a bag line leaves. Declaring it as a
# by-product means the manufacturing order books it back into stock as
# recoverable scrap, where the regrind BoM picks it up and granulates it into
# pellet that the extruder consumes again. Without it the scrap the granulator
# eats has to be counted in by hand and the loop only exists on paper.
#
# ``cost_share`` is the percentage of the run's cost that follows the scrap out
# rather than staying with the good film. It is deliberately well under the
# scrap's proportion by weight: recovered trim is worth a fraction of prime
# film, which is exactly why the plant regrinds it instead of selling it.
MANUFACTURED = {
    "Regrind LDPE Pellet": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        # Yield loss: 105 kg of baled scrap gives 100 kg of usable pellet.
        "components": [(SCRAP_MATERIAL, 105.0)],
        "operations": [("Granulate and pelletise", "TP-REGRIND", 60.0)],
    },
    "Blown Film Reel 50um Clear (Jumbo)": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        "components": [
            ("LDPE Film Grade Resin", 88.0),
            ("LLDPE Octene Resin", 8.0),
            ("Slip / Antiblock Additive", 2.0),
            ("Regrind LDPE Pellet", 2.0),
            ('Paper Core 152mm (6")', 1.0),
        ],
        "operations": [("Extrude and wind jumbo reel", "TP-EXTRUDE", 150.0)],
        # Edge trim off the winder, plus the purge at start of run.
        "byproducts": [(SCRAP_MATERIAL, 3.0, 1.0)],
    },
    "Blown Film Reel 50um White (Jumbo)": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        "components": [
            ("LDPE Film Grade Resin", 86.0),
            ("LLDPE Octene Resin", 8.0),
            ("White Masterbatch (TiO2)", 4.0),
            ("Slip / Antiblock Additive", 2.0),
            ('Paper Core 152mm (6")', 1.0),
        ],
        "operations": [("Extrude and wind jumbo reel", "TP-EXTRUDE", 150.0)],
        # Pigmented trim regrinds back into pigmented film only, but the plant
        # bales it with the rest and lets the black and refuse grades take it.
        "byproducts": [(SCRAP_MATERIAL, 3.0, 1.0)],
    },
    "Printed Bread Bag Film 40um - 3 Colour": {
        "uom": KG,
        "categ": FINISHED_CATEG,
        "qty": 100.0,
        "sale_ok": True,
        "components": [
            ("Blown Film Reel 50um Clear (Jumbo)", 100.0),
            ("Flexo Ink - Cyan", 0.9),
            ("Flexo Ink - Magenta", 0.6),
            ("Flexo Ink - Black", 0.5),
            ("Solvent-Based Ink Extender", 0.4),
            ('Paper Core 76mm (3")', 4.0),
        ],
        "operations": [
            ("Flexo print 3 colours", "TP-FLEXO6", 90.0),
            ("Slit and rewind to order", "TP-SLIT", 60.0),
        ],
        # Set-up waste reaching colour on a three colour job, plus slitter
        # offcut. Printed waste carries ink, so it regrinds dirtier and takes a
        # smaller share of the cost with it.
        "byproducts": [(SCRAP_MATERIAL, 4.0, 1.0)],
    },
    "Printed Shrink Wrap 50um - 2 Colour": {
        "uom": KG,
        "categ": FINISHED_CATEG,
        "qty": 100.0,
        "sale_ok": True,
        "components": [
            ("Blown Film Reel 50um White (Jumbo)", 100.0),
            ("Flexo Ink - White", 1.2),
            ("Flexo Ink - Black", 0.4),
            ("Solvent-Based Ink Extender", 0.5),
            ('Paper Core 76mm (3")', 4.0),
            ("Export Carton 600x400x400", 2.0),
        ],
        "operations": [
            ("Flexo print 2 colours", "TP-FLEXO6", 75.0),
            ("Slit and rewind to order", "TP-SLIT", 55.0),
        ],
        "byproducts": [(SCRAP_MATERIAL, 3.5, 1.0)],
    },
    # ---------------------------------------------------------------- P3/P3.2
    # From here down the chain leaves the reel and becomes a converted bag, and
    # with it the unit of measure changes from kilogrammes to units. See
    # FINISHED_BAGS below for how the two are tied together.
    "Blown Film Reel 40um Black (Jumbo)": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        # The grade that carries the most regrind: a refuse sack is opaque and
        # unprinted, so recovered trim costs it nothing in appearance.
        "components": [
            ("LDPE Film Grade Resin", 66.0),
            ("HDPE Blown Film Resin", 12.0),
            ("Black Masterbatch", 3.0),
            ("Slip / Antiblock Additive", 1.0),
            ("Regrind LDPE Pellet", 20.0),
            ('Paper Core 152mm (6")', 1.0),
        ],
        "operations": [("Extrude and wind jumbo reel", "TP-EXTRUDE", 130.0)],
        "byproducts": [(SCRAP_MATERIAL, 3.0, 1.0)],
    },
    "Blown Film Reel 45um Biodegradable (Jumbo)": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        # No regrind in this grade. The certificate covers a stated
        # formulation, and film built from recovered trim of unknown history
        # cannot be declared against it.
        "components": [
            ("LDPE Film Grade Resin", 82.0),
            ("LLDPE Octene Resin", 12.0),
            ("Oxo-Biodegradable Additive", 4.0),
            ("Slip / Antiblock Additive", 1.5),
            ('Paper Core 152mm (6")', 1.0),
        ],
        "operations": [("Extrude and wind jumbo reel", "TP-EXTRUDE", 165.0)],
        # Trim off this grade still goes to the granulator, but it may only be
        # fed back into the uncertified black and carrier grades.
        "byproducts": [(SCRAP_MATERIAL, 3.5, 1.0)],
    },
    "Printed Carrier Bag Film 30um - 2 Colour": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        "components": [
            ("Blown Film Reel 50um Clear (Jumbo)", 100.0),
            ("Flexo Ink - Cyan", 0.7),
            ("Flexo Ink - Black", 0.5),
            ("Solvent-Based Ink Extender", 0.4),
            ('Paper Core 76mm (3")', 3.0),
        ],
        "operations": [
            ("Flexo print 2 colours", "TP-FLEXO6", 80.0),
            ("Slit to bag web width", "TP-SLIT", 45.0),
        ],
        "byproducts": [(SCRAP_MATERIAL, 3.5, 1.0)],
    },
    "Printed Biodegradable Film 45um - 2 Colour": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        "components": [
            ("Blown Film Reel 45um Biodegradable (Jumbo)", 100.0),
            ("Flexo Ink - Cyan", 0.7),
            ("Flexo Ink - Black", 0.6),
            ("Solvent-Based Ink Extender", 0.4),
            ('Paper Core 76mm (3")', 3.0),
        ],
        "operations": [
            ("Flexo print 2 colours", "TP-FLEXO6", 70.0),
            ("Slit to bag web width", "TP-SLIT", 45.0),
        ],
        "byproducts": [(SCRAP_MATERIAL, 3.0, 1.0)],
    },
}

# ------------------------------------------------------------------ P3 / P3.2
# The finished bag range, and the kilogramme/unit bridge.
#
# Everything above this line is weighed. Everything below it is counted: a
# customer orders 20,000 carrier bags, not 240 kg of carrier bag film. The two
# have to reconcile, because the plant buys, extrudes, prints and costs in
# kilogrammes and invoices in thousands of bags.
#
# Odoo will not convert between kilogrammes and units - they are different UoM
# categories, and rightly so, since the rate is a property of the bag and not
# of the units. The conversion therefore lives in two places, both derived from
# the same ``grams_per_bag`` figure so they cannot drift apart:
#
#   * the BoM, which produces ``run_bags`` bags and consumes
#     ``grams_per_bag * run_bags / 1000`` kilogrammes of film. That is what
#     makes a works order for 20,000 bags reserve the right weight of reel;
#   * the product's ``weight``, in kilogrammes per bag, which is what lets
#     Inventory price a pallet's carriage and what the sales team divides into
#     a reel weight to answer "how many bags do I get out of this?".
#
# Runs are sized at BAG_RUN_QTY bags, so a run consumes exactly
# ``grams_per_bag`` kilogrammes of film - the arithmetic below is deliberately
# arranged to make that true, because a demo whose BoM quantities are round
# numbers is one somebody can check by eye.
BAG_RUN_QTY = 1000.0

# name -> {
#   "film": the printed or plain film it converts,
#   "grams_per_bag": finished bag weight in grammes, gauge times layflat area,
#   "waste_pct": conversion offcut, returned to the granulator as scrap,
#   "extras": [(component, qty per run)] - cartons, handles, tape,
#   "minutes": bag line time for one run,
#   "code": internal reference,
#   "certification": what the customer is told about the material, printed on
#       the quotation and the delivery note. A claim on a bag is a regulated
#       statement, so it names the standard and the certificate it rests on.
#   "margin": gross margin the range is quoted at, see pricing.py.
# }
FINISHED_BAGS = {
    "Carrier Bag 380x450mm - 2 Colour Printed": {
        "film": "Printed Carrier Bag Film 30um - 2 Colour",
        "grams_per_bag": 12.0,
        "waste_pct": 4.0,
        "extras": [("Export Carton 600x400x400", 1.0)],
        "minutes": 45.0,
        "code": "TP-BAG-CAR-380",
        "certification": (
            "Reusable carrier bag, LDPE. Food contact compliant to "
            "Regulation (EC) 1935/2004 and (EU) 10/2011; declaration of "
            "compliance DoC/TP/2024/011 held on file. Recyclable, LDPE 04."
        ),
        "margin": 0.32,
    },
    "Refuse Sack 750x950mm Black Heavy Duty": {
        "film": "Blown Film Reel 40um Black (Jumbo)",
        "grams_per_bag": 38.0,
        "waste_pct": 3.0,
        "extras": [("Export Carton 600x400x400", 2.0)],
        "minutes": 60.0,
        "code": "TP-BAG-REF-750",
        "certification": (
            "Heavy duty refuse sack. Manufactured with a minimum 20% "
            "post-industrial recycled content, recovered on site. Not food "
            "contact approved. Recyclable, LDPE 04."
        ),
        "margin": 0.24,
    },
    "Biodegradable Carrier Bag 300x400mm": {
        "film": "Printed Biodegradable Film 45um - 2 Colour",
        "grams_per_bag": 9.0,
        "waste_pct": 4.5,
        "extras": [("Export Carton 600x400x400", 1.0)],
        "minutes": 50.0,
        "code": "TP-BAG-BIO-300",
        "certification": (
            "Compostable carrier bag. Certified to EN 13432:2000 / "
            "ISO 17088 for industrial composting, certificate "
            "TUV-OK-C-2024-08817 (OK compost INDUSTRIAL). Not certified for "
            "home composting. Do not place in the LDPE recycling stream."
        ),
        "margin": 0.38,
    },
}

# Film margin, applied per kilogramme to the reel products that are sold as
# reel rather than converted into bags. Lower than any bag margin: a reel is a
# commodity sold on price, a printed bag is sold on the artwork and the lead
# time.
FILM_MARGIN = 0.18
