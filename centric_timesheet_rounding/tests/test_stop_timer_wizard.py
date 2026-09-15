from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStopTimerWizardRounding(TransactionCase):
    """The Confirm Time Spent dialog offers the value that will be saved.

    The dialog is opened the way the Stop button opens it: the test presses the
    button, takes the action it returns and feeds that action's own context to
    the wizard. Nothing here hardcodes a context key or a private helper, so if
    the Enterprise flow changes shape these fail loudly rather than quietly
    passing while the dialog goes back to showing the global value.
    """

    WIZARD = "hr.timesheet.stop.timer.confirmation.wizard"

    def setUp(self):
        super().setUp()
        # Set both pairs through the settings screen rather than writing
        # ir.config_parameter keys, so the test does not depend on the native
        # parameter names.
        self.env["res.config.settings"].create({
            "timesheet_min_duration": 15,
            "timesheet_rounding": 15,
            "centric_fsm_timesheet_min_duration": 30,
            "centric_fsm_timesheet_rounding": 30,
        }).execute()
        if not self.env.user.employee_id:
            self.env["hr.employee"].create({
                "name": "Rounding Tester",
                "user_id": self.env.user.id,
                "company_id": self.env.company.id,
            })
        self.fsm_task = self._task("FSM Dialog", is_fsm=True)
        self.other_task = self._task("Regular Dialog", is_fsm=False)

    def _task(self, name, is_fsm):
        project = self.env["project.project"].create({
            "name": "%s Project" % name,
            "is_fsm": is_fsm,
            "allow_timesheets": True,
        })
        return self.env["project.task"].create({
            "name": name,
            "project_id": project.id,
        })

    def _proposed_time(self, task):
        """Start and immediately stop the timer; return what the dialog offers."""
        task.action_timer_start()
        action = task.action_timer_stop()
        self.assertIsInstance(
            action, dict, "Stop should return the Confirm Time Spent action")
        self.assertEqual(
            action.get("res_model"), self.WIZARD,
            "Stop no longer opens the Confirm Time Spent wizard")
        defaults = self.env[self.WIZARD].with_context(
            **(action.get("context") or {})
        ).default_get(["timesheet_id", "time_spent", "timesheet_name"])
        return defaults.get("time_spent")

    def test_fsm_dialog_proposes_the_field_service_minimum(self):
        # Stopped after no measurable time: the global rounding proposes 0:15,
        # Field Service has to raise the offer to 0:30.
        self.assertEqual(self._proposed_time(self.fsm_task), 0.5)

    def test_normal_task_dialog_keeps_the_global_value(self):
        self.assertEqual(self._proposed_time(self.other_task), 0.25)

    def test_dialog_matches_the_line_that_was_saved(self):
        # The point of the fix: the number offered and the number stored agree.
        proposed = self._proposed_time(self.fsm_task)
        line = self.env["account.analytic.line"].search(
            [("task_id", "=", self.fsm_task.id)], limit=1)
        self.assertTrue(line, "Stop should have created a timesheet line")
        self.assertEqual(proposed, line.unit_amount)

    def test_default_get_without_a_timesheet_is_left_alone(self):
        # The delete button can leave the dialog with no line behind it.
        defaults = self.env[self.WIZARD].with_context(
            default_time_spent=0.25
        ).default_get(["timesheet_id", "time_spent"])
        self.assertEqual(defaults.get("time_spent"), 0.25)
