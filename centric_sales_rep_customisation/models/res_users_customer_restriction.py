from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    centric_allowed_customer_ids = fields.Many2many(
        "res.partner",
        "centric_user_allowed_customer_rel",
        "user_id",
        "partner_id",
        string="Allowed Customers",
        domain=[("customer_rank", ">", 0)],
        help="If set, this user can only create and see sales orders for these "
        "customers (and their contacts). Leave empty for no restriction.",
    )
