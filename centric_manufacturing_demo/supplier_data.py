# -*- coding: utf-8 -*-
"""Vendors and purchase price lists for the raw material master.

The vendors below already exist in the live database - they were created
during setup - so the hook matches them by name and only fills in the ones a
rebuilt database is missing. Contact details are demo placeholders on the
``.example`` domain and should be corrected against the real trading records
rather than trusted.

Each material gets a primary vendor priced at its standard cost, and most get
a backup a few percent dearer, so the purchase price list has something to
choose between when the primary is out of stock or off lead time.
"""

from .material_data import KG, UNIT

# Vendor name -> partner values plus the default lead time in days. Resin comes
# in by sea or long-haul road, hence the long lead times; local converting
# consumables arrive in days.
SUPPLIERS = {
    "EuroMasterbatch NV": {
        "street": "Havenlaan 212, Industriepark Noord",
        "city": "Antwerp",
        "zip": "2030",
        "phone": "+32 3 205 7740",
        "email": "sales@euromasterbatch.example",
        "delay": 21,
    },
    "OxoBio Additives Ltd": {
        "street": "Unit 4, Riverside Technology Park",
        "city": "Manchester",
        "zip": "M50 3XP",
        "phone": "+44 161 883 0410",
        "email": "orders@oxobioadditives.example",
        "delay": 18,
    },
    "InkTech Italia S.r.l.": {
        "street": "Via dell'Industria 47",
        "city": "Bergamo",
        "zip": "24127",
        "phone": "+39 035 419 2280",
        "email": "ordini@inktechitalia.example",
        "delay": 14,
    },
    "Mediterranean Resin Traders Ltd": {
        "street": "Hal Far Industrial Estate, HF32",
        "city": "Birzebbuga",
        "zip": "BBG 3000",
        "phone": "+356 2165 4420",
        "email": "trading@medresin.example",
        "delay": 10,
    },
    "NordPolymer B.V.": {
        "street": "Petroleumhavenweg 88",
        "city": "Rotterdam",
        "zip": "3197 KD",
        "phone": "+31 10 429 6605",
        "email": "sales@nordpolymer.example",
        "delay": 25,
    },
    "Adriatic Polymers GmbH": {
        "street": "Hafenstrasse 19",
        "city": "Trieste",
        "zip": "34123",
        "phone": "+39 040 307 1150",
        "email": "vertrieb@adriaticpolymers.example",
        "delay": 20,
    },
    "Malta Core & Carton Ltd": {
        "street": "Mriehel Bypass, Central Business District",
        "city": "Birkirkara",
        "zip": "CBD 1050",
        "phone": "+356 2144 8890",
        "email": "sales@maltacorecarton.example",
        "delay": 5,
    },
    "Kordin Engineering Services Ltd": {
        "street": "Kordin Industrial Estate, KIE",
        "city": "Paola",
        "zip": "PLA 3000",
        "phone": "+356 2180 3312",
        "email": "workshop@kordinengineering.example",
        "delay": 7,
    },
}

# Raw material name -> (primary vendor, backup vendor or None)
SOURCING = {
    "LDPE Film Grade Resin": ("Mediterranean Resin Traders Ltd", "NordPolymer B.V."),
    "LLDPE Octene Resin": ("NordPolymer B.V.", "Adriatic Polymers GmbH"),
    "HDPE Blown Film Resin": ("Adriatic Polymers GmbH", "Mediterranean Resin Traders Ltd"),
    "White Masterbatch (TiO2)": ("EuroMasterbatch NV", None),
    "Black Masterbatch": ("EuroMasterbatch NV", None),
    "Blue Masterbatch": ("EuroMasterbatch NV", None),
    "Green Masterbatch": ("EuroMasterbatch NV", None),
    "Slip / Antiblock Additive": ("OxoBio Additives Ltd", "EuroMasterbatch NV"),
    "Oxo-Biodegradable Additive": ("OxoBio Additives Ltd", None),
    "Polyisobutylene Tackifier": ("NordPolymer B.V.", "Adriatic Polymers GmbH"),
    "Flexo Ink - Cyan": ("InkTech Italia S.r.l.", None),
    "Flexo Ink - Magenta": ("InkTech Italia S.r.l.", None),
    "Flexo Ink - Yellow": ("InkTech Italia S.r.l.", None),
    "Flexo Ink - Black": ("InkTech Italia S.r.l.", None),
    "Flexo Ink - White": ("InkTech Italia S.r.l.", None),
    "Solvent-Based Ink Extender": ("InkTech Italia S.r.l.", None),
    "Photopolymer Printing Plate Set": ("Kordin Engineering Services Ltd", None),
    # The tape converter is a local extruder, not a masterbatch house: it is
    # the same kind of business as the plant itself, two streets away, which is
    # why the lead time is days rather than weeks.
    "LDPE Drawstring Tape 8mm": ("Malta Core & Carton Ltd", None),
    'Paper Core 76mm (3")': ("Malta Core & Carton Ltd", None),
    'Paper Core 152mm (6")': ("Malta Core & Carton Ltd", None),
    "Export Carton 600x400x400": ("Malta Core & Carton Ltd", None),
}

# A backup vendor is priced 6% over the primary - roughly the premium the plant
# pays for buying off contract.
BACKUP_PRICE_UPLIFT = 1.06

# Minimum order quantity, by unit of measure. Polymer moves in full pallets;
# counted goods move in box quantities.
MIN_QTY_BY_UOM = {KG: 1000.0, UNIT: 100.0}

# Materials that do not follow the default for their UoM: ink and additive are
# bought by the drum rather than the pallet, and a plate set is made to order
# one artwork at a time.
MIN_QTY_OVERRIDE = {
    "White Masterbatch (TiO2)": 250.0,
    "Black Masterbatch": 250.0,
    "Blue Masterbatch": 100.0,
    "Green Masterbatch": 250.0,
    "Slip / Antiblock Additive": 100.0,
    "Oxo-Biodegradable Additive": 50.0,
    "Polyisobutylene Tackifier": 100.0,
    "Flexo Ink - Cyan": 25.0,
    "Flexo Ink - Magenta": 25.0,
    "Flexo Ink - Yellow": 25.0,
    "Flexo Ink - Black": 25.0,
    "Flexo Ink - White": 25.0,
    "Solvent-Based Ink Extender": 25.0,
    "Photopolymer Printing Plate Set": 1.0,
    "LDPE Drawstring Tape 8mm": 50.0,
    'Paper Core 152mm (6")': 50.0,
    "Export Carton 600x400x400": 250.0,
}
