from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HelpdeskTeam(models.Model):
    _inherit = "helpdesk.team"

    centric_timesheet_min_duration = fields.Integer(
        string="Minimum Time",
        default=0,
        help="Timesheets logged on this team's tickets below this many minutes are "
             "rounded up to it. For instance, with 15 min, a timer stopped at 00:04 "
             "records 00:15. 0 keeps the database-wide Time Rounding setting.",
    )
    centric_timesheet_rounding = fields.Integer(
        string="Round Up",
        default=0,
        help="Past the minimum, this team's timesheets are rounded up to the next "
             "multiple of this many minutes. For instance, with 15 min, 00:38 records "
             "00:45. 0 keeps the database-wide Time Rounding setting.",
    )

    @api.constrains("centric_timesheet_min_duration", "centric_timesheet_rounding")
    def _check_centric_timesheet_rounding(self):
        for team in self:
            if team.centric_timesheet_min_duration < 0 or team.centric_timesheet_rounding < 0:
                raise ValidationError(_("Timesheet rounding minutes cannot be negative."))
