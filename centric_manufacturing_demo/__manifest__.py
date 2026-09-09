{
    "name": "Centric Manufacturing Demo Data",
    "summary": "Raw material master, work centres, multi-level bills of materials with routings, opening stock, supplier terms and a full trading history - purchases, production, sales, bills and invoices - for the flexible packaging plant.",
    "description": """
Seeds the data side of the manufacturing rollout, so a rebuilt database looks
like the live plant instead of an empty one:

* a **raw material master** - polymer grades, masterbatch, additives, flexo
  inks, plate sets, cores and cartons - as storable products costed per base
  unit (kilogrammes for compound and ink, units for counted goods);
* the **work centres**: the blown film extrusion line, the six colour flexo
  press, the slitter/rewinder and the granulator, each with an hourly rate,
  time efficiency, setup and cleanup times and an OEE target. A work centre
  that already exists is matched by code and left completely alone, so the
  rates someone tuned on the live database survive an install;
* **multi-level bills of materials with routings** - scrap is granulated into
  regrind, regrind and virgin resin are extruded into jumbo reels, and jumbo
  reels are printed and slit into finished film. These are ``normal`` BoMs,
  not kits, so producing them raises manufacturing orders and work orders and
  loads the work centres;
* a **rolled-up cost** on every made product, materials plus work centre time,
  computed level by level so the printed film carries the extrusion and
  regrind cost underneath it;
* an **opening stock count** for every bought-in material;
* a **vendor per trade supplier** and a purchase price list line per material,
  with the agreed price, minimum order quantity and delivery lead time - a
  primary vendor for everything and a dearer backup for the resins;
* the **warehouse** itself, if the company has not got one. A company that had
  Inventory installed after it was created never got the warehouse Odoo
  normally makes for it, and without a stock location nothing below can move;
* a **trading history**, so the database opens on populated apps rather than
  eight empty list views: customers, purchase orders in every state from an
  open request for quotation to a received, billed and paid delivery,
  multi-level manufacturing orders - regrind, extrusion, print and slit - some
  done, one live on the extrusion line and some still to release, and sales
  orders from draft quotation through to delivered, invoiced and paid. Posted
  vendor bills and customer invoices come with it, so Accounting has a payable,
  a receivable and a bank position rather than nothing.

The quantities, formulations, cycle times, prices and orders here are
PLAUSIBLE DEMO FIGURES, not the customer's real recipes, contracted terms or
order book. Replace them before go-live.

Everything runs from a post-init hook and is idempotent: re-installing or
upgrading will not duplicate products, BoMs, work centres, stock, vendor terms
or trading documents - every seeded order carries a reference such as
``TP-DEMO-PO-01`` and one already present is skipped whole. A migration script
re-runs the same hook on upgrade, so a database installed before a given batch
of data existed still picks it up.

A trading document that cannot be built - a component short, a locked
accounting period, a bank journal with no outstanding account - is rolled back
on its own savepoint and logged as a warning. A demo seed does not get to take
an install down with it, so check the install log for
``centric_manufacturing_demo: ... skipped``.

Replaces ``centric_restaurant_demo``, which was removed when the restaurant
scope was dropped.
""",
    "version": "19.0.2.0.0",
    "category": "Manufacturing",
    "author": "Centric",
    "license": "LGPL-3",
    # mrp: the work centres, BoMs and routings. stock: opening quants and the
    # warehouse. purchase_stock / sale_stock: purchase and sales orders that
    # actually move goods, which is what makes the receipts and deliveries
    # appear. account: the vendor bills, customer invoices and payments.
    # mrp_account: work centre time valued into the cost of the finished reel.
    "depends": [
        "mrp",
        "mrp_account",
        "stock",
        "purchase_stock",
        "sale_stock",
        "sale_management",
        "account",
    ],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
