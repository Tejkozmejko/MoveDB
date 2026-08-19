from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    centric_driver_department_id = fields.Many2one(
        related="company_id.centric_driver_department_id",
        string="Drivers Department",
        readonly=False,
    )
