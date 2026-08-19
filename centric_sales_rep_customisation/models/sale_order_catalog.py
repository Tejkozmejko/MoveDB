from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _get_previously_purchased_product_ids(self):
        """Return the ids of the products this order's customer has already
        bought on past confirmed sale orders, RANKED most-recently-bought
        first — so the catalog's "Previously Purchased" view can sort the grid
        to follow the recency colours (red at the top, green at the bottom).

        The lookup is done on the commercial partner so that any contact of the
        same company (delivery addresses, ...) counts as the same customer.
        """
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner:
            return []
        lines = self.env["sale.order.line"].search(
            [
                ("order_id.state", "=", "sale"),
                ("order_id", "!=", self.id),
                ("order_partner_id", "child_of", partner.id),
                ("product_id", "!=", False),
                ("display_type", "=", False),
            ]
        )
        ranked = []
        seen = set()
        for line in lines.sorted(
            key=lambda l: (l.order_id.date_order or l.create_date), reverse=True
        ):
            product_id = line.product_id.id
            if product_id not in seen:
                seen.add(product_id)
                ranked.append(product_id)
        return ranked

    def _get_recommended_product_ids(self, min_orders=2):
        """Return products this order's customer *usually* orders, RANKED with
        the most-bought first.

        Kept to products bought on at least `min_orders` distinct past confirmed
        orders (the regulars), then sorted by total quantity purchased
        descending, tie-broken by how many orders included them. The catalog
        uses this order to show the biggest sellers for this customer at the top.
        Same customer scope as `_get_previously_purchased_product_ids`.
        """
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        if not partner:
            return []
        groups = self.env["sale.order.line"]._read_group(
            [
                ("order_id.state", "=", "sale"),
                ("order_id", "!=", self.id),
                ("order_partner_id", "child_of", partner.id),
                ("product_id", "!=", False),
                ("display_type", "=", False),
            ],
            groupby=["product_id"],
            aggregates=["order_id:count_distinct", "product_uom_qty:sum"],
        )
        ranked = [
            (product.id, order_count, total_qty)
            for product, order_count, total_qty in groups
            if order_count >= min_orders
        ]
        # Most bought first: total quantity, then order frequency.
        ranked.sort(key=lambda item: (item[2], item[1]), reverse=True)
        return [product_id for product_id, _orders, _qty in ranked]

    def _get_catalog_purchase_history(self, product_ids):
        """Return this customer's buying history for the given products.

        {product_id: {'qty': total qty bought before, 'price': last unit price}}

        Same customer scope as `_get_previously_purchased_product_ids` (the
        commercial partner, so all its contacts count). The current order is
        excluded. Used to surface "Bought X · Last €Y" on the Sales catalog card.
        """
        self.ensure_one()
        history = {}
        partner = self.partner_id.commercial_partner_id
        if not partner or not product_ids:
            return history
        lines = self.env["sale.order.line"].search(
            [
                ("order_id.state", "=", "sale"),
                ("order_id", "!=", self.id),
                ("order_partner_id", "child_of", partner.id),
                ("product_id", "in", product_ids),
                ("display_type", "=", False),
            ]
        )
        # Most recent first, so the first line seen per product carries the last
        # price sold. `date_order` is on the order, so we sort in Python.
        for line in lines.sorted(
            key=lambda l: (l.order_id.date_order or l.create_date), reverse=True
        ):
            data = history.setdefault(
                line.product_id.id, {"qty": 0.0, "price": None, "last_date": None}
            )
            data["qty"] += line.product_uom_qty
            if data["price"] is None:
                # First line seen per product is the most recent one.
                data["price"] = line.price_unit
                data["last_date"] = line.order_id.date_order or line.create_date
        return history

    @staticmethod
    def _catalog_recency_bucket(last_date, today):
        """Colour bucket for how recently the customer last bought a product:
        red <= 7 days, yellow <= 14, blue <= 21, purple <= a month, green
        anything older (including past 3 months)."""
        if not last_date:
            return ""
        days = (today - last_date.date()).days
        if days <= 7:
            return "red"
        if days <= 14:
            return "yellow"
        if days <= 21:
            return "blue"
        if days <= 31:
            return "purple"
        return "green"

    def _get_product_catalog_order_line_info(self, product_ids, child_field=False, **kwargs):
        """Inject the customer's purchase history onto every catalog card so the
        UI can show quantity bought before and the last price it was sold at,
        plus whether the product has packagings to cycle through."""
        info = super()._get_product_catalog_order_line_info(
            product_ids, child_field=child_field, **kwargs
        )
        history = self._get_catalog_purchase_history(product_ids)
        # In Odoo 19 "Packagings" are the product's additional UoMs (uom_ids);
        # a product is cycleable only when it has more than the base unit.
        products = self.env["product.product"].browse(list(info.keys()))
        has_packagings = {
            product.id: len(product.product_tmpl_id._get_available_uoms()) > 1
            for product in products
        }
        today = fields.Date.context_today(self)
        for product_id, data in info.items():
            entry = history.get(product_id)
            data["previouslyPurchasedQty"] = entry["qty"] if entry else 0.0
            data["previouslyPurchasedPrice"] = (
                (entry["price"] or 0.0) if entry else 0.0
            )
            data["previouslyPurchasedRecency"] = self._catalog_recency_bucket(
                entry and entry.get("last_date"), today
            )
            data["hasPackagings"] = has_packagings.get(product_id, False)
        return info

    def catalog_cycle_product_uom(self, product_id):
        """Advance this product's catalog line to its next packaging.

        "Packagings" in Odoo 19 are the extra UoMs allowed on the line
        (`allowed_uom_ids`). Setting `product_uom_id` is a real change: Odoo
        reconverts the quantity and re-prices the line. Public (no leading
        underscore) so the catalog can call it over RPC.
        """
        self.ensure_one()
        line = self.order_line.filtered(
            lambda sol: not sol.display_type and sol.product_id.id == product_id
        )[:1]
        if not line:
            return {}
        uoms = line.allowed_uom_ids
        if len(uoms) < 2:
            return {}
        uom_list = list(uoms)
        current = line.product_uom_id
        index = uom_list.index(current) if current in uom_list else -1
        line.product_uom_id = uom_list[(index + 1) % len(uom_list)]
        return {
            "uomDisplayName": line.product_uom_id.display_name,
            "price": line.price_unit,
            "quantity": line.product_uom_qty,
        }

    @api.readonly
    def action_add_from_catalog(self):
        """Point the Sales catalog at our own search view, which carries the
        "Previously Purchased" filter. The order id is already passed in the
        context by the Catalog button, so the filter's search field can resolve
        the customer's purchase history on its own."""
        action = super().action_add_from_catalog()
        if len(self) == 1:
            action["search_view_id"] = [
                self.env.ref(
                    "centric_sales_rep_customisation."
                    "product_view_search_catalog_previously_purchased"
                ).id,
                "search",
            ]
        return action
