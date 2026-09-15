from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHelpdeskTimesheetRounding(TransactionCase):
    """Each Helpdesk team rounds its own tickets; Field Service keeps its own rule.

    Everything goes through create/write on account.analytic.line, the path the
    timer and the grid take, so a hook that never fires fails here.
    """

    def setUp(self):
        super().setUp()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("centric_timesheet_rounding.fsm_min_duration", "30")
        params.set_param("centric_timesheet_rounding.fsm_rounding", "15")
        # Timesheet lines need an employee for the user logging them.
        if not self.env.user.employee_id:
            self.env["hr.employee"].create({"name": self.env.user.name, "user_id": self.env.user.id})
        Team = self.env["helpdesk.team"]
        self.support = Team.create({
            "name": "Rounding Support",
            "use_helpdesk_timesheet": True,
            "centric_timesheet_min_duration": 15,
            "centric_timesheet_rounding": 15,
        })
        self.onsite = Team.create({
            "name": "Rounding Onsite",
            "use_helpdesk_timesheet": True,
            "centric_timesheet_min_duration": 60,
            "centric_timesheet_rounding": 30,
        })
        self.plain = Team.create({
            "name": "Rounding Plain",
            "use_helpdesk_timesheet": True,
        })
        self.fsm_project = self.env["project.project"].create({
            "name": "FSM Rounding Test", "is_fsm": True, "allow_timesheets": True,
        })

    def _ticket(self, team):
        return self.env["helpdesk.ticket"].create({"name": "Printer jam", "team_id": team.id})

    def _ticket_line(self, ticket, hours):
        return self.env["account.analytic.line"].create({
            "name": "/",
            "project_id": ticket.team_id.project_id.id,
            "helpdesk_ticket_id": ticket.id,
            "unit_amount": hours,
        })

    def test_team_minimum_applies(self):
        # 4 minutes on Support -> 15.
        line = self._ticket_line(self._ticket(self.support), 4 / 60)
        self.assertAlmostEqual(line.unit_amount, 0.25, places=4)

    def test_teams_round_up_in_their_own_steps(self):
        # 38 minutes: Support rounds to 45, Onsite to its 60 minimum.
        self.assertAlmostEqual(self._ticket_line(self._ticket(self.support), 38 / 60).unit_amount, 0.75, places=4)
        self.assertAlmostEqual(self._ticket_line(self._ticket(self.onsite), 38 / 60).unit_amount, 1.0, places=4)
        # 70 minutes on Onsite -> 90.
        self.assertAlmostEqual(self._ticket_line(self._ticket(self.onsite), 70 / 60).unit_amount, 1.5, places=4)

    def test_timer_style_write_is_rounded(self):
        # The timer creates an empty line and writes the duration afterwards.
        line = self._ticket_line(self._ticket(self.onsite), 0.0)
        self.assertEqual(line.unit_amount, 0.0)
        line.write({"unit_amount": 5 / 60})
        self.assertAlmostEqual(line.unit_amount, 1.0, places=4)

    def test_team_without_values_is_untouched(self):
        line = self._ticket_line(self._ticket(self.plain), 4 / 60)
        self.assertAlmostEqual(line.unit_amount, 4 / 60, places=4)

    def test_moving_a_line_to_another_team_uses_that_team(self):
        line = self._ticket_line(self._ticket(self.plain), 4 / 60)
        onsite_ticket = self._ticket(self.onsite)
        line.write({
            "helpdesk_ticket_id": onsite_ticket.id,
            "project_id": onsite_ticket.team_id.project_id.id,
        })
        self.assertAlmostEqual(line.unit_amount, 1.0, places=4)

    def test_field_service_keeps_its_own_rule(self):
        line = self.env["account.analytic.line"].create({
            "name": "/", "project_id": self.fsm_project.id, "unit_amount": 4 / 60,
        })
        self.assertEqual(line.unit_amount, 0.5)
