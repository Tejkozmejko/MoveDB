from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    pos_gym_location_id = fields.Many2one(related="pos_config_id.gym_location_id", readonly=False)
