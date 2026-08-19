# -*- coding: utf-8 -*-
from odoo import api, models
from odoo.exceptions import AccessError
from odoo.tools import format_amount, format_date


class SaleOrderLinePriceHistory(models.Model):
    _inherit = "sale.order.line"

    @api.model
    def centric_price_history(self, product_id, partner_id, exclude_order_id=False, limit=10):
        """Previous unit prices this customer paid for a product.

        Feeds the dropdown of the ``centric_price_history`` widget on the SO
        line's Unit Price. Returns at most ``limit`` entries, one per distinct
        price, most recent first:
        ``[{"price": float, "price_label": str, "note": str}, ...]``
        (``price_label`` is the formatted amount, ``note`` the date and
        quantity of that sale).

        History is matched on the customer's commercial entity, so every
        branch / delivery contact of the same company shares one price
        history, and it is searched with sudo so it spans all salespeople's
        orders (a rep record-ruled to their own orders still gets the price
        the office quoted last week). The customer gate stays: the caller
        must be allowed to read the partner, which keeps restricted reps
        (locked to their assigned customers) from probing anyone else's
        prices.
        """
        if not product_id or not partner_id or not self.env.user._is_internal():
            return []
        partner = self.env["res.partner"].browse(int(partner_id)).exists()
        if not partner:
            return []
        try:
            partner.check_access("read")
        except AccessError:
            return []  # not this rep's customer: empty dropdown, not an error
        domain = [
            ("product_id", "=", int(product_id)),
            ("order_partner_id.commercial_partner_id", "=", partner.commercial_partner_id.id),
            ("state", "=", "sale"),
            ("display_type", "=", False),
            ("company_id", "=", self.env.company.id),
        ]
        if exclude_order_id:
            domain.append(("order_id", "!=", int(exclude_order_id)))
        # Over-fetch, then keep the first (= most recent) line of each price.
        lines = self.sudo().search(domain, order="create_date desc, id desc", limit=200)
        entries, seen = [], set()
        for line in lines:
            price = line.price_unit
            key = round(price, 6)
            if price <= 0 or key in seen:
                continue
            seen.add(key)
            currency = line.currency_id or line.company_id.currency_id
            qty = line.product_uom_qty
            qty_text = "%g" % qty
            uom = line.product_uom_id.name or ""
            entries.append({
                "price": price,
                "price_label": format_amount(self.env, price, currency),
                "note": "%s · %s %s" % (
                    format_date(self.env, line.order_id.date_order),
                    qty_text, uom,
                ),
            })
            if len(entries) >= limit:
                break
        return entries
