from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    hide_catalog_prices = fields.Boolean(
        string="Hide Prices in Catalog",
        help="When enabled, prices are hidden in the Sales Product Catalog.",
    )

    def action_add_from_catalog(self):
        """Pass the current catalog price visibility setting to the catalog action."""
        action = super().action_add_from_catalog()
        if len(self) == 1:
            ctx = dict(action.get("context") or {})
            ctx["hide_catalog_prices"] = self.hide_catalog_prices
            action["context"] = ctx
        return action
