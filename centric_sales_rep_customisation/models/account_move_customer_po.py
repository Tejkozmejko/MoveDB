from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    centric_customer_po = fields.Char(
        string="Purchase Order No",
        copy=False,
        help="The customer's own purchase order number, carried over from the "
             "sales order.",
    )
