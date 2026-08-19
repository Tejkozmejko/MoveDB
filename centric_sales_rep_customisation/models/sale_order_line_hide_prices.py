# -*- coding: utf-8 -*-
from odoo import models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _get_product_catalog_lines_data(self, **kwargs):
        """Hide catalog prices for products that are already on the order.

        This only affects the Product Catalog card payload. It does not change
        price_unit, discount, subtotal, or any real sale order calculation.
        """
        res = super()._get_product_catalog_lines_data(**kwargs)

        parent_record = kwargs.get("parent_record")
        hide_prices = False

        if parent_record and parent_record._name == "sale.order":
            hide_prices = parent_record.hide_catalog_prices
        elif self and len(self.order_id) == 1:
            hide_prices = self.order_id.hide_catalog_prices

        if hide_prices:
            res["price"] = 0.0

        return res
