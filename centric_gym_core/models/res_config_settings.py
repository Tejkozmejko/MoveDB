from odoo import _, api, fields, models

from .res_partner import (
    DEFAULT_MINOR_AGE,
    DEFAULT_QUARANTINE_MONTHS,
    DEFAULT_RELEASE_MONTHS,
    PARAM_AUTO_RELEASE,
    PARAM_MINOR_AGE,
    PARAM_QUARANTINE_MONTHS,
    PARAM_RELEASE_MONTHS,
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    gym_pin_auto_release = fields.Boolean(
        string="Release PINs of Inactive Members",
        config_parameter=PARAM_AUTO_RELEASE,
    )
    gym_pin_release_months = fields.Integer(
        string="Inactive For",
        config_parameter=PARAM_RELEASE_MONTHS,
        default=DEFAULT_RELEASE_MONTHS,
    )
    gym_pin_quarantine_months = fields.Integer(
        string="Wait Before Reuse",
        config_parameter=PARAM_QUARANTINE_MONTHS,
        default=DEFAULT_QUARANTINE_MONTHS,
    )
    gym_minor_age = fields.Integer(
        string="Adult From Age",
        config_parameter=PARAM_MINOR_AGE,
        default=DEFAULT_MINOR_AGE,
    )
    gym_pin_usage = fields.Char(string="PINs in Use", compute="_compute_gym_pin_usage")
    gym_pin_usage_warning = fields.Boolean(compute="_compute_gym_pin_usage")

    @api.depends("company_id")
    def _compute_gym_pin_usage(self):
        held, total = self.env["res.partner"]._gym_pin_usage()
        for settings in self:
            settings.gym_pin_usage = _("%(held)s of %(total)s", held=held, total=total)
            settings.gym_pin_usage_warning = bool(total) and held >= 0.9 * total
