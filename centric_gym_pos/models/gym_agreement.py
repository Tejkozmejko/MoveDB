from odoo import fields, models


class GymAgreement(models.Model):
    _inherit = "gym.agreement"

    sale_order_id = fields.Many2one(
        "sale.order", string="Membership", readonly=True, index="btree_not_null", ondelete="set null",
    )
    pos_order_id = fields.Many2one("pos.order", string="POS Order", readonly=True, ondelete="set null")

    def _gym_on_signed(self):
        super()._gym_on_signed()
        order = self.sale_order_id.sudo()
        if self.agreement_type == "membership" and order.state in ("draft", "sent"):
            # Confirmed before payment: Odoo then counts the POS payment as the
            # invoice for the whole period (verified on Odoo 19 Enterprise).
            order.action_confirm()
