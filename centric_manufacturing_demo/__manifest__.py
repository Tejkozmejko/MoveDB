{
    "name": "Centric Manufacturing Demo Data",
    "summary": "Raw material master, work centres, multi-level bills of materials with routings, opening stock and supplier terms for the flexible packaging plant.",
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
  primary vendor for everything and a dearer backup for the resins.

The quantities, formulations, cycle times and prices here are PLAUSIBLE DEMO
FIGURES, not the customer's real recipes or contracted terms. Replace them
before go-live.

Everything runs from a post-init hook and is idempotent: re-installing or
upgrading will not duplicate products, BoMs, work centres, stock or vendor
terms. A migration script re-runs the same hook on upgrade, so a database
installed before a given batch of data existed still picks it up.

Replaces ``centric_restaurant_demo``, which was removed when the restaurant
scope was dropped.
""",
    "version": "19.0.1.0.0",
    "category": "Manufacturing",
    "author": "Centric",
    "license": "LGPL-3",
    # mrp: the work centres, BoMs and routings. stock: opening quants.
    # purchase: the vendor price lists and lead times.
    "depends": ["mrp", "stock", "purchase"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
