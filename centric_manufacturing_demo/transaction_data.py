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

from .ecotax_data import COLLECTION_INVOICED, COLLECTION_POINT_OF_SALE

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
    # P8.1 - the buyers for the waste sack range, and a different trade from
    # everyone above. The five customers above buy film to wrap their own
    # product in; these two buy sacks to put other people's rubbish in, on a
    # tender rather than off a price list, and they pay like public bodies pay.
    "Cottonera Local Council": {
        "street": "Misrah Gavino Gulia",
        "city": "Cospicua",
        "zip": "BML 1010",
        "phone": "+356 2180 2255",
        "email": "procurement@cottoneracouncil.example",
        # The longest terms the plant grants anyone. Not a concession - it is
        # what a council's payment run does, and pricing a tender without
        # allowing for it is how a converter wins one and regrets it.
        "payment_term": "60 Days",
    },
    "Northern Region Waste Services Ltd": {
        "street": "Burmarrad Road",
        "city": "St Paul's Bay",
        "zip": "SPB 9060",
        "phone": "+356 2157 7130",
        "email": "operations@northernwaste.example",
        "payment_term": "45 Days",
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
    # P8.1 - what the waste sack range needed buying in that the plant did not
    # already stock: a green for the organic stream, and tape for the
    # drawstring hem.
    {
        "ref": "TP-DEMO-PO-09",
        "vendor": "EuroMasterbatch NV",
        "days": -50,
        "status": "billed",
        "lines": [("Green Masterbatch", 500.0)],
    },
    {
        "ref": "TP-DEMO-PO-10",
        "vendor": "Malta Core & Carton Ltd",
        "days": -18,
        "status": "received",
        "lines": [("LDPE Drawstring Tape 8mm", 150.0)],
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
    # ---------------------------------------------------------------- P8.1
    # The waste sack range, from the granulator up. Appended rather than
    # interleaved by date, because what matters to the seeder is the order of
    # this list - each order runs against the stock the ones above it left -
    # and the dates are stamped on afterwards. Reading the two halves in
    # sequence is also the clearer story: the plant's existing film business,
    # then the sack business built on top of it.
    #
    # Regrind first, and a big one. The four waste sack grades between them eat
    # about 830 kg of pellet, against the 500 kg the original run made, so
    # without this the extrusion orders below would confirm and then sit
    # unreserved - which is the failure mode the note at the top of this file
    # warns about, made concrete.
    {
        "ref": "TP-DEMO-MO-10",
        "product": "Regrind LDPE Pellet",
        "qty": 900.0,
        "days": -88,
        "status": "done",
    },
    {
        # Tops the clear reel back up: the carrier bag film below comes off it,
        # and the existing print orders had left it thin.
        "ref": "TP-DEMO-MO-11",
        "product": "Blown Film Reel 50um Clear (Jumbo)",
        "qty": 1500.0,
        "days": -84,
        "status": "done",
    },
    {
        # The 40 micron black already existed as a grade and had never been
        # run: the heavy duty sack it was written for is sold from stock the
        # plant bought in. The mixed waste collection sack is what finally puts
        # the extruder on it.
        "ref": "TP-DEMO-MO-12",
        "product": "Blown Film Reel 40um Black (Jumbo)",
        "qty": 800.0,
        "days": -78,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-13",
        "product": "Blown Film Reel 60um Black Heavy (Jumbo)",
        "qty": 1200.0,
        "days": -74,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-14",
        "product": "Blown Film Reel 30um Grey (Jumbo)",
        "qty": 800.0,
        "days": -70,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-15",
        "product": "Blown Film Reel 25um Green (Jumbo)",
        "qty": 600.0,
        "days": -66,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-16",
        "product": "Blown Film Reel 20um White (Jumbo)",
        "qty": 900.0,
        "days": -62,
        "status": "done",
    },
    # The carrier bag chain, run so the two eco-contribution sales orders have
    # something real to ship. Printed film first, then the bags off it.
    {
        "ref": "TP-DEMO-MO-17",
        "product": "Printed Carrier Bag Film 30um - 2 Colour",
        "qty": 600.0,
        "days": -58,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-18",
        "product": "Carrier Bag 380x450mm - 2 Colour Printed",
        "qty": 30000.0,
        "days": -54,
        "status": "done",
    },
    # Sacks. Counted in units, off the bag line, consuming the reels above.
    {
        "ref": "TP-DEMO-MO-19",
        "product": "Wheelie Bin Liner 240L 1100x1400mm Black",
        "qty": 500.0,
        "days": -40,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-20",
        "product": "Waste Sack 700x1100mm Black - Mixed Waste",
        "qty": 5000.0,
        "days": -35,
        "status": "done",
    },
    {
        "ref": "TP-DEMO-MO-21",
        "product": "Waste Sack 700x1100mm Grey - Recyclables",
        "qty": 4000.0,
        "days": -30,
        "status": "done",
    },
    {
        # Released and reserving, not yet run: puts the new bag line range on
        # the shopfloor view and the work centre load report rather than only
        # in the stock ledger.
        "ref": "TP-DEMO-MO-22",
        "product": "Swing Bin Liner 11L 300x600mm White",
        "qty": 6000.0,
        "days": 5,
        "status": "confirmed",
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
# above produced - 3700 kg of bread bag film and 2000 kg of shrink wrap, and
# for the P8.1 range 30,000 carrier bags, 5,000 mixed waste sacks, 4,000
# recyclables sacks and 500 wheelie liners - so nothing ships out of negative
# stock.
#
# ``eco_collection`` is optional and only means anything on an order carrying
# carrier bags. It picks which of the two collection models in ``ecotax_data``
# the order demonstrates:
#
#   COLLECTION_INVOICED        the levy is on the plant's invoice to the
#                              retailer, so the plant collects and remits it
#   COLLECTION_POINT_OF_SALE   the levy is left off the plant's invoice and
#                              charged to the shopper at the till instead
#
# Absent, the order is priced with whatever taxes the products carry, which for
# the carrier bag range means the levy is applied - the same as
# COLLECTION_INVOICED. It is spelled out on the two orders below anyway,
# because the whole point of them is to be read side by side.
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
    # ---------------------------------------------------------------- P8.2
    # The eco-contribution, twice. Same customer, same product, same 10,000
    # bags, same week, both invoiced and posted - and the ONLY difference
    # between them is who hands the levy over. That is deliberate: put the two
    # invoices side by side in Accounting and the entire argument is visible as
    # a difference in one figure, which is a good deal more convincing than a
    # paragraph explaining it.
    #
    # At the demo rate, 10,000 bags is 1,500 euro of levy. On SO-09 that sits
    # on the plant's invoice and the plant is financing it until a 60 day
    # customer pays. On SO-10 it does not appear at all, and the shopper pays
    # it at the till on the bags they actually take.
    {
        "ref": "TP-DEMO-SO-09",
        "customer": "IslandMart Retail Group Ltd",
        "days": -18,
        "status": "invoiced",
        "eco_collection": COLLECTION_INVOICED,
        "lines": [("Carrier Bag 380x450mm - 2 Colour Printed", 10000.0)],
    },
    {
        "ref": "TP-DEMO-SO-10",
        "customer": "IslandMart Retail Group Ltd",
        "days": -17,
        "status": "invoiced",
        "eco_collection": COLLECTION_POINT_OF_SALE,
        "lines": [("Carrier Bag 380x450mm - 2 Colour Printed", 10000.0)],
    },
    # ---------------------------------------------------------------- P8.1
    # The waste sack trade: a council on the collection set, a contractor on
    # wheelie liners, and a retailer quoting the household range. No levy on
    # any of them - see ecotax_data on why a refuse sack is not a carrier bag.
    {
        "ref": "TP-DEMO-SO-11",
        "customer": "Cottonera Local Council",
        "days": -24,
        "status": "paid",
        "lines": [
            ("Waste Sack 700x1100mm Black - Mixed Waste", 3000.0),
            ("Waste Sack 700x1100mm Grey - Recyclables", 2500.0),
        ],
    },
    {
        "ref": "TP-DEMO-SO-12",
        "customer": "Northern Region Waste Services Ltd",
        "days": -9,
        "status": "delivered",
        "lines": [("Wheelie Bin Liner 240L 1100x1400mm Black", 400.0)],
    },
    {
        # A quotation, not an order, and that is what lets it price the three
        # lines the plant has not made yet - the green sack, the caddy liner
        # and the drawstring bag. A quotation reserves nothing, so the range
        # can be shown being sold without inventing stock for it.
        "ref": "TP-DEMO-SO-13",
        "customer": "IslandMart Retail Group Ltd",
        "days": -3,
        "status": "sent",
        "lines": [
            ("Waste Sack 700x1100mm Green - Organic Waste", 4000.0),
            ("Compostable Caddy Liner 10L 380x480mm", 5000.0),
            ("Drawstring Kitchen Bag 30L 480x600mm White", 3000.0),
        ],
    },
]
