from odoo import models

FSM_MIN_DURATION_PARAM = "centric_timesheet_rounding.fsm_min_duration"
FSM_ROUNDING_PARAM = "centric_timesheet_rounding.fsm_rounding"


def _fsm_rounding(env, minimal_duration, rounding):
    """Field Service (minimal duration, round up), in minutes.

    A parameter left at 0 means "no Field Service override", so the caller's
    native database-wide value is returned in its place.
    """
    params = env["ir.config_parameter"].sudo()
    return (
        int(params.get_param(FSM_MIN_DURATION_PARAM) or 0) or minimal_duration,
        int(params.get_param(FSM_ROUNDING_PARAM) or 0) or rounding,
    )


class AccountAnalyticLine(models.Model):
    """Rounding applied when the timer is stopped from the Timesheets grid."""

    _inherit = "account.analytic.line"

    def _timer_rounding(self, minutes_spent, minimal_duration, rounding):
        # Called one record at a time; on anything else keep the native values.
        if len(self) == 1 and self.project_id.is_fsm:
            minimal_duration, rounding = _fsm_rounding(self.env, minimal_duration, rounding)
        return super()._timer_rounding(minutes_spent, minimal_duration, rounding)


class ProjectTask(models.Model):
    """Rounding applied when the timer is stopped from the task itself.

    Field Service uses this path for its Start/Stop button, so overriding
    account.analytic.line alone would leave the FSM timer on the global values.
    """

    _inherit = "project.task"

    def _timer_rounding(self, minutes_spent, minimal_duration, rounding):
        if len(self) == 1 and self.project_id.is_fsm:
            minimal_duration, rounding = _fsm_rounding(self.env, minimal_duration, rounding)
        return super()._timer_rounding(minutes_spent, minimal_duration, rounding)
