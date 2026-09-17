from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestMemberFormTour(HttpCase):

    def test_member_form_tour(self):
        self.env["res.partner"].create({"name": "Tour Member", "gym_member_state": "member"})
        self.start_tour(
            "/odoo/action-centric_gym_core.action_gym_members",
            "centric_gym_core_member_form",
            login="admin",
        )
