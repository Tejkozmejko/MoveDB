# Shopline demo data — native Odoo CSV import

This folder is **not an Odoo module**. There is no `__manifest__.py`, so Odoo will
never load it, even though it sits in the addons directory. It is a set of CSV
files for Odoo's own **Import records** feature, which is the native way to bulk
load data without writing a custom module.

## Why CSV and not the Claude chat proposals

The Claude bridge proposes one record per confirmation. The catalogue, customers
and orders below are about 90 records, which would be 90 separate Yes presses.
Odoo's built-in importer does the same work in five uploads.

## Import order matters

Import the files in numeric order. Later files reference earlier ones by
External ID, so a file will fail if the one before it has not been imported.

| # | File | Odoo screen to import from |
|---|---|---|
| 1 | `01_customers.csv` | Sales ▸ Orders ▸ Customers |
| 2 | `02_vendors.csv` | Purchase ▸ Orders ▸ Vendors |
| 3 | `03_products.csv` | Sales ▸ Products ▸ Products |
| 4 | `04_sales_orders.csv` | Sales ▸ Orders ▸ Quotations |
| 5 | `05_stock_onhand.csv` | Inventory ▸ Operations ▸ Physical Inventory |

How to import, on each screen: switch to **list view**, then the **gear / cog
icon** beside the view switcher ▸ **Import records** ▸ **Upload File** ▸ check the
column mapping ▸ **Test** ▸ **Import**.

## Prerequisites

Both sets of categories must exist before `03_products.csv`, because it matches
them **by name** and the names must match exactly:

- **Product categories** (internal, `categ_id`): Audio, Computers,
  Phones & Tablets, Home & Living, Accessories.
- **eCommerce categories** (`public_categ_ids`): the same five names again.
  These are a different model (`product.public.category`) and drive the shop's
  category navigation.

Both were proposed through the Claude chat. If a product row fails with
"No matching record found", one of the two is missing or spelled differently.

## Per-file notes

### 01_customers.csv / 02_vendors.csv
- `state_id` uses Odoo's display form, e.g. `California (US)`. Plain `California`
  will not match.
- Non-US vendors have `state_id` and some `zip` values left blank on purpose.
- `customer_rank` / `supplier_rank` are set to 1. Without them the records exist
  but do **not** appear under Sales ▸ Customers or Purchase ▸ Vendors, which is a
  common surprise.
- Child contacts use `parent_id/id` pointing at their company's External ID, so
  the company rows must be in the same file — they are.

### 03_products.csv
- Odoo 19 splits the old "Storable Product" type into `type` (`consu`) plus
  `is_storable` (`True`). Both columns are set accordingly. The two service rows
  are `type=service`, `is_storable=False`.
- `is_published` is `True` and `public_categ_ids` mirrors the internal category,
  so products land **live on the shop** with working category navigation. No
  second publishing pass needed.
- `standard_price` (Cost) is company-dependent. It imports fine, but if you run
  multi-company later it only applies to the company you imported as.
- **No images.** Images have to be base64 in CSV, which is impractical by hand.
  Add them in the product form, or drag them onto the shop page in the website
  editor. Products without images show a placeholder in the shop grid.

### 04_sales_orders.csv
- Order lines are **continuation rows**: the first row of an order carries the
  order fields plus its first line, then each extra line is a row with the leading
  columns left empty. Do not fill the blank cells in.
- `price_unit` is stated explicitly. Odoo's importer does **not** run onchanges,
  so relying on the price to be pulled from the product is risky; the values here
  match each product's `list_price`.
- Everything imports as a **draft quotation**. To make them real orders, select
  them in the list and use Actions, or open and Confirm. Leaving a few as drafts
  is realistic anyway.
- Dates span 2026-07-06 to 2026-09-14, so the Sales dashboard has a trend rather
  than one spike.

### 05_stock_onhand.csv
- `location_id/.id` is `5`, the **database id** of the internal stock location.
  `/.id` means "raw database id" rather than an External ID. This is used on
  purpose: the location was named `FM/Stock` and renaming the warehouse to `SL`
  changes that name but not the id, so this file keeps working either way.
  If you import into a different database, change the `5`.
- The column is `inventory_quantity` (Counted Quantity). After importing, the
  Physical Inventory screen will show the counted figures — press **Apply** to
  turn them into real on-hand stock.
- Only the 26 storable products are listed. The two services are not stocked.

## What is deliberately not here

- **Website pages, menus and theme.** These are built in the website editor, not
  imported. Odoo generates Home, Shop, Contact Us and Cart automatically when
  `website_sale` installs.
- **Payment provider setup.** `payment_custom` (Wire Transfer) needs enabling and
  its instructions text set, in Website ▸ Configuration ▸ Payment Providers.
- **Delivery methods.** Add under Website ▸ Configuration ▸ Delivery Methods.
  Without at least one, website checkout cannot complete.
- **Purchase orders and invoices.** Easier to generate from the imported data
  (reordering rules, or Create Invoice on confirmed orders) than to import, so
  the numbers reconcile.

## Re-running an import

Every row has an External ID (`id` column). Re-importing the same file **updates**
those records instead of duplicating them, so a failed import is safe to fix and
retry.
