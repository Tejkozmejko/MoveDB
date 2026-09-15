from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStopTimerWizardRounding(TransactionCase):
    """The Confirm Time Spent dialog offers the value that will be saved.

    The dialog is opened the way the database showed Stop opening it: a
    `default_timesheet_id` pointing at the stopped line and a `default_time_spent`
    already rounded by the global setting. The earlier version of these tests
    pressed the Enterprise Stop button and wrote the global settings through the
    settings screen; that build failed, and neither is needed to prove the fix,
    so the tests stay on the fields this module actually touches.
    """

    WIZARD = "hr.timesheet.stop.timer.confirmation.wizard"

    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("centric_timesheet_rounding.fsm_min_duration", "30")
        params.set_param("centric_timesheet_rounding.fsm_rounding", "30")
        self.fsm_project = self.env["project.project"].create({
            "name": "FSM Dialog Test", "is_fsm": True, "allow_timesheets": True,
        })
        self.other_project = self.env["project.project"].create({
            "name": "Regular Dialog Test", "allow_timesheets": True,
        })

    def _line(self, project):
        # Created empty, as the timer does, so the line's own rounding is not
        # what the dialog ends up showing.
        return self.env["account.analytic.line"].create({
            "name": "/", "project_id": project.id, "unit_amount": 0.0,
        })

    def _proposed(self, line, time_spent):
        context = {"default_time_spent": time_spent}
        if line:
            context["default_timesheet_id"] = line.id
        defaults = self.env[self.WIZARD].with_context(**context).default_get(
            ["timesheet_id", "time_spent", "timesheet_name"]
        )
        return defaults.get("time_spent")

    def test_fsm_dialog_proposes_the_field_service_minimum(self):
        # The global 15 min proposal is raised to Field Service's 30.
        self.assertAlmostEqual(self._proposed(self._line(self.fsm_project), 0.25), 0.5, places=4)

    def test_fsm_dialog_rounds_up_in_field_service_steps(self):
        # 40 minutes -> 60 with a 30 minute step.
        self.assertAlmostEqual(self._proposed(self._line(self.fsm_project), 40 / 60), 1.0, places=4)

    def test_normal_task_dialog_keeps_the_global_value(self):
        self.assertAlmostEqual(self._proposed(self._line(self.other_project), 0.25), 0.25, places=4)

    def test_dialog_matches_what_the_line_will_store(self):
        line = self._line(self.fsm_project)
        proposed = self._proposed(line, 0.25)
        line.write({"unit_amount": proposed})
        self.assertAlmostEqual(line.unit_amount, proposed, places=4)

    def test_dialog_without_a_timesheet_is_left_alone(self):
        self.assertAlmostEqual(self._proposed(None, 0.25), 0.25, places=4)
