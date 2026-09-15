from odoo import models


class AccountAnalyticLine(models.Model):
    """Helpdesk tickets round by their team's own minimum and step.

    Plugs into Centric Timesheet Rounding's single rule hook, so the rounded
    value is still written in exactly one place and cannot fight the Field
    Service rule.
    """

    _inherit = "account.analytic.line"

    # Moving a line onto another ticket can move it under another team's rule.
    _centric_rounding_triggers = {"unit_amount", "project_id", "task_id", "helpdesk_ticket_id"}

    def _centric_rounding_rule(self):
        self.ensure_one()
        team = self.helpdesk_ticket_id.team_id
        if team and (team.centric_timesheet_min_duration or team.centric_timesheet_rounding):
            return team.centric_timesheet_min_duration, team.centric_timesheet_rounding
        return super()._centric_rounding_rule()
