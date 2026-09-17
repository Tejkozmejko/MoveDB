from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.centric_gym_core.models.res_partner import GROUP_RECEPTION

WAIVER_STATES = [
    ("signed", "Signed"),
    ("outdated", "New version to sign"),
    ("pending", "Waiting for signature"),
    ("missing", "Not signed"),
    ("not_required", "Not required"),
]


class ResPartner(models.Model):
    _inherit = "res.partner"

    gym_agreement_ids = fields.One2many("gym.agreement", "partner_id", string="Agreements")
    gym_agreement_count = fields.Integer(string="Agreements", compute="_compute_gym_waiver")
    gym_waiver_state = fields.Selection(WAIVER_STATES, string="Waiver", compute="_compute_gym_waiver")
    gym_paper_waiver_version = fields.Char(
        string="Paper Waiver Version",
        copy=False,
        help="Version of the waiver this member signed on paper (e.g. members imported from the old "
             "system). It counts as signed while it matches the current waiver version.",
    )

    def _gym_protected_fields(self):
        return super()._gym_protected_fields() + ("gym_paper_waiver_version",)

    def _compute_gym_waiver(self):
        for partner in self:
            origin = partner._origin
            partner.gym_waiver_state = origin._gym_waiver_status() if origin else "missing"
            partner.gym_agreement_count = len(origin.sudo().gym_agreement_ids) if origin else 0

    def _gym_waiver_status(self):
        self.ensure_one()
        template = self.env["gym.agreement.template"]._gym_current("waiver", self.company_id or None)
        if not template:
            return "not_required"
        if self.gym_paper_waiver_version and self.gym_paper_waiver_version == template.version:
            return "signed"
        waivers = self.sudo().gym_agreement_ids.filtered(lambda a: a.agreement_type == "waiver")
        if waivers.filtered(lambda a: a.state == "signed" and a.template_id == template):
            return "signed"
        if waivers.filtered(lambda a: a.state == "sent" and a.template_id == template):
            return "pending"
        if waivers.filtered(lambda a: a.state == "signed") or self.gym_paper_waiver_version:
            return "outdated"
        return "missing"

    def _gym_access_status(self):
        status = super()._gym_access_status()
        if not status["allowed"]:
            return status
        waiver = self._gym_waiver_status()
        if waiver in ("signed", "not_required"):
            return status
        code = "waiver_outdated" if waiver == "outdated" else "waiver_missing"
        return {**status, **self._gym_refuse(code)}

    def _gym_signer(self):
        """Who signs for this member: the member, or a minor's parent or guardian."""
        self.ensure_one()
        if self.gym_is_minor:
            if not self.gym_guardian_id:
                raise UserError(_("%(member)s is a minor: add a parent or guardian first.", member=self.name))
            return self.gym_guardian_id
        return self

    def action_gym_send_waiver(self):
        self._gym_require_group(GROUP_RECEPTION)
        self.ensure_one()
        agreement = self.env["gym.agreement"]._gym_send(self, "waiver")
        if self.gym_member_state in ("none", "former"):
            self._gym_write({"gym_member_state": "pending"})
        return agreement.action_open_signing()

    def action_gym_view_agreements(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("centric_gym_sign.action_gym_agreements")
        action["domain"] = [("partner_id", "=", self.id)]
        action["context"] = {}
        return action
