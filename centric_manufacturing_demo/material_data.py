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
INDUSTRIAL_CATEG = "Packaging Industrial"

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
    # Industrial packaging - pallet wrap, shrink hoods, box liners - is a
    # finished good sold to a different buyer than the bag range: a warehouse
    # or a production manager rather than a retailer. It gets its own heading
    # so the two can be reported apart while still adding up under Packaging.
    INDUSTRIAL_CATEG: FINISHED_CATEG,
}

# Parents first, so a category is always created after the one it hangs off.
CATEG_ORDER = (
    ROOT_CATEG,
    RAW_CATEG,
    WIP_CATEG,
    FINISHED_CATEG,
    FINISHED_BAG_CATEG,
    INDUSTRIAL_CATEG,
)

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
    # P3.7: cling. Stretch wrap has to hold a pallet together, and without a
    # tackifier the film simply unwinds off itself.
    # Opening count deliberately above the reordering rule this material's
    # 80 kg/month and 25 day lead time produce (reorder at 200, top up to 300),
    # so a fresh install does not greet the buyer with a draft purchase order.
    "Polyisobutylene Tackifier": (KG, 4.80, 400),
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
    # -------------------------------------------------------------------- P3.7
    # The heavy-gauge and stretch grades. Everything above this point is
    # consumer film - bread bags, carriers, shrink wrap for retail. These two
    # grades exist to be converted into industrial packaging: the film that
    # holds a pallet together and the liner that goes inside a box, sold to a
    # warehouse manager rather than a brand owner.
    "Blown Film Reel 100um Clear (Jumbo)": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        # Heavy gauge takes HDPE for stiffness and carries regrind comfortably:
        # a box liner is not looked at, it is filled.
        "components": [
            ("LDPE Film Grade Resin", 74.0),
            ("LLDPE Octene Resin", 14.0),
            ("HDPE Blown Film Resin", 5.0),
            ("Slip / Antiblock Additive", 2.0),
            ("Regrind LDPE Pellet", 5.0),
            ('Paper Core 152mm (6")', 1.0),
        ],
        "operations": [("Extrude and wind jumbo reel", "TP-EXTRUDE", 145.0)],
        "byproducts": [(SCRAP_MATERIAL, 3.0, 1.0)],
    },
    "Blown Film Reel 23um Stretch (Jumbo)": {
        "uom": KG,
        "categ": WIP_CATEG,
        "qty": 100.0,
        "sale_ok": False,
        # LLDPE-dominant for the stretch, tackifier for the cling. No regrind:
        # a recovered pellet of unknown history puts gels in a 23 micron film,
        # and a gel in stretch wrap is where the pallet lets go.
        "components": [
            ("LLDPE Octene Resin", 88.0),
            ("LDPE Film Grade Resin", 6.0),
            ("Polyisobutylene Tackifier", 4.0),
            ("Slip / Antiblock Additive", 2.0),
            ('Paper Core 152mm (6")', 1.0),
        ],
        # Slow: the thinner the gauge, the slower the line runs for the same
        # output weight, and this is the thinnest thing the plant extrudes.
        "operations": [("Extrude and wind jumbo reel", "TP-EXTRUDE", 175.0)],
        "byproducts": [(SCRAP_MATERIAL, 4.0, 1.0)],
    },
    "Layflat Tubing 300mm - 100um": {
        "uom": KG,
        "categ": FINISHED_CATEG,
        # Sold by weight on the reel, like the printed film above, because the
        # customer cuts and seals it to their own length. The unit-counted
        # industrial items are in INDUSTRIAL_PACKAGING below.
        "qty": 100.0,
        "sale_ok": True,
        "components": [
            ("Blown Film Reel 100um Clear (Jumbo)", 100.0),
            ('Paper Core 76mm (3")', 5.0),
        ],
        "operations": [("Slit tubing to width", "TP-SLIT", 50.0)],
        "byproducts": [(SCRAP_MATERIAL, 2.5, 1.0)],
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
#
# Three optional keys let the same table describe the industrial range in
# INDUSTRIAL_PACKAGING below, which converts film into counted units in exactly
# the same way and would otherwise need a duplicate of the whole mechanism:
#
#   "run_qty": units one run of the BoM makes, default BAG_RUN_QTY. A run of
#       1,000 rolls of pallet wrap is three tonnes of film and nobody schedules
#       one, so the heavier items size their run down.
#   "workcenter": the work centre that converts it, default the bag line. A
#       roll of stretch wrap is slit, not sealed.
#   "operation": what that work centre is doing, for the work order.
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

# ----------------------------------------------------------------------- P3.7
# Industrial packaging: the counted end of the industrial range.
#
# Same shape as FINISHED_BAGS and seeded by the same code - film in by weight,
# units out, offcut to the granulator, price from pricing.py - because it is
# the same problem. What differs is who buys it and how it is made: pallet wrap
# comes off the slitter as a roll, a shrink hood and a box liner come off the
# bag line, and the run sizes are set by what the plant would actually schedule
# rather than by a round thousand.
#
# ``grams_per_bag`` here is grammes per finished unit, worked from the item's
# own geometry at 920 kg/m3 - a roll of 500mm x 300m at 23 micron really is
# about 3.2 kg of film - so the BoM quantities can be checked against the
# product rather than taken on trust.
INDUSTRIAL_PACKAGING = {
    "Pallet Stretch Wrap 500mm x 300m - 23um": {
        "film": "Blown Film Reel 23um Stretch (Jumbo)",
        "grams_per_bag": 3174.0,
        # Low: slitting a reel down to 500mm wastes edge, not area.
        "waste_pct": 2.5,
        "extras": [('Paper Core 76mm (3")', 200.0)],
        "run_qty": 200.0,
        "workcenter": "TP-SLIT",
        "operation": "Slit and rewind stretch rolls",
        "minutes": 240.0,
        "code": "TP-IND-STR-500",
        "certification": (
            "Machine and hand pallet wrap, LLDPE. 250% nominal stretch, "
            "cling one side. Not food contact approved. Recyclable, LDPE 04."
        ),
        "margin": 0.22,
    },
    "Shrink Hood 1200x1000x1800mm - 100um": {
        "film": "Blown Film Reel 100um Clear (Jumbo)",
        "grams_per_bag": 810.0,
        # High: a hood is cut and side-sealed from layflat, and the gussets and
        # the top seal both throw offcut.
        "waste_pct": 6.0,
        "extras": [("Export Carton 600x400x400", 10.0)],
        "run_qty": 500.0,
        "minutes": 180.0,
        "code": "TP-IND-HOOD-1200",
        "certification": (
            "Pallet shrink hood for a 1200x1000mm Euro pallet to 1800mm load "
            "height. Shrink temperature 180-200 degrees C. Not food contact "
            "approved. Recyclable, LDPE 04."
        ),
        "margin": 0.28,
    },
    "Gusseted Box Liner 600x400x800mm - 50um": {
        "film": "Blown Film Reel 50um Clear (Jumbo)",
        "grams_per_bag": 83.0,
        "waste_pct": 4.0,
        "extras": [("Export Carton 600x400x400", 4.0)],
        "minutes": 110.0,
        "code": "TP-IND-LIN-600",
        "certification": (
            "Gusseted liner for a 600x400x800mm case. Food contact compliant "
            "to Regulation (EC) 1935/2004 and (EU) 10/2011; declaration of "
            "compliance DoC/TP/2024/014 held on file. Recyclable, LDPE 04."
        ),
        "margin": 0.26,
    },
}

# Film margin, applied per kilogramme to the reel products that are sold as
# reel rather than converted into bags. Lower than any bag margin: a reel is a
# commodity sold on price, a printed bag is sold on the artwork and the lead
# time.
FILM_MARGIN = 0.18
