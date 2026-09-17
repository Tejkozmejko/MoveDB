from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.centric_gym_core.models.res_partner import ResPartner

from .common import GymCoreCase


@contextmanager
def memberships(*active_partners, code="active"):
    """Pretend the given members hold a membership (core alone has none)."""
    ids = {partner.id for partner in active_partners}

    def status(self):
        if self.id in ids:
            return {"code": code, "label": "Test membership", "end": fields.Date.today() + timedelta(days=30)}
        return {"code": "no_membership", "label": "No membership", "end": False}

    with patch.object(ResPartner, "_gym_membership_status", status):
        yield


@tagged("post_install", "-at_install")
class TestCheckin(GymCoreCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Checkin = cls.env["gym.checkin"]
        cls.location = cls.env["gym.location"].create({"name": "Test Bugibba", "code": "ZZTEST1", "tz": "Europe/Malta"})
        cls.other_location = cls.env["gym.location"].create({"name": "Test Sliema", "code": "ZZTEST2", "max_stay_minutes": 90})
        cls.member = cls.env["res.partner"].create({"name": "Anna Vella", "gym_member_state": "member"})

    def check_in(self, user=None, **kwargs):
        return self.Checkin.with_user(user or self.reception).gym_check_in(self.location.id, **kwargs)

    def visits(self, partner=None):
        return self.Checkin.search([("partner_id", "=", (partner or self.member).id)])

    # Checking in ---------------------------------------------------------

    def test_card_scan_checks_an_active_member_in(self):
        with memberships(self.member):
            card = self.check_in(code=self.member.barcode)
        visit = self.visits()
        self.assertEqual(card["result"], "allowed")
        self.assertEqual(card["member"]["name"], "Anna Vella")
        self.assertEqual(card["membership_label"], "Test membership")
        self.assertEqual((visit.result, visit.identified_by, visit.source), ("allowed", "barcode", "reception"))
        self.assertEqual(visit.planned_check_out - visit.check_in, timedelta(minutes=120))
        self.assertTrue(visit.is_inside)
        self.assertEqual(visit.check_in_user_id, self.reception)
        self.member.invalidate_recordset(["gym_is_inside", "gym_checkin_count"])
        self.assertTrue(self.member.gym_is_inside)
        self.assertEqual(self.member.gym_checkin_count, 1)

    def test_check_in_schedules_the_automatic_check_out(self):
        cron = self.env.ref("centric_gym_core.cron_gym_auto_check_out")
        with memberships(self.member):
            self.check_in(partner_id=self.member.id)
        trigger = self.env["ir.cron.trigger"].search([("cron_id", "=", cron.id)], order="id desc", limit=1)
        self.assertEqual(trigger.call_at, self.visits().planned_check_out)

    def test_pin_identifies_the_member(self):
        with memberships(self.member):
            card = self.check_in(code=self.member.gym_pin)
        self.assertEqual(card["result"], "allowed")
        self.assertEqual(self.visits().identified_by, "pin")

    def test_max_stay_comes_from_the_location(self):
        with memberships(self.member):
            self.Checkin.with_user(self.reception).gym_check_in(self.other_location.id, partner_id=self.member.id)
        visit = self.visits()
        self.assertEqual(visit.planned_check_out - visit.check_in, timedelta(minutes=90))

    def test_unknown_code_is_refused_without_a_record(self):
        count = self.Checkin.search_count([])
        card = self.check_in(code="04299999901")
        self.assertEqual((card["result"], card["reason"]), ("denied", "unknown_code"))
        self.assertFalse(card["member"])
        self.assertEqual(self.Checkin.search_count([]), count)

    def test_refusals_are_recorded_with_their_reason(self):
        pending = self.Partner.create({"name": "New Joiner", "gym_member_state": "pending"})
        former = self.Partner.create({"name": "Old Member", "gym_member_state": "former"})
        blocked = self.Partner.create({"name": "Banned", "gym_member_state": "member",
                                       "gym_access_blocked": True, "gym_block_reason": "Unpaid damage"})
        suspended = self.Partner.create({"name": "Paused", "gym_member_state": "member"})
        cases = [
            (self.member, "no_membership"),
            (pending, "waiver_missing"),
            (former, "not_member"),
            (blocked, "blocked"),
        ]
        with memberships(blocked):
            for partner, reason in cases:
                with self.subTest(reason=reason):
                    card = self.check_in(partner_id=partner.id)
                    visit = self.visits(partner)
                    self.assertEqual((card["result"], card["reason"]), ("denied", reason))
                    self.assertEqual((visit.result, visit.deny_reason), ("denied", reason))
                    self.assertFalse(visit.is_inside)
                    self.assertEqual(visit.presence_end, visit.check_in)
        with memberships(suspended, code="suspended"):
            card = self.check_in(partner_id=suspended.id)
        self.assertEqual(card["reason"], "suspended")
        self.assertIn("Unpaid damage", blocked._gym_access_status()["label"])

    def test_second_scan_while_inside_does_not_check_in_again(self):
        with memberships(self.member):
            first = self.check_in(partner_id=self.member.id)
            second = self.check_in(code=self.member.barcode)
        self.assertEqual(second["result"], "already_inside")
        self.assertEqual(second["checkin_id"], first["checkin_id"])
        self.assertEqual(len(self.visits()), 1)

    def test_forgotten_visit_is_closed_when_the_member_comes_back(self):
        with memberships(self.member):
            self.check_in(partner_id=self.member.id)
            old = self.visits()
            old.write({"check_in": datetime.now() - timedelta(hours=5)})
            card = self.check_in(partner_id=self.member.id)
        self.assertEqual(card["result"], "allowed")
        self.assertEqual(old.checkout_type, "auto")
        self.assertEqual(old.check_out, old.planned_check_out)
        self.assertEqual(len(self.visits()), 2)

    # Overrides, check-out, undo --------------------------------------------

    def test_manager_override_lets_a_refused_member_in(self):
        card = self.check_in(partner_id=self.member.id)
        refused = self.Checkin.browse(card["checkin_id"])
        with self.assertRaises(AccessError):
            refused.with_user(self.reception).gym_override("Paying now")
        with self.assertRaises(UserError):
            refused.with_user(self.manager).gym_override("  ")
        card = refused.with_user(self.manager).gym_override("Paying now")
        override = self.Checkin.browse(card["checkin_id"])
        self.assertEqual(card["result"], "override")
        self.assertEqual((override.override_user_id, override.override_reason), (self.manager, "Paying now"))
        self.assertEqual(override.deny_reason, "no_membership")
        self.assertTrue(override.is_inside)
        self.assertEqual(refused.result, "denied")

    def test_manual_check_out(self):
        with memberships(self.member):
            card = self.check_in(partner_id=self.member.id)
        visit = self.Checkin.browse(card["checkin_id"])
        visit.with_user(self.reception).gym_check_out()
        self.assertTrue(visit.check_out)
        self.assertEqual((visit.checkout_type, visit.check_out_user_id), ("manual", self.reception))
        self.assertFalse(visit.is_inside)
        self.assertFalse(self.Checkin.with_user(self.reception).gym_reception_data(self.location.id)["inside"])

    def test_automatic_check_out_uses_the_planned_time(self):
        with memberships(self.member):
            card = self.check_in(partner_id=self.member.id)
        visit = self.Checkin.browse(card["checkin_id"])
        visit.write({"check_in": datetime.now() - timedelta(hours=3)})
        self.assertFalse(visit.is_inside)
        self.Checkin._cron_gym_auto_check_out()
        self.assertEqual(visit.checkout_type, "auto")
        self.assertEqual(visit.check_out, visit.planned_check_out)
        self.assertAlmostEqual(visit.duration, 2.0)

    def test_undo_is_for_your_own_recent_check_in(self):
        with memberships(self.member):
            card = self.check_in(partner_id=self.member.id)
        visit = self.Checkin.browse(card["checkin_id"])
        other = self.env["res.users"].create({
            "name": "Other Desk", "login": "gym_other_desk",
            "group_ids": [(6, 0, [self.env.ref("centric_gym_core.group_gym_reception").id])],
        })
        with self.assertRaises(UserError):
            visit.with_user(other).gym_undo()
        visit.with_user(self.reception).gym_undo()
        self.assertFalse(visit.exists())

    def test_reception_cannot_edit_or_delete_check_ins(self):
        with memberships(self.member):
            card = self.check_in(partner_id=self.member.id)
        visit = self.Checkin.with_user(self.reception).browse(card["checkin_id"])
        with self.assertRaises(AccessError):
            visit.write({"note": "changed"})
        with self.assertRaises(AccessError):
            visit.unlink()

    # Reception data ----------------------------------------------------------

    def test_reception_data_and_member_search(self):
        with memberships(self.member):
            self.check_in(partner_id=self.member.id)
        data = self.Checkin.with_user(self.reception).gym_reception_data(self.location.id)
        self.assertEqual([row["name"] for row in data["inside"]], ["Anna Vella"])
        self.assertFalse(data["can_override"])
        self.assertTrue(self.Checkin.with_user(self.manager).gym_reception_data(self.location.id)["can_override"])
        search = self.Checkin.with_user(self.reception).gym_search_members
        self.assertEqual([m["id"] for m in search("anna")], [self.member.id])
        self.assertEqual([m["id"] for m in search(self.member.gym_pin)], [self.member.id])
        self.assertEqual(search("a"), [])

    def test_local_time_follows_the_location(self):
        visit = self.Checkin.create({
            "partner_id": self.member.id,
            "location_id": self.location.id,
            "check_in": datetime(2026, 7, 6, 12, 30),  # a Monday, 14:30 in Malta (UTC+2)
            "check_out": datetime(2026, 7, 6, 13, 0),
        })
        self.assertEqual((visit.hour_of_day, visit.day_of_week), (14, "0"))

    # Contact tracing and retention ------------------------------------------

    def test_who_was_inside(self):
        other = self.Partner.create({"name": "Mark Borg", "gym_member_state": "member"})
        refused = self.Partner.create({"name": "No Pass", "gym_member_state": "member"})
        base = datetime(2026, 9, 10, 12, 0)  # 12:00 UTC
        create = self.Checkin.create
        auto_visit = create({"partner_id": self.member.id, "location_id": self.location.id,
                             "check_in": base, "check_out": base + timedelta(hours=2), "checkout_type": "auto"})
        create({"partner_id": other.id, "location_id": self.location.id,
                "check_in": base + timedelta(hours=3), "check_out": base + timedelta(hours=4)})
        create({"partner_id": refused.id, "location_id": self.location.id, "check_in": base + timedelta(hours=1),
                "result": "denied", "deny_reason": "no_membership"})
        elsewhere = create({"partner_id": other.id, "location_id": self.other_location.id,
                            "check_in": base, "check_out": base + timedelta(hours=1)})

        def inside(start, end, location=None):
            report = self.env["gym.presence.report"].with_user(self.manager).create({
                "date_from": start, "date_to": end, "location_id": location and location.id,
            })
            return self.Checkin.search(report._presence_domain())

        self.assertEqual(inside(base + timedelta(hours=1), base + timedelta(minutes=90), self.location), auto_visit)
        self.assertFalse(inside(base + timedelta(hours=2, minutes=10), base + timedelta(hours=2, minutes=50),
                                self.location))
        self.assertEqual(inside(base + timedelta(minutes=30), base + timedelta(minutes=45)), auto_visit | elsewhere)
        action = self.env["gym.presence.report"].with_user(self.manager).create({
            "date_from": base, "date_to": base + timedelta(hours=1),
        }).action_show()
        self.assertEqual(action["res_model"], "gym.checkin")

    def test_old_check_ins_are_deleted_after_the_retention_period(self):
        create = self.Checkin.create
        old = create({"partner_id": self.member.id, "location_id": self.location.id,
                      "check_in": datetime.now() - relativedelta(months=7),
                      "check_out": datetime.now() - relativedelta(months=7) + timedelta(hours=1)})
        recent = create({"partner_id": self.member.id, "location_id": self.location.id,
                         "check_in": datetime.now() - relativedelta(months=5),
                         "check_out": datetime.now() - relativedelta(months=5) + timedelta(hours=1)})
        self.set_param("centric_gym_core.checkin_retention_months", "0")
        self.Checkin._cron_gym_purge_old_checkins()
        self.assertTrue(old.exists())
        self.set_param("centric_gym_core.checkin_retention_months", "6")
        self.Checkin._cron_gym_purge_old_checkins()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_recent_visit_keeps_the_pin(self):
        self.set_param("centric_gym_core.pin_auto_release", "True")
        long_ago = fields.Datetime.now() - relativedelta(months=14)
        self.member.gym_member_since = long_ago.date()
        self.member._gym_current_assignment().date_assigned = long_ago
        self.Checkin.create({"partner_id": self.member.id, "location_id": self.location.id,
                             "check_in": datetime.now() - timedelta(days=3),
                             "check_out": datetime.now() - timedelta(days=3, hours=-1)})
        self.Partner._cron_gym_release_inactive_pins()
        self.assertTrue(self.member.gym_pin)
