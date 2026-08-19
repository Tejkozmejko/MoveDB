from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Write-only scan box. The barcode scanner types the code and sends Enter; the
    # small field widget (centric_barcode_scan) commits it here, which fires the
    # onchange below to add / increment the product line, then clears the box for
    # the next scan. Non-stored: it is a transient input, never persisted.
    centric_barcode_scan = fields.Char(
        string="Scan Product",
        store=False,
        copy=False,
        help="Scan a product barcode to add it to the order, or increment its "
        "quantity if it is already on the order.",
    )

    @api.onchange("centric_barcode_scan")
    def _centric_onchange_barcode_scan(self):
        code = (self.centric_barcode_scan or "").strip()
        # Always clear so the box is immediately ready for the next scan.
        self.centric_barcode_scan = False
        if not code:
            return
        # Defensive on duplicate barcodes: take the first matching product.
        product = self.env["product.product"].search(
            [("barcode", "=", code)], limit=1)
        if not product:
            return {
                "warning": {
                    "title": _("Unknown barcode"),
                    "message": _(
                        "No product matches the barcode \"%(code)s\". "
                        "Nothing was added.", code=code),
                }
            }
        existing = self.order_line.filtered(
            lambda line: line.product_id == product and not line.display_type
        )[:1]
        if existing:
            existing.product_uom_qty += 1
        else:
            self.order_line += self.env["sale.order.line"].new(
                {"product_id": product.id, "product_uom_qty": 1})
