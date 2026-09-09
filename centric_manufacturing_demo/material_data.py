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

RAW_CATEG = "Packaging Raw Materials"
WIP_CATEG = "Packaging Semi-Finished"
FINISHED_CATEG = "Packaging Finished Goods"

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
#   }
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
    },
}
