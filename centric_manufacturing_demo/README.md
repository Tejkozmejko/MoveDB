# Centric Manufacturing Demo Data

Seed data for the flexible packaging plant: raw materials, work centres,
multi-level bills of materials with routings, opening stock, supplier terms and
a full trading history — purchases, production, sales, bills and invoices — so
a rebuilt database opens on populated apps rather than empty list views.

Replaces `centric_restaurant_demo`, removed when the restaurant scope was
dropped.

## What it creates

| Area | Detail |
| --- | --- |
| Materials | Polymer grades, masterbatch, additives, flexo inks, plate sets, cores, cartons — storable, costed per base unit (kg or units) |
| Work centres | Extrusion line, 6-colour flexo press, slitter/rewinder, granulator — rate, efficiency, setup/cleanup, OEE target |
| BoMs | `normal` (not kit) BoMs with routings, three levels deep |
| Costing | Rolled-up standard price per made product: components + work centre time |
| Costing method | Packaging categories put on FIFO before the first product exists. Valuation left as the database has it — automated valuation with no stock accounts breaks every stock move, and those accounts come with the chart of accounts |
| Industrial range | Pallet stretch wrap, a pallet shrink hood, a gusseted box liner and layflat tubing, on two new grades — 100 µm heavy clear and 23 µm LLDPE stretch with a tackifier. Own category, own run sizes: a run of pallet wrap is 200 rolls, not a thousand |
| Custom print | One product, one variant per customer artwork, made to order. Own BoM, ink and press time per artwork; plate sets are tooling, not components |
| Traceability | Lot tracking on every material and made product that can carry a defect forward. Receipts mint a lot off the delivery note, works orders stamp the run. Cores, cartons and recovered scrap deliberately untracked |
| Stock | One-off opening count per bought-in material, under a lot where the material is tracked |
| Replenishment | A reordering rule per bought-in material, sized from its monthly run-rate and the lead time and minimum order quantity on its primary vendor's price list line |
| Purchasing | A vendor per trade supplier, plus a price list line per material with price, minimum order quantity and lead time |
| Warehouse | Created if the company has none — a company that had Inventory installed after it was created never got one, and without a stock location nothing below can move |
| Customers | Five bakery, produce and grocery-retail buyers, with payment terms |
| Purchase orders | Eight, covering every state: draft RFQ, confirmed and awaiting delivery, received but unbilled, billed, and billed-and-paid |
| Manufacturing orders | Nine across all three BoM levels: six done, one live on the extrusion line, one confirmed, one draft |
| Sales orders | Eight: draft, sent, confirmed, delivered, invoiced and paid |
| Accounting | Posted vendor bills and customer invoices, with payments against some of them — so there is a payable, a receivable and a bank position |

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
                      │
                      └─ TP-BAGLINE ──> Carrier / Refuse / Biodegradable bags
                                        Custom printed bags (per artwork, MTO)

100 µm clear ──> TP-SLIT ─────> Layflat Tubing
             └─> TP-BAGLINE ──> Shrink Hood, Box Liner
23 µm stretch ─> TP-SLIT ─────> Pallet Stretch Wrap
```

Everything above the bag line is weighed in kilogrammes; everything below it is
counted in units. Odoo will not convert between the two — different UoM
categories, and rightly so, since the rate belongs to the bag — so the
conversion lives in the BoM (a run of *n* units consuming the matching film
weight, offcut included) and on the product's `weight` in kg per unit, both
derived from one `grams_per_bag` figure so they cannot drift apart.

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
  the buyer;
- every seeded trading document carries a reference — `TP-DEMO-PO-01`,
  `TP-DEMO-MO-04`, `TP-DEMO-SO-02` — in `partner_ref`, `origin` and
  `client_order_ref` respectively. A document already carrying one is skipped
  whole, so an upgrade never re-orders, re-produces or re-ships anything.

BoM lines and operations *are* rewritten to match the data files, since the
recipes are the point of the module.

## Caveats

All quantities, formulations, cycle times, prices and orders are **plausible
demo figures**, not the customer's real recipes, contracted terms or order
book. Vendor and customer contact details use the `.example` domain. Replace
all of it before go-live.

A trading document that cannot be built — a component short, a locked
accounting period, a bank journal with no outstanding account configured — is
rolled back on its own savepoint and logged, rather than failing the install.
After installing, check the log for:

```
centric_manufacturing_demo: purchase TP-DEMO-PO-01 skipped - ...
```

The summary line reports how many were skipped.

The reordering rules are live rules, not decoration: once the scheduler runs,
anything below its reorder point raises a replenishment. Every material is
seeded above its own reorder point, so nothing fires on day one — but consume
stock in the demo and the buyer will find draft purchase orders waiting, which
is the behaviour being demonstrated.

Lot tracking is switched on for the whole database, not just for these
products: it is a settings group, and turning it on puts a Lot/Serial column on
every tracked transfer. A product that already holds stock and no lots may
refuse the change — Odoo protecting a valuation it cannot retrospectively split
— in which case that one product is logged and skipped and the rest still get
tracked. Look for:

```
centric_manufacturing_demo: could not put ... on lot tracking - ...
```

The opening count is seeded as **one lot per material**, standing for "what was
on the floor at cutover". That is honest but coarse; split it against the real
delivery notes before go-live, or the first recall traces back to a single
number covering months of deliveries.

The regrind loop is the limit of a strict forwards trace: recovered scrap is
baled from every line and every grade at once, so it carries no lot. This is
why the certified biodegradable grade takes no regrind at all — its certificate
rests on a stated formulation, and a bale of unknown history cannot be declared
against it.

The custom print range is **made to order**, which means it turns on Odoo's
Replenish on Order route database-wide (it ships archived). Nothing else is put
on that route, but it becomes selectable on every product.

The trading quantities balance against each other: receipts and the opening
count cover what the manufacturing orders consume, and the done manufacturing
orders produce more than the delivered sales orders ship. Change a quantity in
`transaction_data.py` and the documents downstream of it may no longer have the
stock to run.

## Install / upgrade

Data is created by `post_init_hook` on install, and re-run by
`migrations/<version>/post-migrate.py` on upgrade. To add data later: bump
`version` in the manifest and copy the migration script into the matching
folder.
