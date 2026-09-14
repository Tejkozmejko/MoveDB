from odoo import fields, models


class StockEmailImportLine(models.Model):
    """One sheet row as read, and the stock change it caused."""

    _name = "stock.email.import.line"
    _description = "Stock Email Import Line"
    _order = "import_id, row_number, id"

    import_id = fields.Many2one(
        "stock.email.import", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="import_id.company_id", store=True)
    currency_id = fields.Many2one(related="import_id.currency_id")
    row_number = fields.Integer(string="Row")
    product_code = fields.Char()
    barcode = fields.Char()
    product_name = fields.Char()
    category_name = fields.Char(string="Category")
    location_name = fields.Char(string="Location Text")
    lot_name = fields.Char(string="Lot Text")
    product_id = fields.Many2one("product.product")
    location_id = fields.Many2one("stock.location")
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial")
    counted_qty = fields.Float(string="Counted", digits="Product Unit")
    previous_qty = fields.Float(string="Before", digits="Product Unit")
    difference_qty = fields.Float(string="Difference", digits="Product Unit")
    price = fields.Float(digits="Product Price")
    value_change = fields.Monetary()
    status = fields.Selection(
        [("ok", "OK"), ("skipped", "Skipped"), ("error", "Error")],
        default="ok", required=True,
    )
    message = fields.Text()
