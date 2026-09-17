import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

PERIOD_UNITS = {"week": "weeks", "month": "months", "year": "years"}
ABANDON_HOURS = 12
POS_USER = "point_of_sale.group_pos_user"


class SaleOrder(models.Model):
    _inherit = "sale.order"

    gym_pos_pending = fields.Boolean(
        string="Waiting for POS Payment",
        copy=False,
        readonly=True,
        help="Created at the Point of Sale for a membership that has not been paid yet.",
    )
    gym_agreement_ids = fields.One2many("gym.agreement", "sale_order_id", string="Agreements")

    @api.model
    def _gym_require_pos_user(self):
        if not self.env.su and not self.env.user.has_group(POS_USER):
            raise AccessError(_("Only Point of Sale users can sell memberships."))

    @api.model
    def _gym_plan_for(self, product):
        rules = product.product_tmpl_id.sudo().subscription_rule_ids.filtered("plan_id")
        if not rules:
            raise UserError(_(
                "%(product)s has no recurring price. Add one with a recurring plan on the product.",
                product=product.display_name,
            ))
        return rules[:1].plan_id

    @api.model
    def _gym_membership_period(self, partner, plan):
        """First day and last day of the membership being sold."""
        today = fields.Date.context_today(self)
        start = today
        current = partner._gym_membership_status()
        if current["code"] in ("active", "not_started", "suspended") and current.get("end"):
            start = max(today, current["end"] + timedelta(days=1))
        unit = PERIOD_UNITS[plan.billing_period_unit]
        end = start + relativedelta(**{unit: plan.billing_period_value}) - timedelta(days=1)
        return start, end

    @api.model
    def gym_pos_prepare(self, partner_id, product_id, config_id):
        """Create the subscription quotation and send the membership agreement."""
        self._gym_require_pos_user()
        partner = self.env["res.partner"].sudo().browse(partner_id).exists()
        product = self.env["product.product"].sudo().browse(product_id).exists()
        config = self.env["pos.config"].sudo().browse(config_id).exists()
        if not (partner and product and config):
            raise UserError(_("The customer or the product no longer exists."))
        if not product.product_tmpl_id.gym_membership:
            raise UserError(_("%(product)s is not a gym membership.", product=product.display_name))
        if partner.gym_member_state != "member":
            raise UserError(_(
                "%(name)s is not a gym member yet. Register them first (Gym → New Member): "
                "the waiver has to be signed before a membership is sold.",
                name=partner.name,
            ))
        if partner._gym_waiver_status() not in ("signed", "not_required"):
            raise UserError(_("%(name)s has to sign the current gym waiver first.", name=partner.name))
        if partner.gym_access_blocked:
            raise UserError(_("%(name)s is blocked by the gym: %(reason)s",
                              name=partner.name, reason=partner.gym_block_reason or ""))

        plan = self._gym_plan_for(product)
        start, end = self._gym_membership_period(partner, plan)
        order = self.sudo().with_company(config.company_id).create({
            "partner_id": partner.id,
            "company_id": config.company_id.id,
            "plan_id": plan.id,
            "start_date": start,
            "end_date": end,
            "origin": config.name,
            "gym_pos_pending": True,
            "order_line": [(0, 0, {"product_id": product.id, "product_uom_qty": 1})],
        })
        agreement = self.env["gym.agreement"]._gym_send(partner, "membership", reference_doc=order)
        agreement.sale_order_id = order
        return order._gym_pos_payload(agreement)

    def _gym_pos_payload(self, agreement):
        self.ensure_one()
        return {
            "order_id": self.id,
            "order_name": self.name,
            "agreement_id": agreement.id,
            "agreement_name": agreement.name,
            "signing_url": agreement.signing_url,
            "signer": agreement.signer_id.name,
            "member": self.partner_id.name,
            "product": self.order_line.product_id[:1].display_name,
            "start": fields.Date.to_string(self.start_date),
            "end": fields.Date.to_string(self.end_date),
            "amount": self.amount_total,
            "state": agreement.state,
        }

    def gym_pos_poll(self):
        """Agreement status for the POS waiting dialog; a signature confirms the subscription."""
        self._gym_require_pos_user()
        self.ensure_one()
        order = self.sudo()
        agreements = order.gym_agreement_ids.filtered(lambda a: a.state != "void")
        agreements._gym_process_signed()
        return {
            "state": agreements[:1].state or "cancelled",
            "order_state": order.state,
        }

    def gym_pos_cancel(self):
        """The cashier gave up before payment."""
        self._gym_require_pos_user()
        self.sudo()._gym_cancel_unpaid(_("Sale abandoned at the Point of Sale"))
        return True

    def _gym_cancel_unpaid(self, reason):
        for order in self.filtered(lambda o: o.gym_pos_pending and not o.sudo().pos_order_line_ids):
            order.gym_agreement_ids.filtered(lambda a: a.state != "void").write(
                {"voided": True, "void_reason": reason}
            )
            try:
                with self.env.cr.savepoint():
                    order._action_cancel()
                    order.gym_pos_pending = False
            except Exception:
                _logger.exception("Could not cancel abandoned gym membership %s", order.name)
                order.activity_schedule(
                    "mail.mail_activity_data_todo",
                    note=_("This membership was never paid at the Point of Sale. Cancel or close it."),
                )

    @api.model
    def gym_pos_check_payable(self, order_ids):
        """Refuse payment while a membership in the order has no signed agreement."""
        self._gym_require_pos_user()
        for order in self.sudo().browse(order_ids).exists().filtered("is_gym_membership"):
            if not order.gym_agreement_ids.filtered(lambda a: a.state == "signed"):
                return {"ok": False, "message": _(
                    "%(order)s: the membership agreement has not been signed.", order=order.name
                )}
        return {"ok": True}

    @api.model
    def _cron_gym_cancel_abandoned(self):
        limit = fields.Datetime.now() - timedelta(hours=ABANDON_HOURS)
        self.search([
            ("gym_pos_pending", "=", True),
            ("create_date", "<", limit),
        ])._gym_cancel_unpaid(_("Not paid within %(hours)s hours", hours=ABANDON_HOURS))
