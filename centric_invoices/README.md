# Centric Invoices (`centric_invoices`)

Choose how your invoices look, with a live invoice preview.

## What it adds

**Invoicing → Configuration → Invoice Layout** (administrators only) opens Odoo's
own layout chooser in its invoice version. There you can pick:

- the layout (Light, Boxed, Bold, Striped, …)
- font, colours, logo and background
- company details, header and footer
- the VAT number, the bank account and the payment QR code

The result is shown on a sample invoice. Click **Continue** to save.

## What it does not change

- The standard **Settings → General Settings → Configure Document Layout** stays as it is.
- The layout screen Odoo shows before the first print stays as it is.

## Good to know

The chosen layout is the company's document layout, so it applies to every
printed document, not only invoices.

## Tests

```
python -m odoo -d <db> -i centric_invoices --test-enable --test-tags /centric_invoices --stop-after-init
```
