from odoo import api, fields, models
from odoo.tools import SQL


class ProductProduct(models.Model):
    _inherit = "product.product"

    # Context-scoped list of the sale order lines on which the catalog's current
    # customer previously bought this product. Populated only when opened with a
    # `catalog_history_order_id` in context (i.e. the "Card" button from the
    # Sales catalog), so it stays empty on a normal product form.
    catalog_history_line_ids = fields.Many2many(
        "sale.order.line",
        string="Previously Purchased",
        compute="_compute_catalog_history_line_ids",
    )

    @api.depends_context("catalog_history_order_id")
    def _compute_catalog_history_line_ids(self):
        SaleOrderLine = self.env["sale.order.line"]
        order_id = self.env.context.get("catalog_history_order_id")
        order = (
            self.env["sale.order"].browse(order_id).exists()
            if order_id
            else self.env["sale.order"]
        )
        partner = order.partner_id.commercial_partner_id if order else False
        for product in self:
            lines = SaleOrderLine
            if partner:
                domain = [
                    ("order_id.state", "=", "sale"),
                    ("order_partner_id", "child_of", partner.id),
                    ("product_id", "=", product.id),
                    ("display_type", "=", False),
                ]
                if order:
                    domain.append(("order_id", "!=", order.id))
                lines = SaleOrderLine.search(domain).sorted(
                    key=lambda line: (line.order_id.date_order or line.create_date),
                    reverse=True,
                )
            product.catalog_history_line_ids = lines

    # Search-only helper (no storage, no compute): lets the Sales catalog filter
    # products down to what the order's customer bought before. It mirrors the
    # native `is_in_selected_section_of_order` pattern so the catalog search view
    # can reference a real field (and therefore passes view validation), while
    # the actual list is resolved from the `order_id` carried in the context.
    is_previously_purchased = fields.Boolean(
        search="_search_is_previously_purchased",
    )

    def _search_is_previously_purchased(self, operator, value):
        ctx = self.env.context
        order_id = ctx.get("order_id")
        order_model = ctx.get("product_catalog_order_model")
        product_ids = []
        if order_id and order_model == "sale.order":
            order = self.env["sale.order"].browse(order_id).exists()
            if order:
                product_ids = order._get_previously_purchased_product_ids()
        # The catalog filter is always used as ('=', True); resolve to the ids.
        return [("id", "in", product_ids)]

    # Search-only helper: filter the Sales catalog to the products this order's
    # customer usually orders (recommendations from history). Same mechanism as
    # `is_previously_purchased`, but resolved to the frequently-ordered subset.
    is_recommended = fields.Boolean(
        search="_search_is_recommended",
    )

    def _search_is_recommended(self, operator, value):
        ctx = self.env.context
        order_id = ctx.get("order_id")
        order_model = ctx.get("product_catalog_order_model")
        product_ids = []
        if order_id and order_model == "sale.order":
            order = self.env["sale.order"].browse(order_id).exists()
            if order:
                product_ids = order._get_recommended_product_ids()
        return [("id", "in", product_ids)]

    def _get_catalog_ranking(self):
        """Product ids in the order the catalog should show them, resolved from
        the active filter's context flag:

        - "Recommended" (`catalog_rank_recommended`): most-bought first.
        - "Previously Purchased" (`catalog_rank_previously_purchased`):
          most-recently-bought first, so the grid follows the recency colours
          (red at the top, down to green).

        Recommended wins when both filters are active. Empty when no ranking
        filter is on."""
        ctx = self.env.context
        if ctx.get("product_catalog_order_model") != "sale.order":
            return []
        order_id = ctx.get("order_id")
        if not order_id:
            return []
        order = self.env["sale.order"].browse(order_id).exists()
        if not order:
            return []
        if ctx.get("catalog_rank_recommended"):
            return order._get_recommended_product_ids()
        if ctx.get("catalog_rank_previously_purchased"):
            return order._get_previously_purchased_product_ids()
        return []

    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """Rank the Sales catalog for the customer when a ranking filter is
        active: "Recommended" sorts most-bought first, "Previously Purchased"
        sorts most-recently-bought first.

        The ranking is customer-specific, so it can't be a sortable column; we
        impose it on the query with `array_position` over the ranked ids. The
        ORDER BY is applied before LIMIT/OFFSET, so paging follows the ranking.
        """
        query = super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)
        ranked_ids = self._get_catalog_ranking()
        if ranked_ids:
            query.order = SQL(
                "array_position(%s::int[], %s)",
                ranked_ids,
                SQL.identifier(self._table, "id"),
            )
        return query
