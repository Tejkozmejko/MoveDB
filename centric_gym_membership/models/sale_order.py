from odoo import _, api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    is_gym_membership = fields.Boolean(
        string="Gym Membership",
        compute="_compute_is_gym_membership",
        store=True,
        index=True,
    )

    @api.depends("order_line.product_id.product_tmpl_id.gym_membership")
    def _compute_is_gym_membership(self):
        for order in self:
            order.is_gym_membership = any(order.order_line.product_id.product_tmpl_id.mapped("gym_membership"))

    @api.model
    def _gym_memberships_action(self):
        """Subscriptions' own list, restricted to gym memberships."""
        action = self.env["ir.actions.act_window"]._for_xml_id("sale_subscription.sale_subscription_action")
        action.update({
            "name": _("Memberships"),
            "domain": [("is_gym_membership", "=", True), ("is_subscription", "=", True)],
        })
        return action
