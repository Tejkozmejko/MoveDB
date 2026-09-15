from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFsmTimerRounding(TransactionCase):
    """The Field Service override replaces the global values, and only there.

    These also pin the signature of the native _timer_rounding hook: if a future
    Odoo version changes it, these fail rather than the rounding silently
    reverting to the global setting.
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

    def _line(self, project):
        return self.env["account.analytic.line"].create({
            "name": "/",
            "project_id": project.id,
            "unit_amount": 0.0,
        })

    def test_fsm_applies_the_30_minute_floor(self):
        self.assertEqual(self._line(self.fsm_project)._timer_rounding(4, 15, 15), 30)

    def test_fsm_rounds_up_in_15_minute_steps(self):
        self.assertEqual(self._line(self.fsm_project)._timer_rounding(38, 15, 15), 45)

    def test_non_fsm_keeps_the_global_values(self):
        self.assertEqual(self._line(self.other_project)._timer_rounding(4, 15, 15), 15)

    def test_zero_falls_back_to_the_global_values(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("centric_timesheet_rounding.fsm_min_duration", "0")
        params.set_param("centric_timesheet_rounding.fsm_rounding", "0")
        self.assertEqual(self._line(self.fsm_project)._timer_rounding(4, 15, 15), 15)

    def test_fsm_task_timer_uses_the_override(self):
        task = self.env["project.task"].create({
            "name": "FSM Rounding Task",
            "project_id": self.fsm_project.id,
        })
        self.assertEqual(task._timer_rounding(4, 15, 15), 30)
