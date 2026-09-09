# Centric Restaurant Reporting

Delivers phase **9 — Reporting & Dashboards** of the restaurant rollout:
9.1 (session and daily reports), 9.2 (margin per dish), 9.3 (menu engineering)
and 9.4 (scheduled summary email).

## Menu Performance

`centric.restaurant.menu.report` is a SQL view over `pos_order_line`, one row
per line, exposing **quantity, net revenue, cost and margin**. Odoo's own
`report.pos.order` aggregates to order level and carries no cost, so it cannot
answer "what does this dish actually make?".

Cost is `pos_order_line.total_cost`, the figure Odoo snapshots at sale time
from the product's standard price. For the menu that price is the kit-BoM
roll-up written by `centric_restaurant_demo`, so **margin here is recipe
driven**, not a guess. Dishes sold before costing was configured show a zero
cost, which reads as 100% margin — check the earliest data before drawing
conclusions from it.

Find it at **Point of Sale → Reporting → Menu Performance** (POS Manager
group). Pivot, graph and list, grouped by dish by default over the current
month, with shared favourites for Today, This Week, Last Month and a Menu
Engineering view (category × dish, volume against margin — stars and dogs on
one grid).

Refunds appear as negative quantities and negative revenue, so they net off
rather than needing a separate filter. Cancelled and draft orders are excluded.

## Wastage

**Point of Sale → Reporting → Wastage** — a pivot and graph on completed
`stock.scrap` records, by product and scrap reason.

This one reads `stock.scrap` directly rather than through a SQL view, because
the *value* of a scrap depends on the product's cost, which Odoo stores per
company and does not expose as a plain queryable column. Quantities are honest;
costing wastage would need stock valuation turned on and is not attempted here.

## Daily trading summary email

A scheduled action, **Restaurant: daily trading summary email**, emails the
previous trading day's orders, covers, net sales, cost, gross margin, average
spend per cover, top five sellers, five weakest margins and wastage count.

The trading day is bounded by the **company's timezone**, not the server's, so
a service running past midnight UTC is not split across two reports.

### It is shipped switched OFF

Installing a module should not start sending mail to real people. To turn it
on: **Settings → Technical → Scheduled Actions → Restaurant: daily trading
summary email → Active**. It then runs daily at 06:00.

### Recipients

By default, every user in the **POS Manager** group that has an email address.
To send somewhere else instead, set the system parameter
`centric_restaurant_reporting.summary_recipients` to a comma-separated list of
addresses (Settings → Technical → System Parameters). If neither yields an
address the job logs a warning and sends nothing.

## What this module does not do

No spreadsheet dashboard tile. Odoo's `spreadsheet.dashboard` records store an
opaque JSON blob that is painful to maintain in source and breaks across
versions; a pivot with saved favourites gives managers the same numbers and
stays reviewable in git. If a tiled dashboard is wanted, build it in the UI
from these views.
