from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFsmTimesheetRounding(TransactionCase):
    """Field Service lines reach the minimum; everything else is left alone.

    These go through create/write on the real model rather than calling the
    rounding helper directly, so they exercise the same path the timer and the
    grid use. An earlier version of this module hooked the native timer helper
    instead and silently never fired -- these tests are what would have caught
    that.
    """

    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("centric_timesheet_rounding.fsm_min_duration", "30")
        params.set_param("centric_timesheet_rounding.fsm_rounding", "15")
        self.fsm_project = self.env["project.project"].create({
            "name": "FSM Rounding Test",
            "is_fsm": True,
            "allow_timesheets": True,
        })
        self.other_project = self.env["project.project"].create({
            "name": "Regular Rounding Test",
            "allow_timesheets": True,
        })

    def _line(self, project, unit_amount):
        return self.env["account.analytic.line"].create({
            "name": "/",
            "project_id": project.id,
            "unit_amount": unit_amount,
        })

    def test_fsm_applies_the_30_minute_floor_on_create(self):
        self.assertEqual(self._line(self.fsm_project, 0.05).unit_amount, 0.5)

    def test_fsm_rounds_up_in_15_minute_steps(self):
        # 38 minutes -> 45.
        self.assertAlmostEqual(self._line(self.fsm_project, 38 / 60).unit_amount, 0.75, places=4)

    def test_fsm_leaves_an_exact_step_alone(self):
        self.assertEqual(self._line(self.fsm_project, 0.75).unit_amount, 0.75)

    def test_fsm_applies_on_write(self):
        # The timer creates an empty line and writes the duration afterwards.
        line = self._line(self.fsm_project, 0.0)
        self.assertEqual(line.unit_amount, 0.0)
        line.write({"unit_amount": 0.05})
        self.assertEqual(line.unit_amount, 0.5)

    def test_empty_line_is_not_bumped_to_the_minimum(self):
        self.assertEqual(self._line(self.fsm_project, 0.0).unit_amount, 0.0)

    def test_non_fsm_is_untouched(self):
        self.assertEqual(self._line(self.other_project, 0.05).unit_amount, 0.05)

    def test_zero_settings_disable_the_override(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("centric_timesheet_rounding.fsm_min_duration", "0")
        params.set_param("centric_timesheet_rounding.fsm_rounding", "0")
        self.assertEqual(self._line(self.fsm_project, 0.05).unit_amount, 0.05)

    # Note: the validated / invoiced guard in _centric_apply_fsm_rounding is
    # deliberately not covered here. Both fields are readonly computes, so
    # setting them up would mean driving the validation and invoicing flows,
    # which is a lot of fixture for a two-condition guard.
