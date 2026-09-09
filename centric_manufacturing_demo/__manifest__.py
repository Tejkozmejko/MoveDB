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
* a **finished bag range** - a printed carrier bag, a heavy duty black refuse
  sack made on the plant's own regrind, and an EN 13432 certified compostable
  carrier - counted in units rather than weighed, each carrying the
  certification claim that goes onto the quotation and the delivery note. The
  categories they sit in are now a tree under one ``Packaging`` root rather
  than three unrelated headings;
* the **kilogramme to unit conversion**, which the plant needs because it buys,
  extrudes and costs film by weight but sells bags by the thousand. Odoo will
  not convert between the two - they are different UoM categories - so the rate
  is held in two places derived from one figure: the bag's BoM, which produces
  1,000 bags and consumes the matching weight of film including its conversion
  offcut, and the product's own ``weight`` in kilogrammes per bag;
* a **bag pricing calculation** in ``pricing.py``, replacing the spreadsheet:
  film at its rolled-up cost, plus offcut, plus bag line time, plus cartons,
  divided by one minus the range's margin. Margin as a divisor, not a mark-up
  multiplier, which is the mistake that quietly gives a range away;
* the **regrind loop closed** with by-products - every extrusion, print and bag
  line BoM books its trim and set-up waste back into stock as recoverable
  scrap, which is what the granulator BoM then eats. Before this the loop only
  existed on paper and the scrap had to be counted in by hand;
* an **industrial packaging range** - pallet stretch wrap, a pallet shrink hood,
  a gusseted box liner and layflat tubing - on two grades the plant did not
  previously extrude: a heavy 100 micron clear and a 23 micron LLDPE stretch
  film with a tackifier for cling. Sold to a warehouse manager rather than a
  brand owner, so it sits in its own category under finished goods. It reuses
  the bag range's kilogramme-to-unit machinery rather than a copy of it, with
  each item carrying its own run size, because a run of pallet wrap is 200
  rolls and a run of bags is a thousand;
* **custom printed bags, made to order, one variant per customer artwork**. A
  printed carrier is not a stock item - the plant holds clear film and a set of
  plates per customer - so the artwork is a product attribute, which means the
  sales order line names it, each artwork has its own bill of materials with
  its own ink and press time, and cost and margin are answerable per artwork.
  The template carries the Make To Order and Manufacture routes, so confirming
  an order raises a works order rather than reserving finished bags that by
  definition do not exist. Plate sets are deliberately not components: a plate
  is tooling, cut once and mounted for every repeat, so what the run costs is
  the make-ready, which is in the operation time;
* **lot traceability from resin batch to delivered pallet**. Every material and
  made product that can carry a defect forward is tracked by lot - resin,
  masterbatch, additive, ink, reels, film and finished bags - and receipts mint
  a lot off the delivery note while works orders stamp the run they produced.
  A recalled resin batch is now answerable in Odoo in both directions: which
  reels it went into and which customers took them, and from a returned pallet
  back to the batch and the shift. Cores, cartons and recovered scrap are
  untracked on purpose - see ``traceability_data`` - and the regrind loop is
  the honest limit of the chain, which is why the certified biodegradable grade
  takes no regrind at all;
* a **rolled-up cost** on every made product, materials plus work centre time,
  computed level by level so the printed film carries the extrusion and
  regrind cost underneath it;
* **FIFO costing** on the packaging categories, set before the first product
  exists so material is costed under it from its first receipt rather than
  converted afterwards. The plant buys polymer on a moving market, and standard
  costing would bury that in a price variance nobody reads. Valuation is
  switched to **automated** in the same pass, but only where the chart of
  accounts can back it - a stock journal and a stock valuation account per
  category - and only before the first receipt, because Odoo will not convert
  a category that already holds valued stock. Where either condition fails the
  category stays periodic and the install log names it;
* an **opening stock count** for every bought-in material;
* a **reordering rule per bought-in material**, sized off its monthly run-rate
  and the lead time and minimum order quantity on its primary vendor's price
  list line - so correcting a lead time in Purchasing and re-seeding moves the
  reorder point with it. The reorder point covers the wait plus a safety buffer
  proportional to it; the maximum adds a month of cover, both rounded up so the
  rule never proposes an order below the vendor's minimum;
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

Two further pieces are seeded only when the app they need is installed, because
both are separate apps and a data module has no business installing an app on
every database that takes this seed. Install them from Apps and upgrade this
module, and they appear:

* **landed costs** on inbound resin (needs ``stock_landed_costs``) - sea
  freight and port handling allocated by weight, duty and insurance by value,
  the broker's fee split equally. Only the service products are seeded, not
  historical entries: revaluing receipts the seeded bills were costed against
  would stop the demo's accounting tying out;
* **quality checkpoints** (needs ``quality_control``, and ``quality_mrp`` to
  pin a check to an operation) - incoming resin against its batch certificate,
  film gauge across the web to a tolerance band, print colour against the
  signed proof, and seal strength off the bag line.

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
    "version": "19.0.6.0.0",
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
