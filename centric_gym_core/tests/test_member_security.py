from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import GymCoreCase


@tagged("post_install", "-at_install")
class TestMemberSecurity(GymCoreCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.member = cls.env["res.partner"].create({
            "name": "Joe Camilleri",
            "gym_member_state": "member",
            "gym_emergency_name": "Rita Camilleri",
            "gym_emergency_phone": "+356 7900 0000",
        })

    # Protected member fields ----------------------------------------------

    def test_reception_cannot_make_members_or_change_pins(self):
        member = self.member.with_user(self.reception)
        with self.assertRaises(AccessError):
            member.write({"gym_pin": "0999"})
        with self.assertRaises(AccessError):
            member.write({"gym_member_state": "former"})
        with self.assertRaises(AccessError):
            self.Partner.with_user(self.reception).create({"name": "Sneaky", "gym_member_state": "member"})
        with self.assertRaises(AccessError):
            member.action_gym_make_member()
        with self.assertRaises(AccessError):
            member.action_gym_release_pin()

    def test_reception_can_still_create_contacts_and_edit_member_details(self):
        contact = self.Partner.with_user(self.reception).create({
            "name": "Walk-in", "gym_member_state": "none", "gym_pin": False,
        })
        self.assertEqual(contact.gym_member_state, "none")
        self.member.with_user(self.reception).write({"gym_birthdate": "1990-05-01", "phone": "+356 2100 0000"})
        self.assertEqual(str(self.member.gym_birthdate), "1990-05-01")

    def test_reception_can_replace_a_lost_card(self):
        self.member.with_user(self.reception).action_gym_reissue_card()
        self.assertEqual(self.member.gym_card_no, 2)

    def test_manager_can_make_a_member(self):
        contact = self.Partner.create({"name": "Prospect"})
        contact.with_user(self.manager).action_gym_make_member()
        self.assertEqual(contact.gym_member_state, "member")
        self.assertTrue(contact.gym_pin)

    def test_reception_sees_pin_and_emergency_contact(self):
        values = self.member.with_user(self.reception).read(
            ["gym_pin", "gym_emergency_name", "gym_emergency_phone", "gym_health_alert"]
        )[0]
        self.assertEqual(values["gym_pin"], self.member.gym_pin)
        self.assertEqual(values["gym_emergency_name"], "Rita Camilleri")

    def test_pin_history_is_for_managers(self):
        with self.assertRaises(AccessError):
            self.member.with_user(self.reception).read(["gym_pin_assignment_ids"])
        with self.assertRaises(AccessError):
            self.Assignment.with_user(self.reception).search([])
        self.assertTrue(self.member.with_user(self.manager).gym_pin_assignment_ids)

    # Health data ----------------------------------------------------------

    def test_health_details_are_hidden_from_reception_and_managers(self):
        self.env["gym.member.health"].with_user(self.health_officer).create({
            "partner_id": self.member.id,
            "conditions": "Asthma",
            "show_alert": True,
        })
        for user in (self.reception, self.manager):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    self.env["gym.member.health"].with_user(user).search([])
                with self.assertRaises(AccessError):
                    self.member.with_user(user).read(["gym_health_ids"])

    def test_reception_sees_only_the_alert_flag(self):
        health = self.env["gym.member.health"].with_user(self.health_officer).create({
            "partner_id": self.member.id,
            "conditions": "Diabetes",
            "show_alert": False,
        })
        self.assertFalse(self.member.with_user(self.reception).gym_health_alert)
        health.show_alert = True
        self.assertTrue(self.member.with_user(self.reception).gym_health_alert)
        self.assertTrue(self.Partner.with_user(self.reception).search([
            ("id", "=", self.member.id), ("gym_health_alert", "=", True),
        ]))

    def test_health_officer_reads_health_records(self):
        self.env["gym.member.health"].with_user(self.health_officer).create({
            "partner_id": self.member.id,
            "allergies": "Penicillin",
        })
        self.assertEqual(
            self.member.with_user(self.health_officer).gym_health_ids.allergies, "Penicillin"
        )

    def test_health_changes_are_not_written_to_the_chatter(self):
        self.env["gym.member.health"].with_user(self.health_officer).create({
            "partner_id": self.member.id,
            "conditions": "Epilepsy",
        })
        bodies = " ".join(self.member.message_ids.mapped(lambda m: str(m.body)))
        tracked = self.member.message_ids.tracking_value_ids.mapped(
            lambda t: f"{t.old_value_char} {t.new_value_char}"
        )
        self.assertNotIn("Epilepsy", bodies)
        self.assertNotIn("Epilepsy", " ".join(tracked))
