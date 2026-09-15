from odoo import api, models

FSM_MIN_DURATION_PARAM = "centric_timesheet_rounding.fsm_min_duration"
FSM_ROUNDING_PARAM = "centric_timesheet_rounding.fsm_rounding"


class AccountAnalyticLine(models.Model):
    """Enforce a per-app minimum and step on timesheet lines.

    The rounding is applied on create/write rather than by overriding the
    native timer hook. Whichever button produced the line -- the Field Service
    Start/Stop, the Timesheets grid timer, or a value typed in by hand -- it
    reaches the database through the ORM, so this is the one place that catches
    every path. The native database-wide rounding still runs first; this only
    raises the result where an app asks for more.

    Which rule applies to a line is decided by `_centric_rounding_rule`. This
    module answers for Field Service; other modules (Helpdesk teams, for one)
    extend it for their own lines, so there is still exactly one place that
    writes the rounded value.
    """

    _inherit = "account.analytic.line"

    # A write touching any of these can change the rule or the duration.
    _centric_rounding_triggers = {"unit_amount", "project_id", "task_id"}

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._centric_apply_rounding()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if self._centric_rounding_triggers & vals.keys():
            self._centric_apply_rounding()
        return res

    def _centric_apply_rounding(self):
        for line in self:
            minimal_minutes, step_minutes = line._centric_rounding_rule()
            if not minimal_minutes and not step_minutes:
                continue
            # Never reopen time that has been signed off or billed.
            if line.validated or line.timesheet_invoice_id:
                continue
            rounded = self._centric_round_hours(line.unit_amount, minimal_minutes, step_minutes)
            if abs(rounded - line.unit_amount) > 1e-4:
                # Bypass our own write() so this cannot recurse.
                super(AccountAnalyticLine, line).write({"unit_amount": rounded})

    def _centric_rounding_rule(self):
        """(minimal duration, round up) in minutes for this line; (0, 0) for none."""
        self.ensure_one()
        if self.project_id.is_fsm:
            return self._centric_fsm_params()
        return 0, 0

    # Kept under its original name for anything already calling it.
    def _centric_apply_fsm_rounding(self):
        self._centric_apply_rounding()

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
