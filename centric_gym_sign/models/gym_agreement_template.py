from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

AGREEMENT_TYPES = [
    ("waiver", "Waiver (new members)"),
    ("membership", "Membership agreement"),
]


class GymAgreementTemplate(models.Model):
    """Which Sign template the gym uses for a kind of agreement, and its version.

    The wording lives in the gym's own PDF inside the Sign template. A new
    wording is a new template record, so every signed agreement keeps pointing
    at exactly what was signed.
    """

    _name = "gym.agreement.template"
    _description = "Gym Agreement Template"
    _order = "agreement_type, sequence, id desc"

    name = fields.Char(required=True)
    agreement_type = fields.Selection(AGREEMENT_TYPES, string="Used For", required=True, default="waiver")
    version = fields.Char(
        required=True, default="1",
        help="Shown on every agreement signed with this template. For new wording, duplicate the "
             "template, give it a new version and archive the old one: members must then sign again.",
    )
    sign_template_id = fields.Many2one(
        "sign.template", string="Sign Template", required=True, ondelete="restrict",
        help="Prepared in the Sign app from the gym's PDF, with one signer role.",
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one("res.company", required=True, index=True, default=lambda self: self.env.company)
    note = fields.Text()
    agreement_ids = fields.One2many("gym.agreement", "template_id")
    agreement_count = fields.Integer(compute="_compute_agreement_count")

    def _compute_agreement_count(self):
        counts = dict(self.env["gym.agreement"]._read_group(
            [("template_id", "in", self.ids)], ["template_id"], ["__count"]
        ))
        for template in self:
            template.agreement_count = counts.get(template, 0)

    @api.constrains("active", "agreement_type", "company_id")
    def _check_one_active(self):
        for template in self.filtered("active"):
            if self.search_count([
                ("id", "!=", template.id),
                ("agreement_type", "=", template.agreement_type),
                ("company_id", "=", template.company_id.id),
            ]):
                raise ValidationError(_(
                    "There is already an active template for %(use)s. Archive it first.",
                    use=dict(AGREEMENT_TYPES)[template.agreement_type],
                ))

    @api.constrains("sign_template_id")
    def _check_single_signer(self):
        for template in self:
            roles = template.sign_template_id.sudo().sign_item_ids.responsible_id
            if len(roles) != 1:
                raise ValidationError(_(
                    "The Sign template %(name)s must have fields for exactly one signer role.",
                    name=template.sign_template_id.name,
                ))

    def write(self, vals):
        if {"version", "sign_template_id", "agreement_type"} & vals.keys() and self.agreement_ids:
            raise UserError(_(
                "Documents were already signed with this template. Duplicate it for a new version "
                "and archive this one instead."
            ))
        return super().write(vals)

    @api.model
    def _gym_current(self, agreement_type, company=None):
        return self.sudo().search([
            ("agreement_type", "=", agreement_type),
            ("company_id", "=", (company or self.env.company).id),
        ], limit=1)
