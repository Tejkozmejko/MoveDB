from odoo import api, models


class HrTimesheetStopTimerConfirmationWizard(models.TransientModel):
    """Propose the rounding that will actually be saved in "Confirm Time Spent".

    The dialog's `time_spent` is handed to it already rounded by the native
    database-wide setting, independently of the timesheet line it points at. So
    on a Field Service task the line was correctly stored as 0:30 while the
    dialog still offered 0:15, and the technician was shown a number the
    database disagreed with.

    Re-round the proposal through the same rule the line itself uses, so the
    number offered is the number stored. Delegating to the line's
    `_centric_rounding_rule` rather than reading the Field Service settings
    directly means any other module extending that rule is covered here too.
    """

    _inherit = "hr.timesheet.stop.timer.confirmation.wizard"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        return self._centric_round_proposal(res)

    @api.model_create_multi
    def create(self, vals_list):
        # The Stop button creates the dialog record with time_spent already
        # filled in and opens it by id, so default_get never sees that value -
        # it has to be corrected here as well.
        return super().create([self._centric_round_proposal(dict(vals)) for vals in vals_list])

    @api.model
    def _centric_round_proposal(self, values):
        """`values` with time_spent re-rounded by its timesheet line's rule."""
        if not values.get("time_spent"):
            return values
        timesheet = self._centric_wizard_timesheet(values)
        if not timesheet:
            return values
        minimal_minutes, step_minutes = timesheet._centric_rounding_rule()
        if not minimal_minutes and not step_minutes:
            return values
        # time_spent is in hours -- the form renders it with widget="float_time".
        values["time_spent"] = timesheet._centric_round_hours(
            values["time_spent"], minimal_minutes, step_minutes
        )
        return values

    @api.model
    def _centric_wizard_timesheet(self, defaults):
        """The timesheet line this dialog is about, empty if not known yet.

        The Stop button creates the line before opening the dialog, so it is
        normally already there; default_get resolves it out of the context for
        us, and we fall back to the raw context key for safety.
        """
        timesheet_id = defaults.get("timesheet_id") or self.env.context.get(
            "default_timesheet_id"
        )
        if not timesheet_id:
            return self.env["account.analytic.line"]
        return self.env["account.analytic.line"].browse(timesheet_id).exists()
