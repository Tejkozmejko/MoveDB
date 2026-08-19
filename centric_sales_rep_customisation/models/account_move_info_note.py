from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    centric_info_note = fields.Text(
        string="Info Note",
        copy=False,
        help="A note for the customer, printed on the invoice. Carried over "
             "from the sales order, and editable here.",
    )
