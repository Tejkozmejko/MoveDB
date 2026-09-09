# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class CentricRestaurantMenuReport(models.Model):
    """One row per POS order line, with the margin already worked out.

    Odoo ships ``report.pos.order``, but it aggregates to order level and does
    not expose cost, so it cannot answer "what does this dish actually make?".
    This view keeps the line grain and reads ``pos_order_line.total_cost``,
    which is the stored cost Odoo snapshots at sale time. For the menu that is
    the kit-BoM roll-up written by ``centric_restaurant_demo``, so margin here
    is recipe-driven rather than a guess.
    """

    _name = "centric.restaurant.menu.report"
    _description = "Restaurant Menu Performance"
    _auto = False
    _rec_name = "product_id"
    _order = "date desc"

    date = fields.Datetime("Order Date", readonly=True)
    order_id = fields.Many2one("pos.order", "Order", readonly=True)
    session_id = fields.Many2one("pos.session", "Session", readonly=True)
    config_id = fields.Many2one("pos.config", "Point of Sale", readonly=True)
    # ``pos.order.employee_id`` only exists once ``pos_hr`` is installed, so
    # the view sticks to ``user_id``, which is always there.
    user_id = fields.Many2one("res.users", "Salesperson", readonly=True)
    partner_id = fields.Many2one("res.partner", "Customer", readonly=True)
    company_id = fields.Many2one("res.company", "Company", readonly=True)
    currency_id = fields.Many2one("res.currency", "Currency", readonly=True)

    product_id = fields.Many2one("product.product", "Dish", readonly=True)
    product_tmpl_id = fields.Many2one("product.template", "Product", readonly=True)
    categ_id = fields.Many2one("product.category", "Product Category", readonly=True)

    qty = fields.Float("Quantity Sold", readonly=True)
    revenue = fields.Monetary("Net Revenue", readonly=True)
    cost = fields.Monetary("Cost", readonly=True)
    margin = fields.Monetary("Margin", readonly=True)

    def init(self):
        # ``total_cost`` is only populated once Odoo has computed it; treat a
        # null as zero rather than dropping the line, otherwise a dish sold
        # before costing was set would silently vanish from the mix.
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            """
            CREATE VIEW %s AS (
                SELECT
                    l.id                                    AS id,
                    o.date_order                            AS date,
                    o.id                                    AS order_id,
                    o.session_id                            AS session_id,
                    o.config_id                             AS config_id,
                    o.user_id                               AS user_id,
                    o.partner_id                            AS partner_id,
                    o.company_id                            AS company_id,
                    c.currency_id                           AS currency_id,
                    l.product_id                            AS product_id,
                    p.product_tmpl_id                       AS product_tmpl_id,
                    t.categ_id                              AS categ_id,
                    l.qty                                   AS qty,
                    l.price_subtotal                        AS revenue,
                    COALESCE(l.total_cost, 0.0)             AS cost,
                    l.price_subtotal - COALESCE(l.total_cost, 0.0) AS margin
                FROM pos_order_line l
                JOIN pos_order o        ON o.id = l.order_id
                JOIN res_company c      ON c.id = o.company_id
                JOIN product_product p  ON p.id = l.product_id
                JOIN product_template t ON t.id = p.product_tmpl_id
                WHERE o.state IN ('paid', 'done')
            )
            """
            % self._table
        )
