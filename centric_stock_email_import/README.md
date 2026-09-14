# Centric Stock Email Import

An administrator emails a daily stocktake sheet (Excel `.xlsx` or `.csv`) to a
dedicated address. Odoo reads it and sets on-hand stock to the **counted**
quantities through standard inventory adjustments (the same thing
*Inventory > Physical Inventory > Apply* does), so stock valuation follows.

## Flow

1. Email arrives at the alias → a **Stock Email Import** record is created
   (Inventory > Stock Email Import > Imports).
2. Sender not in *Allowed Senders* → **Rejected**, stock untouched.
3. The processing job wakes immediately and reads the sheet:
   - every row is checked (product, location, lot, quantity);
   - **any** error → **Failed**, nothing applied, errors listed per row and
     emailed back to the sender;
   - all rows valid → counted quantities applied → **Applied**, with the
     before/after/difference per row, estimated value change, and links to the
     inventory moves.
4. The same file applied twice is refused (tick *Allow Duplicate* to override).

Products not in the sheet are left unchanged. Stock held in packages or
owned by third parties is not counted by this import.

## Setup

1. Install the module (depends on `stock_account`; `openpyxl` ships with Odoo).
2. Make sure an incoming mail domain works: Settings > General Settings >
   Alias Domain (on Odoo.sh e.g. `yourcompany.odoo.com`, or a custom domain
   whose MX points to Odoo / an incoming mail server fetching the mailbox).
   An address like `companyStocktake@odoo.com` is not possible - the alias
   lives on your own domain, e.g. `stocktake@yourcompany.odoo.com`.
3. Inventory > Stock Email Import > Configuration > New:
   - **Alias**: `stocktake`
   - **Allowed Senders**: the administrator's email address(es)
   - **Apply As**: an Inventory Administrator
   - **Default Location**: used when a row has no Location
   - **Price Column**: ignore / update cost / update sales price
   - **Create Missing Products / Lots**
4. *Download Excel Template* for a starter sheet.

## Sheet format

Columns are found by header name (case, spaces and punctuation ignored), in
any order, with the header row anywhere in the first 20 rows. Defaults:

| Field | Accepted headers |
|---|---|
| Product code | Product Code, Internal Reference, Reference, SKU, Item Code, Code |
| Barcode | Barcode, EAN, UPC, GTIN |
| Name | Name, Product Name, Product, Description, Item |
| Category | Category, Product Category |
| **Counted quantity** | Quantity, Counted Quantity, Qty, Count, Stock Count, On Hand |
| Location | Location, Bin, Stock Location (full name like `WH/Stock/Shelf 1`, name or barcode) |
| Lot / serial | Lot, Lot Number, Serial Number, Batch |
| Price | Price, Unit Price, Cost, Unit Cost |

A quantity column plus one of code/barcode/name is required. Add header names
for new sheet layouts under *Column Mapping* - no code change needed.

Rows for the same product + location + lot are added together. Lot-tracked
products need a lot on every row. A row with a product but an empty quantity is
skipped (a blank is not a zero).
