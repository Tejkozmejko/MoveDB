from odoo import fields, models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    # The order's confirmation date, exposed on the line so the product Card's
    # "Previously Purchased (this customer)" list can show when each purchase
    # happened. Related and non-stored: display only.
    centric_order_date = fields.Datetime(
        related="order_id.date_order",
        string="Order Date",
    )
