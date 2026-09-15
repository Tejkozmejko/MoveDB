from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    centric_fsm_timesheet_min_duration = fields.Integer(
        string="Field Service Minimal Duration",
        config_parameter="centric_timesheet_rounding.fsm_min_duration",
        default=30,
    )
    centric_fsm_timesheet_rounding = fields.Integer(
        string="Field Service Round up",
        config_parameter="centric_timesheet_rounding.fsm_rounding",
        default=15,
    )
