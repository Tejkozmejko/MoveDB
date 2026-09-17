import re
import secrets

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import str2bool

PIN_LENGTH = 4
PIN_PATTERN = re.compile(r"[0-9]{%d}" % PIN_LENGTH)
ALL_PINS = tuple(str(number).zfill(PIN_LENGTH) for number in range(10 ** PIN_LENGTH))
# Too easy to guess to hand out automatically. A member imported with one keeps it.
EASY_PINS = frozenset(
    [digit * PIN_LENGTH for digit in "0123456789"]
    + [
        "0123", "1234", "2345", "3456", "4567", "5678", "6789",
        "9876", "8765", "7654", "6543", "5432", "4321", "3210",
        "1010", "1122", "1212", "2000", "2580", "0852", "6969",
    ]
)
# Odoo's default barcode nomenclature reads anything starting with 042 as a
# customer, so a member card scanned in the Point of Sale selects the member.
BARCODE_PREFIX = "042"
MAX_CARD_NO = 99
# Any constant; it serialises PIN allocation between concurrent requests.
PIN_LOCK_KEY = 0x67796D50

PARAM_AUTO_RELEASE = "centric_gym_core.pin_auto_release"
PARAM_RELEASE_MONTHS = "centric_gym_core.pin_release_months"
PARAM_QUARANTINE_MONTHS = "centric_gym_core.pin_quarantine_months"
PARAM_MINOR_AGE = "centric_gym_core.minor_age"
DEFAULT_RELEASE_MONTHS = 12
DEFAULT_QUARANTINE_MONTHS = 12
DEFAULT_MINOR_AGE = 18

# Set by the system or a manager, never typed in by reception.
PROTECTED_FIELDS = ("gym_member_state", "gym_pin", "gym_card_no", "gym_access_blocked", "gym_block_reason")

GROUP_RECEPTION = "centric_gym_core.group_gym_reception"
GROUP_MANAGER = "centric_gym_core.group_gym_manager"


def _int_param(env, key, default):
    try:
        return int(env["ir.config_parameter"].sudo().get_param(key, default))
    except (TypeError, ValueError):
        return default


def gym_card_barcode(pin, card_no):
    """042 + the PIN padded to six digits + a two-digit card number."""
    return "%s%s%02d" % (BARCODE_PREFIX, pin.zfill(6), card_no)


class ResPartner(models.Model):
    _inherit = "res.partner"

    gym_member_state = fields.Selection(
        [
            ("none", "Not a member"),
            ("pending", "Waiting for waiver"),
            ("member", "Member"),
            ("former", "Former member"),
        ],
        string="Gym Membership",
        required=True,
        default="none",
        copy=False,
        index=True,
        tracking=True,
    )
    gym_pin = fields.Char(
        string="Member PIN",
        copy=False,
        help="The member types this on the tablet to check in. It is also inside the card barcode.",
    )
    gym_card_no = fields.Integer(string="Card No.", copy=False, readonly=True)
    gym_member_since = fields.Date(string="Member Since", copy=False)
    gym_home_location_id = fields.Many2one(
        "gym.location",
        string="Home Gym",
        index="btree_not_null",
    )
    gym_birthdate = fields.Date(string="Date of Birth")
    gym_age = fields.Integer(string="Age", compute="_compute_gym_age")
    gym_is_minor = fields.Boolean(
        string="Minor",
        compute="_compute_gym_age",
        search="_search_gym_is_minor",
    )
    gym_guardian_id = fields.Many2one(
        "res.partner",
        string="Parent / Guardian",
        index="btree_not_null",
        domain="[('is_company', '=', False)]",
        help="Signs the waiver and membership agreements for a minor.",
    )
    gym_emergency_name = fields.Char(string="Emergency Contact")
    gym_emergency_phone = fields.Char(string="Emergency Phone")
    gym_emergency_relation = fields.Char(string="Relationship")
    gym_health_ids = fields.One2many(
        "gym.member.health",
        "partner_id",
        string="Health Information",
        groups="centric_gym_core.group_gym_health",
    )
    gym_health_alert = fields.Boolean(
        string="Health Alert",
        compute="_compute_gym_health_alert",
        store=True,
        help="Someone in the Gym Health Data group asked reception to be alerted. Ask them for details.",
    )
    gym_pin_assignment_ids = fields.One2many(
        "gym.pin.assignment",
        "partner_id",
        string="PIN History",
        groups="centric_gym_core.group_gym_manager",
    )
    gym_access_blocked = fields.Boolean(
        string="Blocked",
        copy=False,
        tracking=True,
        help="Refuse check-in whatever the membership says.",
    )
    gym_block_reason = fields.Char(string="Block Reason", copy=False)
    gym_checkin_ids = fields.One2many("gym.checkin", "partner_id", string="Check-Ins")
    gym_checkin_count = fields.Integer(string="Visits", compute="_compute_gym_checkin_stats")
    gym_last_checkin = fields.Datetime(string="Last Visit", compute="_compute_gym_checkin_stats")
    gym_is_inside = fields.Boolean(string="Inside Now", compute="_compute_gym_checkin_stats")

    _gym_pin_uniq = models.UniqueIndex(
        "(gym_pin) WHERE gym_pin IS NOT NULL",
        "Another member already has this PIN.",
    )

    # ------------------------------------------------------------------
    # Computes and constraints
    # ------------------------------------------------------------------

    @api.depends("gym_birthdate")
    def _compute_gym_age(self):
        today = fields.Date.context_today(self)
        minor_age = _int_param(self.env, PARAM_MINOR_AGE, DEFAULT_MINOR_AGE)
        for partner in self:
            age = relativedelta(today, partner.gym_birthdate).years if partner.gym_birthdate else 0
            partner.gym_age = age
            partner.gym_is_minor = bool(partner.gym_birthdate) and age < minor_age

    def _search_gym_is_minor(self, operator, value):
        if operator != "in":
            return NotImplemented
        minor_age = _int_param(self.env, PARAM_MINOR_AGE, DEFAULT_MINOR_AGE)
        cutoff = fields.Date.context_today(self) - relativedelta(years=minor_age)
        minors = [("gym_birthdate", ">", cutoff)]
        adults = ["|", ("gym_birthdate", "=", False), ("gym_birthdate", "<=", cutoff)]
        if True in value and False in value:
            return []
        return minors if True in value else adults

    @api.depends("gym_health_ids.show_alert")
    def _compute_gym_health_alert(self):
        for partner in self:
            # Reception never has access to the health records themselves.
            partner.gym_health_alert = any(partner.sudo().gym_health_ids.mapped("show_alert"))

    def _compute_gym_checkin_stats(self):
        Checkin = self.env["gym.checkin"].sudo()
        visits = dict(Checkin._read_group(
            [("partner_id", "in", self.ids), ("result", "!=", "denied")],
            ["partner_id"], ["check_in:max"],
        ))
        counts = dict(Checkin._read_group(
            [("partner_id", "in", self.ids), ("result", "!=", "denied")], ["partner_id"], ["__count"],
        ))
        inside = Checkin.search([("partner_id", "in", self.ids), ("is_inside", "=", True)]).partner_id
        for partner in self:
            key = partner._origin
            partner.gym_last_checkin = visits.get(key, False)
            partner.gym_checkin_count = counts.get(key, 0)
            partner.gym_is_inside = key in inside

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def _gym_access_status(self):
        """May this member come in right now?

        Returns ``{"allowed", "code", "label", "end"}``. ``code`` is one of the
        check-in refusal reasons, or ``active`` when allowed.
        """
        self.ensure_one()
        if self.gym_member_state == "pending":
            return self._gym_refuse("waiver_missing")
        if self.gym_member_state != "member":
            return self._gym_refuse("not_member")
        if self.gym_access_blocked:
            return self._gym_refuse("blocked", self.gym_block_reason)
        membership = self._gym_membership_status()
        if membership["code"] != "active":
            refusal = self._gym_refuse(membership["code"])
            return {**membership, **refusal, "end": membership.get("end") or False}
        return {**membership, "allowed": True, "label": membership.get("label") or _("Active")}

    def _gym_refuse(self, code, detail=None):
        from .gym_checkin import DENY_REASONS
        label = dict(DENY_REASONS).get(code, code)
        return {"allowed": False, "code": code, "label": f"{label}: {detail}" if detail else label, "end": False}

    def _gym_membership_status(self):
        """The member's membership right now: ``{"code", "label", "end"}``.

        ``code`` is active, no_membership, not_started, expired, suspended or
        cancelled. Memberships live in Subscriptions, which the Gym Membership
        module reads; without it nobody has a membership.
        """
        self.ensure_one()
        return {"code": "no_membership", "label": _("No membership"), "end": False}

    @api.constrains("gym_pin")
    def _check_gym_pin(self):
        for partner in self.filtered("gym_pin"):
            if not PIN_PATTERN.fullmatch(partner.gym_pin):
                raise ValidationError(_(
                    "A member PIN is exactly %(length)s digits, for example 0427.",
                    length=PIN_LENGTH,
                ))

    def _gym_check_pins_free(self, pins):
        """Refuse PINs someone else holds, before the unique index does it less politely."""
        pins = [pin for pin in pins if pin]
        if not pins:
            return
        if len(pins) != len(set(pins)):
            raise ValidationError(_("The same PIN cannot be given to more than one member."))
        holder = self.sudo().with_context(active_test=False).search(
            [("gym_pin", "in", pins), ("id", "not in", self.ids)], limit=1
        )
        if holder:
            raise ValidationError(_(
                "PIN %(pin)s already belongs to %(member)s.",
                pin=holder.gym_pin,
                member=holder.display_name,
            ))

    @api.constrains("gym_member_state", "is_company")
    def _check_gym_member_is_person(self):
        for partner in self:
            if partner.is_company and partner.gym_member_state != "none":
                raise ValidationError(_("A company cannot be a gym member; add the person as a contact instead."))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get("gym_pin_sync"):
            return super().create(vals_list)
        for vals in vals_list:
            self._gym_check_protected_write(vals, creating=True)
            self._gym_normalize_pin(vals)
        self._gym_check_pins_free([vals.get("gym_pin") for vals in vals_list])
        partners = super().create(vals_list)
        for partner, vals in zip(partners, vals_list):
            if vals.get("gym_pin") or vals.get("gym_member_state") == "member":
                partner._gym_sync_pin(vals)
        return partners

    def write(self, vals):
        if self.env.context.get("gym_pin_sync"):
            return super().write(vals)
        self._gym_check_protected_write(vals)
        self._gym_normalize_pin(vals)
        if vals.get("gym_pin"):
            self._gym_check_pins_free([vals["gym_pin"]] * len(self))
        result = super().write(vals)
        if "gym_pin" in vals or "gym_member_state" in vals:
            self._gym_sync_pin(vals)
        return result

    def _gym_check_protected_write(self, vals, creating=False):
        if self.env.su or self.env.user.has_group(GROUP_MANAGER):
            return
        touched = [name for name in PROTECTED_FIELDS if name in vals]
        if creating:
            # The form sends the defaults along with a new contact.
            touched = [name for name in touched if vals[name] and vals[name] != "none"]
        if touched:
            raise AccessError(_("Only a gym manager can change a member's PIN, card or membership state."))

    def _gym_normalize_pin(self, vals):
        if "gym_pin" not in vals:
            return
        pin = (vals["gym_pin"] or "").strip()
        if pin and self.env.context.get("import_file") and pin.isascii() and pin.isdigit():
            # Spreadsheets drop leading zeros: 0427 comes back as 427.
            pin = pin.zfill(PIN_LENGTH)
        vals["gym_pin"] = pin or False

    def _gym_write(self, vals):
        """Write system-managed fields, bypassing the manager-only guard."""
        return self.sudo().with_context(gym_pin_sync=True).write(vals)

    # ------------------------------------------------------------------
    # PIN life cycle
    # ------------------------------------------------------------------

    def _gym_current_assignment(self):
        self.ensure_one()
        return self.env["gym.pin.assignment"].sudo().search(
            [("partner_id", "=", self.id), ("date_released", "=", False)], limit=1
        )

    def _gym_sync_pin(self, vals):
        """Bring PIN, card, barcode and PIN history in line with a create/write."""
        explicit_pin = "gym_pin" in vals
        source = "imported" if self.env.context.get("import_file") else "manual"
        for partner in self.sudo():
            current = partner._gym_current_assignment()
            if partner.gym_member_state != "member":
                if explicit_pin and partner.gym_pin and "gym_member_state" not in vals:
                    # A PIN only belongs on a member, so giving one makes them one.
                    partner._gym_write({"gym_member_state": "member"})
                elif partner.gym_pin or current:
                    partner._gym_release_pin("manual")
                    continue
                else:
                    continue
            if not partner.gym_member_since:
                partner._gym_write({"gym_member_since": fields.Date.context_today(partner)})
            if partner.gym_pin:
                if current.pin == partner.gym_pin:
                    continue
                if current:
                    current.write({
                        "date_released": fields.Datetime.now(),
                        "release_reason": "replaced",
                        "released_by_id": self.env.uid,
                    })
                partner._gym_open_assignment(partner.gym_pin, source)
            elif explicit_pin and current:
                # A manager cleared the PIN on a member.
                partner._gym_release_pin("manual")
            else:
                if current:
                    current.write({"date_released": fields.Datetime.now(), "release_reason": "replaced"})
                partner._gym_open_assignment(partner._gym_allocate_pin(), "allocated")

    def _gym_open_assignment(self, pin, source):
        self.ensure_one()
        Assignment = self.env["gym.pin.assignment"].sudo()
        holder = Assignment.search([("pin", "=", pin), ("date_released", "=", False)], limit=1).partner_id
        if holder and holder != self:
            raise ValidationError(_(
                "PIN %(pin)s already belongs to %(member)s.", pin=pin, member=holder.display_name
            ))
        card_no = self._gym_next_card_no(pin)
        Assignment.create({
            "pin": pin,
            "partner_id": self.id,
            "source": source,
            "card_no": card_no,
        })
        self._gym_write({
            "gym_pin": pin,
            "gym_card_no": card_no,
            "barcode": gym_card_barcode(pin, card_no),
        })

    def _gym_next_card_no(self, pin):
        """Card numbers carry on across everyone who ever held the PIN.

        That is what stops a card printed for an earlier holder of a reused PIN
        from matching the new holder's barcode.
        """
        [(last,)] = self.env["gym.pin.assignment"].sudo()._read_group(
            [("pin", "=", pin)], [], ["card_no:max"]
        )
        last = last or 0
        if last >= MAX_CARD_NO:
            raise UserError(_(
                "PIN %(pin)s has run out of card numbers. Give this member a different PIN.",
                pin=pin,
            ))
        return last + 1

    def _gym_pin_candidates(self):
        return ALL_PINS

    def _gym_allocate_pin(self):
        """Pick a PIN for this member.

        In order of preference: the member's own previous PIN if nobody holds it,
        a PIN nobody ever held, then the PIN released longest ago once its
        waiting period is over.
        """
        self.ensure_one()
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [PIN_LOCK_KEY])
        Assignment = self.env["gym.pin.assignment"].sudo()
        held = {pin for (pin,) in Assignment._read_group([("date_released", "=", False)], ["pin"])}
        held |= {
            pin for (pin,) in self.sudo().with_context(active_test=False)._read_group(
                [("gym_pin", "!=", False)], ["gym_pin"]
            )
        }
        own_previous = Assignment.search(
            [("partner_id", "=", self.id), ("date_released", "!=", False)],
            order="date_released desc",
        ).mapped("pin")
        for pin in own_previous:
            if pin not in held:
                return pin

        released = dict(Assignment._read_group(
            [("date_released", "!=", False)], ["pin"], ["date_released:max"]
        ))
        candidates = [
            pin for pin in self._gym_pin_candidates()
            if pin not in held and pin not in EASY_PINS
        ]
        fresh = [pin for pin in candidates if pin not in released]
        if fresh:
            return secrets.choice(fresh)

        quarantine = _int_param(self.env, PARAM_QUARANTINE_MONTHS, DEFAULT_QUARANTINE_MONTHS)
        cutoff = fields.Datetime.now() - relativedelta(months=quarantine)
        reusable = sorted(
            (released[pin], pin) for pin in candidates
            if pin in released and released[pin] <= cutoff
        )
        if reusable:
            return reusable[0][1]
        raise UserError(_(
            "No member PIN is free: every PIN is either in use or still in its waiting "
            "period before reuse. Release PINs of inactive members or shorten the waiting "
            "period in Gym settings."
        ))

    def _gym_release_pin(self, reason):
        now = fields.Datetime.now()
        for partner in self.sudo():
            current = partner._gym_current_assignment()
            current.write({
                "date_released": now,
                "release_reason": reason,
                "released_by_id": self.env.uid,
            })
            vals = {"gym_pin": False, "gym_card_no": 0}
            if partner.gym_pin and partner.barcode == gym_card_barcode(partner.gym_pin, partner.gym_card_no):
                vals["barcode"] = False
            if partner.gym_member_state == "member":
                vals["gym_member_state"] = "former"
            partner._gym_write(vals)
            partner.message_post(body=_(
                "Member PIN released (%(reason)s). The membership card no longer works.",
                reason=dict(current._fields["release_reason"].selection).get(reason, reason),
            ))

    def _gym_last_activity_date(self):
        """The last day this member did something that should keep their PIN.

        The Gym Membership module adds the membership end date.
        """
        self.ensure_one()
        assigned = self._gym_current_assignment().date_assigned
        last_visit = self.sudo().gym_last_checkin
        dates = [day for day in (
            self.gym_member_since,
            assigned and assigned.date(),
            last_visit and last_visit.date(),
        ) if day]
        return max(dates) if dates else fields.Date.context_today(self)

    @api.model
    def _cron_gym_release_inactive_pins(self):
        params = self.env["ir.config_parameter"].sudo()
        if not str2bool(params.get_param(PARAM_AUTO_RELEASE, "False")):
            return
        months = _int_param(self.env, PARAM_RELEASE_MONTHS, DEFAULT_RELEASE_MONTHS)
        if months <= 0:
            return
        cutoff = fields.Date.context_today(self) - relativedelta(months=months)
        holders = self.sudo().with_context(active_test=False).search([("gym_pin", "!=", False)])
        holders.filtered(lambda p: p._gym_last_activity_date() < cutoff)._gym_release_pin("inactive")

    @api.model
    def _gym_pin_usage(self):
        """(PINs held, PINs that can be handed out in total)."""
        held = self.sudo().with_context(active_test=False).search_count([("gym_pin", "!=", False)])
        return held, len(set(self._gym_pin_candidates()) - EASY_PINS)

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _gym_require_group(self, group):
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_("You are not allowed to do this in the Gym app."))

    def action_gym_make_member(self):
        self._gym_require_group(GROUP_MANAGER)
        self.filtered(lambda p: p.gym_member_state != "member").write({"gym_member_state": "member"})
        return True

    def action_gym_release_pin(self):
        self._gym_require_group(GROUP_MANAGER)
        self.filtered("gym_pin")._gym_release_pin("manual")
        return True

    def action_gym_reissue_card(self):
        self._gym_require_group(GROUP_RECEPTION)
        for partner in self:
            if not partner.gym_pin:
                raise UserError(_("%(member)s has no member PIN yet.", member=partner.display_name))
            card_no = partner._gym_next_card_no(partner.gym_pin)
            partner._gym_current_assignment().write({"card_no": card_no})
            partner._gym_write({
                "gym_card_no": card_no,
                "barcode": gym_card_barcode(partner.gym_pin, card_no),
            })
            partner.message_post(body=_(
                "Replacement card No. %(card_no)s issued. Earlier cards no longer work.",
                card_no=card_no,
            ))
        return self.action_gym_print_card()

    def action_gym_view_checkins(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("centric_gym_core.action_gym_checkins")
        action["domain"] = [("partner_id", "=", self.id)]
        action["context"] = {"search_default_filter_visits": 1}
        return action

    def action_gym_print_card(self):
        self._gym_require_group(GROUP_RECEPTION)
        members = self.filtered("gym_pin")
        if not members:
            raise UserError(_("Only a member with a PIN has a card to print."))
        return self.env.ref("centric_gym_core.action_report_gym_member_card").report_action(members)
