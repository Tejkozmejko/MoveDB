from odoo import api, models

FSM_MIN_DURATION_PARAM = "centric_timesheet_rounding.fsm_min_duration"
FSM_ROUNDING_PARAM = "centric_timesheet_rounding.fsm_rounding"


class AccountAnalyticLine(models.Model):
    """Enforce the Field Service minimum and step on timesheet lines.

    The rounding is applied on create/write rather than by overriding the
    native timer hook. Whichever button produced the line -- the Field Service
    Start/Stop, the Timesheets grid timer, or a value typed in by hand -- it
    reaches the database through the ORM, so this is the one place that catches
    every path. The native database-wide rounding still runs first; this only
    raises the result where Field Service asks for more.
    """

    _inherit = "account.analytic.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._centric_apply_fsm_rounding()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if {"unit_amount", "project_id", "task_id"} & vals.keys():
            self._centric_apply_fsm_rounding()
        return res

    def _centric_apply_fsm_rounding(self):
        minimal_minutes, step_minutes = self._centric_fsm_params()
        if not minimal_minutes and not step_minutes:
            return
        for line in self:
            if not line.project_id.is_fsm:
                continue
            # Never reopen time that has been signed off or billed.
            if line.validated or line.timesheet_invoice_id:
                continue
            rounded = self._centric_round_hours(line.unit_amount, minimal_minutes, step_minutes)
            if abs(rounded - line.unit_amount) > 1e-4:
                # Bypass our own write() so this cannot recurse.
                super(AccountAnalyticLine, line).write({"unit_amount": rounded})

    @api.model
    def _centric_fsm_params(self):
        """Field Service (minimal duration, round up), in minutes. 0 disables."""
        params = self.env["ir.config_parameter"].sudo()
        return (
            int(params.get_param(FSM_MIN_DURATION_PARAM) or 0),
            int(params.get_param(FSM_ROUNDING_PARAM) or 0),
        )

    @api.model
    def _centric_round_hours(self, hours, minimal_minutes, step_minutes):
        """Round hours up to the minimum, then to the next whole step.

        An empty line is left alone, so a timer that is still running does not
        jump to the minimum before any time has actually been spent.
        """
        minutes = hours * 60.0
        if minutes <= 0:
            return hours
        minutes = max(minutes, minimal_minutes)
        if step_minutes:
            steps = int(minutes / step_minutes)
            if minutes - steps * step_minutes > 1e-6:
                steps += 1
            minutes = steps * step_minutes
        return minutes / 60.0
