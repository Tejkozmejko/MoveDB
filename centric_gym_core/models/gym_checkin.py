from datetime import timedelta

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .res_partner import GROUP_MANAGER, GROUP_RECEPTION, PIN_PATTERN, _int_param

PARAM_RETENTION_MONTHS = "centric_gym_core.checkin_retention_months"
DEFAULT_RETENTION_MONTHS = 6
UNDO_MINUTES = 5

DENY_REASONS = [
    ("unknown_code", "Unknown card or PIN"),
    ("not_member", "Not a gym member"),
    ("blocked", "Blocked by the gym"),
    ("waiver_missing", "Waiver not signed"),
    ("no_membership", "No membership"),
    ("not_started", "Membership not started yet"),
    ("expired", "Membership expired"),
    ("suspended", "Membership suspended"),
    ("cancelled", "Membership cancelled"),
    ("already_inside", "Already checked in"),
]


class GymCheckin(models.Model):
    """One visit, or one refused attempt, at a gym location.

    Times are UTC. A visit that nobody closes is closed at its planned
    check-out time, and ``presence_end`` is what contact tracing compares with.
    """

    _name = "gym.checkin"
    _description = "Gym Check-In"
    _order = "check_in desc, id desc"
    _rec_name = "partner_id"

    partner_id = fields.Many2one(
        "res.partner", string="Member", required=True, index=True, ondelete="restrict",
    )
    partner_phone = fields.Char(related="partner_id.phone", string="Phone")
    partner_email = fields.Char(related="partner_id.email", string="Email")
    location_id = fields.Many2one(
        "gym.location", string="Location", required=True, index=True, ondelete="restrict",
    )
    company_id = fields.Many2one(related="location_id.company_id", store=True, index=True)
    check_in = fields.Datetime(required=True, index=True, default=fields.Datetime.now)
    planned_check_out = fields.Datetime(
        string="Expected Check-Out", compute="_compute_planned_check_out", store=True, readonly=False,
    )
    check_out = fields.Datetime(index=True)
    presence_end = fields.Datetime(
        string="Inside Until", compute="_compute_presence_end", store=True, index=True,
        help="The check-out time, or the expected check-out time while the visit is still open.",
    )
    checkout_type = fields.Selection(
        [("manual", "Manual"), ("auto", "Automatic")], string="Check-Out",
    )
    result = fields.Selection(
        [("allowed", "Allowed"), ("override", "Allowed by override"), ("denied", "Denied")],
        required=True, default="allowed", index=True,
    )
    deny_reason = fields.Selection(DENY_REASONS, string="Reason")
    membership_end = fields.Date(string="Membership Ends", help="As it was at check-in.")
    identified_by = fields.Selection(
        [("barcode", "Card"), ("pin", "PIN"), ("search", "Name search")], default="search",
    )
    source = fields.Selection([("reception", "Reception"), ("tablet", "Tablet")], default="reception")
    is_inside = fields.Boolean(compute="_compute_is_inside", search="_search_is_inside")
    duration = fields.Float(string="Hours", compute="_compute_duration", store=True, aggregator="avg")
    hour_of_day = fields.Integer(compute="_compute_local_time", store=True, aggregator=None)
    day_of_week = fields.Selection(
        [("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"), ("3", "Thursday"),
         ("4", "Friday"), ("5", "Saturday"), ("6", "Sunday")],
        compute="_compute_local_time", store=True,
    )
    check_in_user_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    check_out_user_id = fields.Many2one("res.users", readonly=True)
    override_user_id = fields.Many2one("res.users", string="Overridden By", readonly=True)
    override_reason = fields.Char()
    note = fields.Char()

    _check_out_after_check_in = models.Constraint(
        "CHECK(check_out IS NULL OR check_out >= check_in)",
        "The check-out cannot be before the check-in.",
    )
    _one_open_visit = models.UniqueIndex(
        "(partner_id) WHERE check_out IS NULL AND result != 'denied'",
        "This member is already checked in.",
    )

    @api.depends("check_in", "location_id.max_stay_minutes")
    def _compute_planned_check_out(self):
        for visit in self:
            minutes = visit.location_id.max_stay_minutes or 120
            visit.planned_check_out = visit.check_in and visit.check_in + timedelta(minutes=minutes)

    @api.depends("check_out", "planned_check_out", "result", "check_in")
    def _compute_presence_end(self):
        for visit in self:
            if visit.result == "denied":
                visit.presence_end = visit.check_in
            else:
                visit.presence_end = visit.check_out or visit.planned_check_out

    @api.depends("check_in", "presence_end")
    def _compute_duration(self):
        for visit in self:
            if visit.check_in and visit.presence_end:
                visit.duration = (visit.presence_end - visit.check_in).total_seconds() / 3600
            else:
                visit.duration = 0.0

    @api.depends("check_in", "location_id.tz")
    def _compute_local_time(self):
        for visit in self:
            if not visit.check_in:
                visit.hour_of_day, visit.day_of_week = 0, False
                continue
            tz = pytz.timezone(visit.location_id.tz or "UTC")
            local = pytz.utc.localize(visit.check_in).astimezone(tz)
            visit.hour_of_day = local.hour
            visit.day_of_week = str(local.weekday())

    def _compute_is_inside(self):
        now = fields.Datetime.now()
        for visit in self:
            visit.is_inside = bool(
                visit.result != "denied" and not visit.check_out
                and visit.planned_check_out and visit.planned_check_out > now
            )

    def _search_is_inside(self, operator, value):
        if operator != "in":
            return NotImplemented
        inside = [
            ("result", "!=", "denied"),
            ("check_out", "=", False),
            ("planned_check_out", ">", fields.Datetime.now()),
        ]
        if True in value and False in value:
            return []
        if True in value:
            return inside
        return ["!", "&", "&"] + inside

    # ------------------------------------------------------------------
    # Check-in
    # ------------------------------------------------------------------

    @api.model
    def _gym_require(self, group):
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_("You are not allowed to do this in the Gym app."))

    @api.model
    def _gym_reason_label(self, code):
        """Translated label of a refusal reason, including reasons added by other modules."""
        reasons = dict(self._fields["deny_reason"]._description_selection(self.env))
        return reasons.get(code, code or "")

    @api.model
    def _gym_find_member(self, code):
        """(partner, identified_by) for a scanned card or a typed PIN."""
        code = (code or "").strip()
        Partner = self.env["res.partner"].sudo()
        if PIN_PATTERN.fullmatch(code):
            return Partner.search([("gym_pin", "=", code)], limit=1), "pin"
        return Partner.search([("barcode", "=", code), ("gym_member_state", "!=", "none")], limit=1), "barcode"

    @api.model
    def gym_check_in(self, location_id, partner_id=None, code=None, source="reception", identified_by="search"):
        """Check a member in, or record why they were refused.

        Returns the payload the reception screen (and the member tablet) shows.
        """
        self._gym_require(GROUP_RECEPTION)
        location = self.env["gym.location"].browse(location_id).exists()
        if not location:
            raise UserError(_("Choose the gym location first."))
        if code is not None:
            partner, identified_by = self._gym_find_member(code)
            if not partner:
                return {"result": "denied", "reason": "unknown_code",
                        "reason_label": self._gym_reason_label("unknown_code"), "member": False}
        else:
            partner = self.env["res.partner"].sudo().browse(partner_id).exists()
            if not partner:
                raise UserError(_("That member no longer exists."))

        open_visit = self.sudo().search([
            ("partner_id", "=", partner.id), ("check_out", "=", False), ("result", "!=", "denied"),
        ], limit=1)
        if open_visit and open_visit.is_inside:
            return open_visit._gym_payload(result="already_inside")
        if open_visit:
            # Written to the database now: the new visit's insert checks "one open visit".
            open_visit._gym_close("auto")
            open_visit.flush_recordset()

        status = partner._gym_access_status()
        visit = self.sudo().create({
            "partner_id": partner.id,
            "location_id": location.id,
            "result": "allowed" if status["allowed"] else "denied",
            "deny_reason": False if status["allowed"] else status["code"],
            "membership_end": status.get("end") or False,
            "identified_by": identified_by,
            "source": source,
            "check_in_user_id": self.env.uid,
        })
        visit._gym_after_check_in(status)
        return visit._gym_payload(status=status)

    def _gym_after_check_in(self, status):
        """Hook: remember membership details, schedule the automatic check-out, notify displays."""
        if self.result != "denied":
            self.env.ref("centric_gym_core.cron_gym_auto_check_out")._trigger(at=self.planned_check_out)
        self._gym_notify_display()

    def _gym_notify_display(self):
        """Hook for the member-facing tablet (added by the POS module)."""

    def gym_override(self, reason):
        """Let a refused member in anyway. Managers only; the reason is kept."""
        self._gym_require(GROUP_MANAGER)
        self.ensure_one()
        if self.result != "denied":
            raise UserError(_("Only a refused check-in can be overridden."))
        if not (reason or "").strip():
            raise UserError(_("Give a reason for letting this member in."))
        if self.deny_reason in ("unknown_code", "already_inside"):
            raise UserError(_("There is nobody to let in."))
        visit = self.sudo().create({
            "partner_id": self.partner_id.id,
            "location_id": self.location_id.id,
            "result": "override",
            "deny_reason": self.deny_reason,
            "membership_end": self.membership_end,
            "identified_by": self.identified_by,
            "source": self.source,
            "override_user_id": self.env.uid,
            "override_reason": reason.strip(),
            "check_in_user_id": self.env.uid,
        })
        visit._gym_after_check_in({})
        return visit._gym_payload()

    def gym_check_out(self):
        self._gym_require(GROUP_RECEPTION)
        visits = self.sudo().filtered(lambda v: not v.check_out and v.result != "denied")
        visits._gym_close("manual")
        return True

    def gym_undo(self):
        """Remove a check-in made by mistake in the last few minutes."""
        self._gym_require(GROUP_RECEPTION)
        limit = fields.Datetime.now() - timedelta(minutes=UNDO_MINUTES)
        for visit in self.sudo():
            if visit.create_uid != self.env.user or visit.create_date < limit or visit.check_out:
                raise UserError(_("Only your own check-in from the last %(minutes)s minutes can be undone.",
                                  minutes=UNDO_MINUTES))
        self.sudo().unlink()
        return True

    def _gym_close(self, checkout_type):
        now = fields.Datetime.now()
        for visit in self:
            # An automatic check-out happens at the planned time, not when the job ran.
            when = min(now, visit.planned_check_out) if checkout_type == "auto" else now
            visit.write({
                "check_out": max(when, visit.check_in),
                "checkout_type": checkout_type,
                "check_out_user_id": self.env.uid if checkout_type == "manual" else False,
            })

    def _gym_payload(self, status=None, result=None):
        self.ensure_one()
        partner = self.partner_id
        status = status or {}
        reason = "already_inside" if result == "already_inside" else self.deny_reason
        return {
            "result": result or self.result,
            "reason": reason or False,
            "reason_label": self._gym_reason_label(reason) if reason else "",
            "checkin_id": self.id,
            "check_in": fields.Datetime.to_string(self.check_in),
            "planned_check_out": fields.Datetime.to_string(self.planned_check_out),
            "membership_end": fields.Date.to_string(self.membership_end) if self.membership_end else False,
            "membership_label": status.get("label", ""),
            "member": {
                "id": partner.id,
                "name": partner.name,
                "pin": partner.gym_pin,
                "health_alert": partner.gym_health_alert,
                "minor": partner.gym_is_minor,
                "write_date": fields.Datetime.to_string(partner.write_date),
            },
        }

    # ------------------------------------------------------------------
    # Reception screen data
    # ------------------------------------------------------------------

    @api.model
    def gym_reception_data(self, location_id):
        self._gym_require(GROUP_RECEPTION)
        visits = self.sudo().search(
            [("location_id", "=", location_id), ("is_inside", "=", True)], order="check_in desc"
        )
        location = self.env["gym.location"].browse(location_id)
        return {
            "capacity": location.capacity,
            "can_override": self.env.user.has_group(GROUP_MANAGER),
            "inside": [{
                "checkin_id": visit.id,
                "partner_id": visit.partner_id.id,
                "name": visit.partner_id.name,
                "check_in": fields.Datetime.to_string(visit.check_in),
                "planned_check_out": fields.Datetime.to_string(visit.planned_check_out),
                "override": visit.result == "override",
                "health_alert": visit.partner_id.gym_health_alert,
                "write_date": fields.Datetime.to_string(visit.partner_id.write_date),
            } for visit in visits],
        }

    @api.model
    def gym_search_members(self, term):
        self._gym_require(GROUP_RECEPTION)
        term = (term or "").strip()
        if len(term) < 2:
            return []
        members = self.env["res.partner"].sudo().search([
            ("gym_member_state", "in", ("pending", "member")),
            "|", "|", "|",
            ("name", "ilike", term), ("gym_pin", "=", term), ("phone", "ilike", term), ("email", "ilike", term),
        ], limit=12)
        return [{
            "id": member.id,
            "name": member.name,
            "pin": member.gym_pin,
            "state": member.gym_member_state,
            "write_date": fields.Datetime.to_string(member.write_date),
        } for member in members]

    # ------------------------------------------------------------------
    # Scheduled jobs
    # ------------------------------------------------------------------

    @api.model
    def _cron_gym_auto_check_out(self):
        overdue = self.search([
            ("check_out", "=", False),
            ("result", "!=", "denied"),
            ("planned_check_out", "<=", fields.Datetime.now()),
        ])
        overdue._gym_close("auto")

    @api.model
    def _cron_gym_purge_old_checkins(self):
        months = _int_param(self.env, PARAM_RETENTION_MONTHS, DEFAULT_RETENTION_MONTHS)
        if months <= 0:
            return
        cutoff = fields.Datetime.now() - relativedelta(months=months)
        self.search([("check_in", "<", cutoff)]).unlink()

    @api.constrains("result", "deny_reason")
    def _check_deny_reason(self):
        for visit in self:
            if visit.result == "denied" and not visit.deny_reason:
                raise ValidationError(_("A refused check-in needs a reason."))
