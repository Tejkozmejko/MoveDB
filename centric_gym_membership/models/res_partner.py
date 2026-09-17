from collections import defaultdict
from datetime import date, timedelta

from odoo import _, api, fields, models

STATUSES = [
    ("active", "Active"),
    ("not_started", "Not started yet"),
    ("suspended", "Suspended"),
    ("expired", "Expired"),
    ("cancelled", "Cancelled"),
    ("no_membership", "No membership"),
]
# A renewed subscription keeps running until its end date; a paused one is suspended.
RUNNING = ("3_progress", "5_renewed")
PAUSED = "4_paused"
CLOSED = "6_churn"


def _period_end(order):
    """Last day a subscription covers: its end date, or the day before the next invoice."""
    if order.end_date:
        return order.end_date
    if order.next_invoice_date:
        return order.next_invoice_date - timedelta(days=1)
    return False


class ResPartner(models.Model):
    _inherit = "res.partner"

    gym_membership_status = fields.Selection(
        STATUSES,
        string="Membership",
        compute="_compute_gym_membership",
        search="_search_gym_membership_status",
    )
    gym_membership_id = fields.Many2one(
        "sale.order", string="Current Membership", compute="_compute_gym_membership",
    )
    gym_next_membership_id = fields.Many2one(
        "sale.order", string="Next Membership", compute="_compute_gym_membership",
        help="A membership already sold that starts later, e.g. a renewal.",
    )
    gym_membership_end = fields.Date(
        string="Membership Ends", compute="_compute_gym_membership",
        help="Last covered day, including any renewal that follows without a gap.",
    )
    gym_membership_count = fields.Integer(string="Memberships", compute="_compute_gym_membership")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @api.model
    def _gym_membership_orders(self, partners):
        """Confirmed or cancelled gym subscriptions of the partners, by partner."""
        orders = self.env["sale.order"].sudo().search([
            ("partner_id", "in", partners.ids),
            ("is_gym_membership", "=", True),
            ("is_subscription", "=", True),
            ("state", "in", ("sale", "cancel")),
            ("subscription_state", "not in", ("1_draft", "2_renewal", "7_upsell")),
        ], order="start_date, id")
        # Built from the sudo recordset: reception may not read sale orders.
        by_partner = defaultdict(orders.browse)
        for order in orders:
            by_partner[order.partner_id.id] |= order
        return by_partner

    @api.model
    def _gym_membership_info(self, orders, today):
        """Status of one member from their gym subscriptions (oldest first)."""
        confirmed = orders.filtered(lambda o: o.state == "sale")
        covering = confirmed.filtered(
            lambda o: o.start_date and o.start_date <= today and (_period_end(o) or date.max) >= today
            and o.subscription_state in (*RUNNING, PAUSED)
        )
        upcoming = confirmed.filtered(
            lambda o: o.start_date and o.start_date > today and o.subscription_state in RUNNING
        )
        info = {"order": orders.browse(), "next": upcoming[:1], "end": False, "count": len(orders)}
        running = covering.filtered(lambda o: o.subscription_state in RUNNING)
        if running:
            current = running[-1]
            info.update(code="active", order=current, end=self._gym_chain_end(current, upcoming))
        elif covering:
            info.update(code="suspended", order=covering[-1], end=_period_end(covering[-1]))
        elif upcoming:
            info.update(code="not_started", order=upcoming[0], end=_period_end(upcoming[0]))
        elif confirmed:
            last = confirmed.sorted(lambda o: (_period_end(o) or date.min, o.id))[-1]
            early_close = last.subscription_state == CLOSED and (_period_end(last) or date.min) >= today
            info.update(code="cancelled" if early_close else "expired", order=last, end=_period_end(last))
        elif orders:
            info.update(code="cancelled", order=orders[-1], end=_period_end(orders[-1]))
        else:
            info.update(code="no_membership")
        return info

    @api.model
    def _gym_chain_end(self, current, upcoming):
        """End of the current membership, extended by renewals that start the next day."""
        end = _period_end(current)
        for order in upcoming:
            if end and order.start_date == end + timedelta(days=1):
                end = _period_end(order) or end
        return end

    def _gym_membership_infos(self):
        today = fields.Date.context_today(self)
        by_partner = self._gym_membership_orders(self)
        return {
            partner.id: self._gym_membership_info(by_partner[partner.id], today)
            for partner in self
        }

    def _compute_gym_membership(self):
        infos = self._origin._gym_membership_infos()
        empty = {"code": "no_membership", "order": False, "next": False, "end": False, "count": 0}
        for partner in self:
            info = infos.get(partner._origin.id, empty)
            partner.gym_membership_status = info["code"] if partner.gym_member_state != "none" or info["count"] else False
            partner.gym_membership_id = info["order"]
            partner.gym_next_membership_id = info["next"]
            partner.gym_membership_end = info["end"]
            partner.gym_membership_count = info["count"]

    def _search_gym_membership_status(self, operator, value):
        if operator != "in":
            return NotImplemented
        members = self.sudo().with_context(active_test=False).search([("gym_member_state", "!=", "none")])
        infos = members._gym_membership_infos()
        wanted = set(value)
        return [("id", "in", [pid for pid, info in infos.items() if info["code"] in wanted])]

    def _gym_membership_status(self):
        self.ensure_one()
        info = self._gym_membership_infos()[self.id]
        order = info["order"]
        labels = dict(STATUSES)
        label = labels[info["code"]]
        if order:
            product = order.order_line.product_id[:1]
            label = f"{product.display_name or order.name} ({order.name})"
        return {
            "code": info["code"],
            "label": label,
            "end": info["end"],
            "order_id": order.id if order else False,
        }

    def _gym_last_activity_date(self):
        last = super()._gym_last_activity_date()
        ends = [
            _period_end(order) for order in self._gym_membership_orders(self)[self.id]
            if _period_end(order)
        ]
        return max([last, *ends])

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def action_gym_view_memberships(self):
        self.ensure_one()
        action = self.env["sale.order"]._gym_memberships_action()
        action["domain"] = action["domain"] + [("partner_id", "=", self.id)]
        action["context"] = {"default_partner_id": self.id}
        return action
