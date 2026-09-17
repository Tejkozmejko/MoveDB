from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.centric_gym_core.models.res_partner import GROUP_MANAGER, GROUP_RECEPTION

from .gym_agreement_template import AGREEMENT_TYPES


class GymAgreement(models.Model):
    """A gym document sent to a member for signature, and what became of it."""

    _name = "gym.agreement"
    _description = "Gym Agreement"
    _inherit = ["mail.thread"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="Reference", required=True, readonly=True, copy=False, default="/")
    partner_id = fields.Many2one("res.partner", string="Member", required=True, index=True, ondelete="restrict")
    signer_id = fields.Many2one(
        "res.partner", string="Signed By", required=True, ondelete="restrict",
        help="The member, or a minor's parent or guardian.",
    )
    template_id = fields.Many2one("gym.agreement.template", required=True, ondelete="restrict", index=True)
    agreement_type = fields.Selection(AGREEMENT_TYPES, related="template_id.agreement_type", store=True)
    version = fields.Char(required=True, readonly=True)
    company_id = fields.Many2one(related="template_id.company_id", store=True, index=True)
    sign_request_id = fields.Many2one("sign.request", string="Sign Request", readonly=True, ondelete="set null")
    sign_state = fields.Selection(related="sign_request_id.state", store=True, string="Sign Status")
    voided = fields.Boolean(readonly=True, tracking=True, copy=False)
    void_reason = fields.Char(readonly=True, tracking=True, copy=False)
    state = fields.Selection(
        [("sent", "Waiting for signature"), ("signed", "Signed"), ("cancelled", "Cancelled"), ("void", "Void")],
        compute="_compute_state", store=True, index=True, tracking=True,
    )
    signed_on = fields.Datetime(compute="_compute_signed_on", store=True)
    processed = fields.Boolean(
        readonly=True, copy=False,
        help="What follows a signature (e.g. the contact becoming a member) has been done.",
    )
    signing_url = fields.Char(compute="_compute_signing_url")
    document_count = fields.Integer(compute="_compute_document_count")

    @api.depends("sign_state", "voided", "sign_request_id")
    def _compute_state(self):
        for agreement in self:
            if agreement.voided:
                agreement.state = "void"
            elif agreement.sign_state == "signed":
                agreement.state = "signed"
            elif not agreement.sign_request_id or agreement.sign_state in ("canceled", "expired"):
                agreement.state = "cancelled"
            else:
                agreement.state = "sent"

    @api.depends("sign_state")
    def _compute_signed_on(self):
        for agreement in self:
            if agreement.sign_state != "signed":
                agreement.signed_on = False
                continue
            logs = agreement.sudo().sign_request_id.sign_log_ids.filtered(lambda log: log.action == "sign")
            agreement.signed_on = max(logs.mapped("log_date"), default=fields.Datetime.now())

    def _compute_signing_url(self):
        for agreement in self:
            request = agreement.sudo().sign_request_id
            item = request.request_item_ids.filtered(
                lambda i: i.partner_id == agreement.signer_id and i.state == "sent"
            )[:1]
            agreement.signing_url = (
                f"/sign/document/{request.id}/{item.access_token}"
                if item and agreement.state == "sent" else False
            )

    def _compute_document_count(self):
        for agreement in self:
            agreement.document_count = len(agreement.sudo().sign_request_id.completed_document_attachment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].sudo().next_by_code("gym.agreement") or "/"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    @api.model
    def _gym_send(self, partner, agreement_type, signer=None, reference_doc=None):
        """Send the current template of ``agreement_type`` to ``partner`` for signature."""
        template = self.env["gym.agreement.template"]._gym_current(agreement_type, partner.company_id or None)
        if not template:
            raise UserError(_(
                "There is no active %(use)s template. Set one up under Gym → Configuration → Agreement Templates.",
                use=dict(AGREEMENT_TYPES)[agreement_type],
            ))
        signer = signer or partner._gym_signer()
        if not signer.email:
            raise UserError(_("%(signer)s needs an email address to sign.", signer=signer.display_name))
        role = template.sign_template_id.sudo().sign_item_ids.responsible_id[:1]
        document = reference_doc or partner
        request = self.env["sign.request"].sudo().create({
            "template_id": template.sign_template_id.id,
            "reference": f"{template.name} - {partner.name}",
            "reference_doc": f"{document._name},{document.id}",
            "request_item_ids": [(0, 0, {"partner_id": signer.id, "role_id": role.id})],
        })
        return self.sudo().create({
            "partner_id": partner.id,
            "signer_id": signer.id,
            "template_id": template.id,
            "version": template.version,
            "sign_request_id": request.id,
        })

    # ------------------------------------------------------------------
    # After signing
    # ------------------------------------------------------------------

    def _gym_process_signed(self):
        """Run what follows a signature, once per agreement."""
        for agreement in self.sudo().filtered(lambda a: a.state == "signed" and not a.processed):
            agreement._gym_on_signed()
            agreement.processed = True

    def _gym_on_signed(self):
        """Hook. A signed waiver turns a waiting contact into a member."""
        self.ensure_one()
        partner = self.partner_id
        if self.agreement_type == "waiver" and partner.gym_member_state in ("pending", "none", "former"):
            partner._gym_write({"gym_member_state": "member"})
            partner._gym_sync_pin({"gym_member_state": "member"})
            partner.message_post(body=_("Waiver %(ref)s signed: now a gym member.", ref=self.name))

    @api.model
    def _cron_gym_process_signed(self):
        self.search([("state", "=", "signed"), ("processed", "=", False)])._gym_process_signed()

    def gym_poll(self):
        """Status for screens waiting on a signature."""
        self._gym_require(GROUP_RECEPTION)
        self._gym_process_signed()
        return {agreement.id: agreement.sudo().state for agreement in self}

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    @api.model
    def _gym_require(self, group):
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_("You are not allowed to do this in the Gym app."))

    def action_open_signing(self):
        self.ensure_one()
        self._gym_require(GROUP_RECEPTION)
        if not self.signing_url:
            raise UserError(_("%(ref)s is not waiting for a signature.", ref=self.name))
        return {"type": "ir.actions.act_url", "url": self.signing_url, "target": "new"}

    def action_check_signature(self):
        self._gym_require(GROUP_RECEPTION)
        self._gym_process_signed()
        return True

    def action_void(self):
        self._gym_require(GROUP_MANAGER)
        for agreement in self:
            reason = self.env.context.get("void_reason") or _("Voided by %(user)s", user=self.env.user.name)
            agreement.sudo().write({"voided": True, "void_reason": reason})
        return True

    def action_download_documents(self):
        """Signed PDF and certificate. Managers only: they may not have Sign rights."""
        self.ensure_one()
        self._gym_require(GROUP_MANAGER)
        attachments = self.sudo().sign_request_id.completed_document_attachment_ids
        if not attachments:
            raise UserError(_("There is no signed document yet."))
        attachment = attachments.sorted("id")[:1]
        token = attachment.generate_access_token()[0]
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true&access_token={token}",
            "target": "new",
        }
