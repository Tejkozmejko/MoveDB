# -*- coding: utf-8 -*-
"""Customers and the trading history that turns the master data into a system.

``material_data`` and ``supplier_data`` describe what the plant *is*: products,
recipes, machines, vendors. This file describes what the plant has *done* -
purchase orders that were received and paid, manufacturing orders that ran, and
sales that were delivered and invoiced - so a rebuilt database opens on
populated Purchase, Manufacturing, Inventory, Sales and Accounting apps rather
than on eight empty list views.

Everything here is PLAUSIBLE DEMO TRADING, not the customer's real order book.

Sequencing
----------
The three tables below are seeded in order - purchases, then production, then
sales - and the quantities are chosen so the chain actually balances against
the opening stock in ``material_data``:

* receipts and the opening count cover every component the manufacturing
  orders consume;
* the ``done`` manufacturing orders produce more regrind than the extrusion
  orders consume, more jumbo reel than the print orders consume, and more
  printed film than the delivered sales orders ship.

Change a quantity in one table and the ones downstream of it may no longer
have the stock to run. The seeder logs a warning and carries on rather than
failing the install, but the resulting database will have unreserved orders.

Ages
----
Every document is dated relative to the install date, in days before or after
it, so the demo is never stale: ``-110`` is a hundred and ten days ago,
``+3`` is three days out.
"""

# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------
# Who the plant sells printed film to: bakeries, produce packers and grocery
# retail, which is the usual mix for a flexible packaging converter.
CUSTOMERS = {
    "Mediterranean Bakeries Ltd": {
        "street": "Bakery Lane, Industrial Estate",
        "city": "Marsa",
        "zip": "MRS 3000",
        "phone": "+356 2122 5510",
        "email": "purchasing@medbakeries.example",
        # Payment terms are matched by name against whatever the chart of
        # accounts installed; a term that is not present is simply skipped.
        "payment_term": "30 Days",
    },
    "Valletta Foods Distribution Ltd": {
        "street": "Xatt Lascaris 14",
        "city": "Valletta",
        "zip": "VLT 1920",
        "phone": "+356 2124 8830",
        "email": "orders@vallettafoods.example",
        "payment_term": "30 Days",
    },
    "Gozo Farm Produce Co-operative": {
        "street": "Triq ir-Rabat",
        "city": "Victoria",
        "zip": "VCT 2500",
        "phone": "+356 2156 1140",
        "email": "admin@gozofarmproduce.example",
        "payment_term": "Immediate Payment",
    },
    "Sicilia Fresh Produce S.p.A.": {
        "street": "Zona Industriale, Contrada Bocchetta",
        "city": "Catania",
        "zip": "95121",
        "phone": "+39 095 771 4420",
        "email": "acquisti@siciliafresh.example",
        "payment_term": "45 Days",
    },
    "IslandMart Retail Group Ltd": {
        "street": "Mriehel Bypass, Block C",
        "city": "Birkirkara",
        "zip": "CBD 2010",
        "phone": "+356 2148 9900",
        "email": "supplychain@islandmart.example",
        "payment_term": "60 Days",
    },
}

# Sale price as a markup on the rolled-up standard cost the BoMs compute, so
# the price list stays sane if a cycle time or a resin price is corrected.
# Printed film runs at a thinner margin than shrink wrap, which is the usual
# shape: bread bag film is a tendered commodity, shrink wrap is not.
SALE_MARKUP = {
    "Printed Bread Bag Film 40um - 3 Colour": 1.28,
    "Printed Shrink Wrap 50um - 2 Colour": 1.36,
}

# --------------------------------------------------------------------------
# Purchases
# --------------------------------------------------------------------------
# ``status`` is cumulative - each one implies the ones before it:
#   draft      a request for quotation nobody has confirmed
#   confirmed  a purchase order placed, goods not yet arrived
#   received   the receipt has been validated, stock is in
#   billed     the vendor bill has been created and posted
#   paid       the bill has been paid off the bank journal
#
# ``ref`` is what makes the seed idempotent: a purchase order already carrying
# it is left completely alone, so re-installing or upgrading never duplicates
# a document or double-counts stock.
PURCHASE_ORDERS = [
    {
        "ref": "TP-DEMO-PO-01",
        "vendor": "Mediterranean Resin Traders Ltd",
        "days": -110,
        "status": "paid",
        "lines": [("LDPE Film Grade Resin", 12000.0)],
    },
    {
        "ref": "TP-DEMO-PO-02",
        "vendor": "NordPolymer B.V.",
        "days": -95,
        "status": "paid",
        "lines": [("LLDPE Octene Resin", 6000.0)],
    },
    {
        "ref": "TP-DEMO-PO-03",
        "vendor": "Kordin Engineering Services Ltd",
        "days": -75,
        "status": "paid",
        # Two artworks re-plated for the season's bread bag and shrink jobs.
        "lines": [("Photopolymer Printing Plate Set", 2.0)],
    },
    {
        "ref": "TP-DEMO-PO-04",
        "vendor": "EuroMasterbatch NV",
        "days": -60,
        "status": "billed",
        "lines": [
            ("White Masterbatch (TiO2)", 500.0),
            ("Black Masterbatch", 250.0),
        ],
    },
    {
        "ref": "TP-DEMO-PO-05",
        "vendor": "InkTech Italia S.r.l.",
        "days": -45,
        "status": "billed",
        "lines": [
            ("Flexo Ink - Cyan", 50.0),
            ("Flexo Ink - Magenta", 50.0),
            ("Flexo Ink - Black", 75.0),
            ("Flexo Ink - White", 75.0),
            ("Solvent-Based Ink Extender", 50.0),
        ],
    },
    {
        # Goods in, invoice not yet arrived: this is what puts a figure in
        # "Bills to receive" / goods received not invoiced.
        "ref": "TP-DEMO-PO-06",
        "vendor": "Malta Core & Carton Ltd",
        "days": -20,
        "status": "received",
        "lines": [
            ('Paper Core 76mm (3")', 2000.0),
            ('Paper Core 152mm (6")', 500.0),
            ("Export Carton 600x400x400", 1000.0),
        ],
    },
    {
        # On order, not yet arrived: gives the forecast something to show.
        "ref": "TP-DEMO-PO-07",
        "vendor": "Mediterranean Resin Traders Ltd",
        "days": -5,
        "status": "confirmed",
        "lines": [("LDPE Film Grade Resin", 8000.0)],
    },
    {
        "ref": "TP-DEMO-PO-08",
        "vendor": "Adriatic Polymers GmbH",
        "days": -2,
        "status": "draft",
        "lines": [("HDPE Blown Film Resin", 4000.0)],
    },
]

# --------------------------------------------------------------------------
# Production
# --------------------------------------------------------------------------
# ``status`` again cumulative:
#   draft      planned, not released to the floor
#   confirmed  released and reserving components
#   progress   the first work order has been started by an operator
#   done       produced, components consumed, work centre time booked
#
# Ordered so that every ``done`` order's components exist by the time it runs:
# regrind before the extrusion that consumes it, extrusion before the print.
MANUFACTURING_ORDERS = [
    {
        "ref": "TP-DEMO-MO-01",
        "product": "Regrind LDPE Pellet",
        "qty": 500.0,
        "days": -85,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-02",
        "product": "Blown Film Reel 50um Clear (Jumbo)",
        "qty": 4000.0,
        "days": -80,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-03",
        "product": "Blown Film Reel 50um White (Jumbo)",
        "qty": 3000.0,
        "days": -70,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-04",
        "product": "Printed Bread Bag Film 40um - 3 Colour",
        "qty": 2500.0,
        "days": -60,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-05",
        "product": "Printed Shrink Wrap 50um - 2 Colour",
        "qty": 2000.0,
        "days": -50,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-06",
        "product": "Printed Bread Bag Film 40um - 3 Colour",
        "qty": 1200.0,
        "days": -25,
        "status": "done",
    },
    {
        # On the extrusion line right now, so the shopfloor view and the work
        # centre load report both have something live in them.
        "ref": "TP-DEMO-MO-07",
        "product": "Blown Film Reel 50um Clear (Jumbo)",
        "qty": 2000.0,
        "days": -2,
        "status": "progress",
    },
    {
        "ref": "TP-DEMO-MO-08",
        "product": "Printed Shrink Wrap 50um - 2 Colour",
        "qty": 800.0,
        "days": 3,
        "status": "confirmed",
    },
    {
        "ref": "TP-DEMO-MO-09",
        "product": "Regrind LDPE Pellet",
        "qty": 300.0,
        "days": 7,
        "status": "draft",
    },
]

# --------------------------------------------------------------------------
# Sales
# --------------------------------------------------------------------------
# ``status`` cumulative:
#   draft      a quotation being priced
#   sent       a quotation sent to the customer
#   confirmed  a sales order, nothing shipped
#   delivered  the delivery has been validated
#   invoiced   the customer invoice has been created and posted
#   paid       the invoice has been paid into the bank journal
#
# The delivered quantities stay inside what the ``done`` manufacturing orders
# above produced - 3700 kg of bread bag film and 2000 kg of shrink wrap - so
# nothing ships out of negative stock.
SALES_ORDERS = [
    {
        "ref": "TP-DEMO-SO-01",
        "customer": "Mediterranean Bakeries Ltd",
        "days": -55,
        "status": "paid",
        "lines": [("Printed Bread Bag Film 40um - 3 Colour", 1200.0)],
    },
    {
        "ref": "TP-DEMO-SO-02",
        "customer": "Valletta Foods Distribution Ltd",
        "days": -48,
        "status": "paid",
        "lines": [("Printed Shrink Wrap 50um - 2 Colour", 800.0)],
    },
    {
        # Invoiced and outstanding: puts a real figure on the aged receivable.
        "ref": "TP-DEMO-SO-03",
        "customer": "IslandMart Retail Group Ltd",
        "days": -30,
        "status": "invoiced",
        "lines": [("Printed Bread Bag Film 40um - 3 Colour", 900.0)],
    },
    {
        "ref": "TP-DEMO-SO-04",
        "customer": "Sicilia Fresh Produce S.p.A.",
        "days": -22,
        "status": "invoiced",
        "lines": [("Printed Shrink Wrap 50um - 2 Colour", 600.0)],
    },
    {
        # Shipped, not yet billed: this is the "to invoice" list.
        "ref": "TP-DEMO-SO-05",
        "customer": "Gozo Farm Produce Co-operative",
        "days": -12,
        "status": "delivered",
        "lines": [("Printed Bread Bag Film 40um - 3 Colour", 500.0)],
    },
    {
        # Ordered, not shipped: the open delivery the warehouse is picking.
        "ref": "TP-DEMO-SO-06",
        "customer": "Mediterranean Bakeries Ltd",
        "days": -4,
        "status": "confirmed",
        "lines": [("Printed Bread Bag Film 40um - 3 Colour", 600.0)],
    },
    {
        "ref": "TP-DEMO-SO-07",
        "customer": "Valletta Foods Distribution Ltd",
        "days": -2,
        "status": "sent",
        "lines": [
            ("Printed Shrink Wrap 50um - 2 Colour", 400.0),
            ("Printed Bread Bag Film 40um - 3 Colour", 300.0),
        ],
    },
    {
        "ref": "TP-DEMO-SO-08",
        "customer": "Sicilia Fresh Produce S.p.A.",
        "days": -1,
        "status": "draft",
        "lines": [("Printed Shrink Wrap 50um - 2 Colour", 1000.0)],
    },
]
