from odoo import _, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    def _process_saved_order(self, draft):
        result = super()._process_saved_order(draft)
        if not draft and self.state in ("paid", "done"):
            self._gym_after_payment()
        return result

    def _gym_after_payment(self):
        self.ensure_one()
        order_sudo = self.sudo()
        memberships = order_sudo.lines.sale_order_origin_id.filtered("is_gym_membership")
        for membership in memberships:
            signed = membership.gym_agreement_ids.filtered(lambda a: a.state == "signed")
            if membership.state in ("draft", "sent"):
                membership.action_confirm()
            membership.gym_pos_pending = False
            signed.write({"pos_order_id": self.id})
            if not signed:
                membership.activity_schedule(
                    "mail.mail_activity_data_todo",
                    note=_("Paid at the Point of Sale (%(pos)s) without a signed membership agreement. "
                           "Have the member sign it.", pos=self.name),
                )
        refunded = order_sudo.lines.refunded_orderline_id.sale_order_origin_id.filtered("is_gym_membership")
        for membership in refunded:
            membership.activity_schedule(
                "mail.mail_activity_data_todo",
                note=_("This membership was refunded at the Point of Sale (%(pos)s). "
                       "Close the subscription.", pos=self.name),
            )
