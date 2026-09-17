from odoo import fields, models


class GymCheckin(models.Model):
    _inherit = "gym.checkin"

    subscription_id = fields.Many2one(
        "sale.order", string="Membership", readonly=True, index="btree_not_null",
        help="The subscription that was running at check-in.",
    )

    def _gym_after_check_in(self, status):
        if status.get("order_id"):
            self.sudo().subscription_id = status["order_id"]
        return super()._gym_after_check_in(status)
