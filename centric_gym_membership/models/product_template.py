from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    gym_membership = fields.Boolean(
        string="Gym Membership",
        help="Selling this subscription product gives gym access for the subscription's period.",
    )

    @api.onchange("gym_membership")
    def _onchange_gym_membership(self):
        if self.gym_membership:
            self.recurring_invoice = True

    @api.constrains("gym_membership", "recurring_invoice")
    def _check_gym_membership_is_recurring(self):
        for product in self:
            if product.gym_membership and not product.recurring_invoice:
                raise ValidationError(_(
                    "%(product)s is a gym membership, so it must be a subscription product.",
                    product=product.display_name,
                ))
