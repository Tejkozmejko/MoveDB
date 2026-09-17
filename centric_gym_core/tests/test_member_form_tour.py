from odoo.tests import HttpCase, tagged

from .test_checkin import memberships


@tagged("post_install", "-at_install")
class TestMemberFormTour(HttpCase):

    def test_member_form_tour(self):
        self.env["res.partner"].create({"name": "Tour Member", "gym_member_state": "member"})
        self.start_tour(
            "/odoo/action-centric_gym_core.action_gym_members",
            "centric_gym_core_member_form",
            login="admin",
        )

    def test_reception_tour(self):
        self.env["gym.location"].create({"name": "Tour Gym"})
        visitor = self.env["res.partner"].create({"name": "Tour Visitor", "gym_member_state": "member"})
        self.env["res.partner"].create({"name": "Tour Lapsed", "gym_member_state": "member"})
        with memberships(visitor):
            self.start_tour(
                "/odoo/action-centric_gym_core.action_gym_reception",
                "centric_gym_core_reception",
                login="admin",
            )
