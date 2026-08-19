"""Auto-create shop replenishment rules for new products.

Every warehouse with "Resupply From" set (the shops) gets a Manual, 0/0
reordering rule for each storable product its company can see, pinned to the
inter-warehouse resupply route. Odoo does not do this by itself: reordering
rules are plain records, so a product added after the initial setup would
never appear on the shop order pads (Inventory > Operations > Replenishment)
until someone created its rules by hand.

The backfill fires when a product is created, when an existing product becomes
storable / changes company, and when a warehouse first gains a resupply
source. It only ever adds missing rules; it never edits or removes existing
ones, so hand-tuned Min/Max or Auto triggers are preserved. Kill switch:
system parameter centric_delivery_method_customisation.auto_shop_orderpoints
set to "0".
"""

from odoo import api, models


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    @api.model_create_multi
    def create(self, vals_list):
        warehouses = super().create(vals_list)
        warehouses._centric_backfill_shop_orderpoints()
        return warehouses

    def write(self, vals):
        had_resupply = {wh.id: bool(wh.resupply_wh_ids) for wh in self}
        res = super().write(vals)
        if "resupply_wh_ids" in vals:
            newly_resupplied = self.filtered(
                lambda wh: wh.resupply_wh_ids and not had_resupply[wh.id]
            )
            newly_resupplied._centric_backfill_shop_orderpoints()
        return res

    def _centric_backfill_shop_orderpoints(self, products=None):
        """Create the missing Manual 0/0 rules at the shops in ``self``.

        ``products`` limits the backfill to those variants; ``None`` means
        every storable product the shop's company can see.
        """
        get_param = self.env["ir.config_parameter"].sudo().get_param
        disabled = get_param(
            "centric_delivery_method_customisation.auto_shop_orderpoints", "1"
        )
        if disabled in ("0", "False", "false"):
            return
        shops = self.filtered("resupply_wh_ids")
        if not shops:
            return
        Product = self.env["product.product"].sudo()
        Orderpoint = self.env["stock.warehouse.orderpoint"].sudo()
        Route = self.env["stock.route"].sudo()
        vals_list = []
        for shop in shops:
            if products is None:
                shop_products = Product.search([
                    ("is_storable", "=", True),
                    ("company_id", "in", [False, shop.company_id.id]),
                ])
            else:
                shop_products = products.filtered(
                    lambda p: p.active and p.is_storable
                    and p.company_id.id in (False, shop.company_id.id)
                )
            if not shop_products:
                continue
            route = Route.search([
                ("supplied_wh_id", "=", shop.id),
                ("supplier_wh_id", "in", shop.resupply_wh_ids.ids),
            ], limit=1)
            # Archived rules count too: the unique constraint on
            # (product, location, company) does not care about active.
            existing = set(
                Orderpoint.with_context(active_test=False).search([
                    ("location_id", "=", shop.lot_stock_id.id),
                    ("product_id", "in", shop_products.ids),
                ]).mapped("product_id").ids
            )
            vals_list.extend(
                {
                    "product_id": product.id,
                    "warehouse_id": shop.id,
                    "location_id": shop.lot_stock_id.id,
                    "route_id": route.id,
                    "product_min_qty": 0.0,
                    "product_max_qty": 0.0,
                    "trigger": "manual",
                    "company_id": shop.company_id.id,
                }
                for product in shop_products
                if product.id not in existing
            )
        if vals_list:
            Orderpoint.create(vals_list)


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model_create_multi
    def create(self, vals_list):
        products = super().create(vals_list)
        storable = products.filtered(lambda p: p.active and p.is_storable)
        if storable:
            self.env["stock.warehouse"].sudo().search([
                ("resupply_wh_ids", "!=", False),
            ])._centric_backfill_shop_orderpoints(storable)
        return products


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("is_storable", "company_id", "active")):
            storable = self.product_variant_ids.filtered(
                lambda p: p.active and p.is_storable
            )
            if storable:
                self.env["stock.warehouse"].sudo().search([
                    ("resupply_wh_ids", "!=", False),
                ])._centric_backfill_shop_orderpoints(storable)
        return res
