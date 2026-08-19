from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    # Dynamic domain for the Customer field (partner_id). When the current user
    # has an Allowed Customers list, the Customer dropdown is limited to it; for
    # everyone else it is unrestricted ([]). Kept as a computed Binary domain
    # bound in the form via domain="centric_allowed_customer_domain", mirroring
    # the Delivery Address domain approach.
    centric_allowed_customer_domain = fields.Binary(
        string="Allowed Customer Domain",
        compute="_compute_centric_allowed_customer_domain",
    )

    @api.depends_context("uid")
    def _compute_centric_allowed_customer_domain(self):
        allowed = self.env.user.centric_allowed_customer_ids
        domain = [("id", "in", allowed.ids)] if allowed else []
        for order in self:
            order.centric_allowed_customer_domain = domain

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        # Convenience: if the user is locked to exactly one customer, pre-fill it.
        allowed = self.env.user.centric_allowed_customer_ids
        if len(allowed) == 1 and "partner_id" in fields_list and not defaults.get("partner_id"):
            defaults["partner_id"] = allowed.id
        return defaults

    @api.constrains("partner_id")
    def _check_centric_allowed_customer(self):
        # Enforce the per-user customer restriction as a clear message. The record
        # rules already hide other customers' orders; this also catches a wrong
        # customer arriving via import / RPC / programmatic creation. Keyed on the
        # acting user, so admins and unrestricted users are never affected. Matching
        # is on the commercial partner, so a contact of an allowed customer is fine.
        allowed = self.env.user.centric_allowed_customer_ids
        if not allowed:
            return
        allowed_commercial = allowed.commercial_partner_id
        for order in self:
            if order.partner_id and order.partner_id.commercial_partner_id not in allowed_commercial:
                raise ValidationError(
                    _(
                        "You can only create sales orders for: %(customers)s.",
                        customers=", ".join(allowed.mapped("display_name")),
                    )
                )
