from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.centric_gym_core.models.res_partner import (
    EASY_PINS,
    PARAM_AUTO_RELEASE,
    PARAM_QUARANTINE_MONTHS,
    PARAM_RELEASE_MONTHS,
    ResPartner,
    gym_card_barcode,
)

from .common import GymCoreCase


@tagged("post_install", "-at_install")
class TestMemberPin(GymCoreCase):

    def limit_pins(self, *pins):
        """Pretend only these PINs exist, so the pool can be filled in a test."""
        return patch.object(ResPartner, "_gym_pin_candidates", lambda self: pins)

    def age_release(self, partner, months):
        """Move the partner's released assignments back in time."""
        self.Assignment.search([("partner_id", "=", partner.id), ("date_released", "!=", False)]).write({
            "date_released": fields.Datetime.now() - relativedelta(months=months),
        })

    # Allocation ---------------------------------------------------------

    def test_new_member_gets_pin_card_and_history(self):
        member = self.make_member()
        self.assertRegex(member.gym_pin, r"^[0-9]{4}$")
        self.assertNotIn(member.gym_pin, EASY_PINS)
        self.assertEqual(member.gym_card_no, 1)
        self.assertEqual(member.barcode, "042" + member.gym_pin.zfill(6) + "01")
        self.assertEqual(member.gym_member_since, fields.Date.context_today(member))
        current = member._gym_current_assignment()
        self.assertEqual((current.pin, current.source, current.card_no), (member.gym_pin, "allocated", 1))

    def test_plain_contact_gets_nothing(self):
        contact = self.Partner.create({"name": "Supplier Person"})
        self.assertEqual(contact.gym_member_state, "none")
        self.assertFalse(contact.gym_pin)
        self.assertFalse(self.Assignment.search([("partner_id", "=", contact.id)]))

    def test_pins_are_unique(self):
        members = self.Partner.create([
            {"name": f"Member {index}", "gym_member_state": "member"} for index in range(40)
        ])
        self.assertEqual(len(set(members.mapped("gym_pin"))), 40)

    def test_pending_contact_has_no_pin_until_member(self):
        contact = self.Partner.create({"name": "New Joiner", "gym_member_state": "pending"})
        self.assertFalse(contact.gym_pin)
        contact.gym_member_state = "member"
        self.assertTrue(contact.gym_pin)

    def test_company_cannot_be_member(self):
        with self.assertRaises(ValidationError):
            self.Partner.create({"name": "Acme", "is_company": True, "gym_member_state": "member"})

    # Explicit and imported PINs ------------------------------------------

    def test_import_keeps_pin_and_restores_leading_zeros(self):
        member = self.Partner.with_context(import_file=True).create({"name": "Legacy", "gym_pin": "42"})
        self.assertEqual(member.gym_pin, "0042")
        self.assertEqual(member.gym_member_state, "member")
        self.assertEqual(member._gym_current_assignment().source, "imported")

    def test_manager_can_set_an_easy_pin_explicitly(self):
        member = self.Partner.create({"name": "Legacy", "gym_pin": "1234"})
        self.assertEqual(member.gym_pin, "1234")
        self.assertEqual(member._gym_current_assignment().source, "manual")

    def test_pin_format_is_enforced(self):
        for bad in ("12a4", "123", "12345", "１２３４"):
            with self.subTest(pin=bad), self.assertRaises(ValidationError):
                self.Partner.create({"name": "Bad", "gym_pin": bad})

    def test_duplicate_pin_is_refused(self):
        first = self.make_member()
        with self.assertRaises(ValidationError):
            self.Partner.create({"name": "Copycat", "gym_pin": first.gym_pin})

    def test_same_pin_twice_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Partner.create([{"name": "A", "gym_pin": "0555"}, {"name": "B", "gym_pin": "0555"}])
        pair = self.make_member(name="C") | self.make_member(name="D")
        with self.assertRaises(ValidationError):
            pair.write({"gym_pin": "0556"})

    def test_changing_pin_closes_the_old_assignment(self):
        member = self.make_member()
        old_pin = member.gym_pin
        new_pin = "0777" if old_pin != "0777" else "0778"
        member.gym_pin = new_pin
        history = member.gym_pin_assignment_ids.sorted("id")
        self.assertEqual(history.mapped("pin"), [old_pin, new_pin])
        self.assertEqual(history[0].release_reason, "replaced")
        self.assertTrue(history[1].is_current)
        self.assertEqual(member.barcode, gym_card_barcode(new_pin, member.gym_card_no))

    # Cards --------------------------------------------------------------

    def test_replacement_card_changes_barcode_not_pin(self):
        member = self.make_member()
        pin, old_barcode = member.gym_pin, member.barcode
        member.action_gym_reissue_card()
        self.assertEqual(member.gym_pin, pin)
        self.assertEqual(member.gym_card_no, 2)
        self.assertNotEqual(member.barcode, old_barcode)
        self.assertEqual(member._gym_current_assignment().card_no, 2)

    def test_card_report_renders(self):
        member = self.make_member(name="Card Holder")
        html, _format = self.env["ir.actions.report"]._render_qweb_html(
            "centric_gym_core.report_gym_member_card", member.ids
        )
        html = html.decode()
        self.assertIn("Card Holder", html)
        self.assertIn(member.gym_pin, html)

    # Release and reuse --------------------------------------------------

    def test_release_clears_pin_and_card(self):
        member = self.make_member()
        pin = member.gym_pin
        member.action_gym_release_pin()
        self.assertFalse(member.gym_pin)
        self.assertFalse(member.barcode)
        self.assertEqual(member.gym_member_state, "former")
        released = self.Assignment.search([("partner_id", "=", member.id)])
        self.assertEqual((released.pin, released.release_reason), (pin, "manual"))
        self.assertTrue(released.date_released)

    def test_ending_membership_releases_pin(self):
        member = self.make_member()
        member.gym_member_state = "former"
        self.assertFalse(member.gym_pin)
        self.assertFalse(member._gym_current_assignment())

    def test_released_pin_waits_before_reuse(self):
        with self.limit_pins("5001", "5002"):
            first = self.make_member(name="First")
            second = self.make_member(name="Second")
            first.action_gym_release_pin()
            with self.assertRaises(UserError):
                self.make_member(name="Third")
            self.age_release(first, 13)
            third = self.make_member(name="Third")
        self.assertEqual(third.gym_pin, self.Assignment.search([("partner_id", "=", first.id)]).pin)
        self.assertNotEqual(third.gym_pin, second.gym_pin)

    def test_reused_pin_never_repeats_a_barcode(self):
        with self.limit_pins("5003"):
            first = self.make_member(name="First")
            first.action_gym_reissue_card()
            old_barcodes = {gym_card_barcode(first.gym_pin, 1), first.barcode}
            first.action_gym_release_pin()
            self.set_param(PARAM_QUARANTINE_MONTHS, "0")
            second = self.make_member(name="Second")
        self.assertEqual(second.gym_card_no, 3)
        self.assertNotIn(second.barcode, old_barcodes)

    def test_returning_member_gets_their_pin_back(self):
        member = self.make_member()
        pin = member.gym_pin
        member.action_gym_release_pin()
        member.action_gym_make_member()
        self.assertEqual(member.gym_pin, pin)
        self.assertEqual(member.gym_card_no, 2)
        self.assertEqual(member.gym_member_state, "member")

    def test_fresh_pins_are_used_before_released_ones(self):
        with self.limit_pins("5004", "5005"):
            first = self.make_member(name="First")
            released_pin = first.gym_pin
            first.action_gym_release_pin()
            self.age_release(first, 24)
            second = self.make_member(name="Second")
        self.assertIn(second.gym_pin, ("5004", "5005"))
        self.assertNotEqual(second.gym_pin, released_pin)

    # Automatic release ---------------------------------------------------

    def test_auto_release_is_off_by_default(self):
        member = self.make_member(gym_member_since=fields.Date.today() - relativedelta(years=3))
        member._gym_current_assignment().date_assigned = fields.Datetime.now() - relativedelta(years=3)
        self.Partner._cron_gym_release_inactive_pins()
        self.assertTrue(member.gym_pin)

    def test_auto_release_takes_back_inactive_pins_only(self):
        self.set_param(PARAM_AUTO_RELEASE, "True")
        self.set_param(PARAM_RELEASE_MONTHS, "12")
        long_ago = fields.Datetime.now() - relativedelta(months=14)
        inactive = self.make_member(name="Gone", gym_member_since=long_ago.date())
        inactive._gym_current_assignment().date_assigned = long_ago
        active = self.make_member(name="Recent", gym_member_since=long_ago.date())
        active._gym_current_assignment().date_assigned = fields.Datetime.now() - timedelta(days=30)

        self.Partner._cron_gym_release_inactive_pins()

        self.assertFalse(inactive.gym_pin)
        self.assertEqual(inactive.gym_member_state, "former")
        self.assertEqual(
            self.Assignment.search([("partner_id", "=", inactive.id)]).release_reason, "inactive"
        )
        self.assertTrue(active.gym_pin)

    # Minors -------------------------------------------------------------

    def test_minor_is_computed_and_searchable(self):
        today = fields.Date.today()
        child = self.make_member(name="Child", gym_birthdate=today - relativedelta(years=12))
        adult = self.make_member(name="Adult", gym_birthdate=today - relativedelta(years=18))
        unknown = self.make_member(name="Unknown")
        self.assertEqual(child.gym_age, 12)
        self.assertTrue(child.gym_is_minor)
        self.assertFalse(adult.gym_is_minor)
        members = child | adult | unknown
        self.assertEqual(members.filtered_domain([("gym_is_minor", "=", True)]), child)
        self.assertEqual(self.Partner.search([("id", "in", members.ids), ("gym_is_minor", "=", True)]), child)
        self.assertEqual(
            self.Partner.search([("id", "in", members.ids), ("gym_is_minor", "=", False)]), adult | unknown
        )
