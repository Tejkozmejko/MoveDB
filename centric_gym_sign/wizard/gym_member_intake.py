from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import email_normalize

from odoo.addons.centric_gym_core.models.res_partner import (
    DEFAULT_MINOR_AGE,
    GROUP_RECEPTION,
    PARAM_MINOR_AGE,
    _int_param,
)


class GymMemberIntake(models.TransientModel):
    """New Gym Member: details → waiver signature → member with a PIN."""

    _name = "gym.member.intake"
    _description = "New Gym Member"

    step = fields.Selection(
        [("details", "Details"), ("sign", "Waiver"), ("done", "Done")],
        default="details", required=True,
    )
    name = fields.Char(required=True)
    email = fields.Char(help="Odoo Sign emails the waiver, so the signer needs an address.")
    phone = fields.Char()
    birthdate = fields.Date(string="Date of Birth")
    street = fields.Char()
    city = fields.Char()
    zip = fields.Char()
    country_id = fields.Many2one("res.country", default=lambda self: self.env.company.country_id)
    home_location_id = fields.Many2one(
        "gym.location", string="Home Gym",
        default=lambda self: self.env["gym.location"].search([], limit=1),
    )
    emergency_name = fields.Char(string="Emergency Contact")
    emergency_phone = fields.Char(string="Emergency Phone")
    emergency_relation = fields.Char(string="Relationship")
    image_1920 = fields.Image(string="Photo", max_width=1920, max_height=1920)
    is_minor = fields.Boolean(compute="_compute_is_minor")
    guardian_id = fields.Many2one(
        "res.partner", string="Parent / Guardian", domain="[('is_company', '=', False)]",
        help="Signs the waiver for a minor. Leave empty to create one from the fields below.",
    )
    guardian_name = fields.Char(string="Guardian Name")
    guardian_email = fields.Char(string="Guardian Email")
    partner_id = fields.Many2one("res.partner", string="Member", readonly=True)
    agreement_id = fields.Many2one("gym.agreement", string="Waiver", readonly=True)
    agreement_state = fields.Selection(related="agreement_id.state")
    signer_name = fields.Char(related="agreement_id.signer_id.name")
    pin = fields.Char(related="partner_id.gym_pin")

    @api.depends("birthdate")
    def _compute_is_minor(self):
        minor_age = _int_param(self.env, PARAM_MINOR_AGE, DEFAULT_MINOR_AGE)
        today = fields.Date.context_today(self)
        for intake in self:
            intake.is_minor = bool(intake.birthdate) and relativedelta(today, intake.birthdate).years < minor_age

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": _("New Gym Member"),
        }

    def _check_access(self):
        if not self.env.su and not self.env.user.has_group(GROUP_RECEPTION):
            raise UserError(_("Only gym staff can register members."))

    # ------------------------------------------------------------------
    # Step 1: details
    # ------------------------------------------------------------------

    def _guardian(self):
        if not self.is_minor:
            return self.env["res.partner"]
        if self.guardian_id:
            return self.guardian_id
        if not (self.guardian_name and email_normalize(self.guardian_email or "")):
            raise UserError(_("This member is a minor: choose a parent or guardian, or enter their name and email."))
        return self.env["res.partner"].create({
            "name": self.guardian_name,
            "email": email_normalize(self.guardian_email),
        })

    def _existing_partner(self, email):
        Partner = self.env["res.partner"].sudo()
        existing = Partner.search([("email_normalized", "=", email)], limit=1) if email else Partner
        if existing and existing.gym_member_state == "member":
            raise UserError(_(
                "%(name)s (%(email)s) is already a gym member.", name=existing.name, email=existing.email
            ))
        return existing

    def action_send_waiver(self):
        self.ensure_one()
        self._check_access()
        email = email_normalize(self.email or "")
        if self.email and not email:
            raise UserError(_("%(email)s is not a valid email address.", email=self.email))
        if not self.is_minor and not email:
            raise UserError(_("An email address is needed: Odoo Sign emails the waiver to the member."))
        guardian = self._guardian()
        values = {
            "name": self.name,
            "email": email or False,
            "phone": self.phone,
            "street": self.street,
            "city": self.city,
            "zip": self.zip,
            "country_id": self.country_id.id,
            "gym_birthdate": self.birthdate,
            "gym_home_location_id": self.home_location_id.id,
            "gym_emergency_name": self.emergency_name,
            "gym_emergency_phone": self.emergency_phone,
            "gym_emergency_relation": self.emergency_relation,
            "gym_guardian_id": guardian.id,
        }
        if self.image_1920:
            values["image_1920"] = self.image_1920
        partner = self._existing_partner(email)
        if partner:
            partner.write({key: value for key, value in values.items() if value and not partner[key]})
            partner = partner.with_env(self.env)
        else:
            partner = self.env["res.partner"].create({**values, "is_company": False})
        partner._gym_write({"gym_member_state": "pending"})
        agreement = self.env["gym.agreement"]._gym_send(partner, "waiver")
        self.write({"partner_id": partner.id, "agreement_id": agreement.id, "step": "sign"})
        return self._reopen()

    # ------------------------------------------------------------------
    # Step 2: signature
    # ------------------------------------------------------------------

    def action_open_signing(self):
        self.ensure_one()
        return self.agreement_id.action_open_signing()

    def action_check_signature(self):
        self.ensure_one()
        self._check_access()
        self.agreement_id._gym_process_signed()
        if self.agreement_id.sudo().state == "signed":
            self.step = "done"
        elif self.agreement_id.sudo().state != "sent":
            raise UserError(_("The waiver request was cancelled. Close this window and send a new one from the contact."))
        return self._reopen()

    # ------------------------------------------------------------------
    # Step 3: done
    # ------------------------------------------------------------------

    def action_print_card(self):
        self.ensure_one()
        return self.partner_id.action_gym_print_card()

    def action_open_member(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "view_mode": "form",
            "target": "current",
        }
