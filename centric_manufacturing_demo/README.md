# Centric Manufacturing Demo Data

Seed data for the flexible packaging plant: raw materials, work centres,
multi-level bills of materials with routings, opening stock and supplier terms.

Replaces `centric_restaurant_demo`, removed when the restaurant scope was
dropped.

## What it creates

| Area | Detail |
| --- | --- |
| Materials | Polymer grades, masterbatch, additives, flexo inks, plate sets, cores, cartons — storable, costed per base unit (kg or units) |
| Work centres | Extrusion line, 6-colour flexo press, slitter/rewinder, granulator — rate, efficiency, setup/cleanup, OEE target |
| BoMs | `normal` (not kit) BoMs with routings, three levels deep |
| Costing | Rolled-up standard price per made product: components + work centre time |
| Stock | One-off opening count per bought-in material |
| Purchasing | A vendor per trade supplier, plus a price list line per material with price, minimum order quantity and lead time |

## The production flow

```
Production Film Scrap (LDPE)
  └─ TP-REGRIND ──> Regrind LDPE Pellet
                      │
LDPE / LLDPE resin ───┤
Masterbatch, additive ┤
Paper core 152mm ─────┘
  └─ TP-EXTRUDE ──> Blown Film Reel 50um Clear / White (Jumbo)
                      │
Flexo inks, extender ─┤
Paper core 76mm ──────┘
  └─ TP-FLEXO6 ──> TP-SLIT ──> Printed Bread Bag Film / Printed Shrink Wrap
```

Because the BoMs are `normal` rather than `phantom`, producing a finished film
raises a manufacturing order with work orders against each work centre, giving
real WIP, work centre load and OEE figures. A kit would have exploded silently
and produced none of that.

## Idempotency

The hook matches products, vendors and categories by **name** and work centres
by **code**, and skips anything it finds. Notably:

- an existing work centre is **never** rewritten — the rates and OEE targets on
  the live database were set by the plant, not by this module;
- a material that already holds stock is **not** counted in again, so an upgrade
  cannot reset a live store;
- an existing purchase price list line is left alone — trading terms belong to
  the buyer.

BoM lines and operations *are* rewritten to match the data files, since the
recipes are the point of the module.

## Caveats

All quantities, formulations, cycle times and prices are **plausible demo
figures**, not the customer's real recipes or contracted terms. Vendor contact
details use the `.example` domain. Replace both before go-live.

## Install / upgrade

Data is created by `post_init_hook` on install, and re-run by
`migrations/<version>/post-migrate.py` on upgrade. To add data later: bump
`version` in the manifest and copy the migration script into the matching
folder.
