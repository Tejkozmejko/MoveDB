from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    centric_driver_department_id = fields.Many2one(
        "hr.department",
        string="Drivers Department",
        help="Only employees in this department are offered as Drivers on sales "
             "orders, deliveries and payment collection.",
    )
