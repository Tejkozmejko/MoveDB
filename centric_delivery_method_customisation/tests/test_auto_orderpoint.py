from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAutoShopOrderpoint(TransactionCase):
    """New storable products must automatically get a Manual 0/0 reordering
    rule at every warehouse that resupplies from another one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Warehouse = cls.env["stock.warehouse"]
        cls.main = Warehouse.create({"name": "Auto OP Main", "code": "AOMN"})
        cls.shop = Warehouse.create({
            "name": "Auto OP Shop",
            "code": "AOSH",
            "resupply_wh_ids": [(6, 0, cls.main.ids)],
        })
        cls.route = cls.env["stock.route"].search([
            ("supplied_wh_id", "=", cls.shop.id),
            ("supplier_wh_id", "=", cls.main.id),
        ], limit=1)

    def _shop_orderpoints(self, product):
        return self.env["stock.warehouse.orderpoint"].with_context(
            active_test=False
        ).search([
            ("product_id", "=", product.id),
            ("location_id", "=", self.shop.lot_stock_id.id),
        ])

    def test_new_storable_product_gets_shop_rule(self):
        product = self.env["product.product"].create({
            "name": "Auto OP Cod",
            "is_storable": True,
        })
        op = self._shop_orderpoints(product)
        self.assertEqual(len(op), 1)
        self.assertEqual(op.trigger, "manual")
        self.assertEqual(op.product_min_qty, 0)
        self.assertEqual(op.product_max_qty, 0)
        self.assertEqual(op.route_id, self.route)
        self.assertEqual(op.warehouse_id, self.shop)
        main_ops = self.env["stock.warehouse.orderpoint"].search([
            ("product_id", "=", product.id),
            ("warehouse_id", "=", self.main.id),
        ])
        self.assertFalse(main_ops, "the supplier warehouse must get no rule")

    def test_non_storable_product_gets_no_rule(self):
        product = self.env["product.product"].create({
            "name": "Auto OP Service",
            "type": "service",
        })
        self.assertFalse(self._shop_orderpoints(product))

    def test_other_company_product_gets_no_rule(self):
        other = self.env["res.company"].create({"name": "Auto OP Other Co"})
        product = self.env["product.product"].create({
            "name": "Auto OP Foreign",
            "is_storable": True,
            "company_id": other.id,
        })
        self.assertFalse(self._shop_orderpoints(product))

    def test_becoming_storable_backfills(self):
        product = self.env["product.product"].create({
            "name": "Auto OP Late Bloomer",
            "type": "consu",
            "is_storable": False,
        })
        self.assertFalse(self._shop_orderpoints(product))
        product.product_tmpl_id.write({"is_storable": True})
        self.assertEqual(len(self._shop_orderpoints(product)), 1)

    def test_no_duplicate_even_when_archived(self):
        product = self.env["product.product"].create({
            "name": "Auto OP Once Only",
            "is_storable": True,
        })
        op = self._shop_orderpoints(product)
        self.assertEqual(len(op), 1)
        op.action_archive()
        product.product_tmpl_id.write({"is_storable": True})
        self.assertEqual(
            len(self._shop_orderpoints(product)), 1,
            "an archived rule must block re-creation, not crash it",
        )

    def test_new_resupplied_warehouse_backfills_existing_products(self):
        product = self.env["product.product"].create({
            "name": "Auto OP Preexisting",
            "is_storable": True,
        })
        shop2 = self.env["stock.warehouse"].create({
            "name": "Auto OP Shop 2",
            "code": "AOS2",
            "resupply_wh_ids": [(6, 0, self.main.ids)],
        })
        ops = self.env["stock.warehouse.orderpoint"].search([
            ("product_id", "=", product.id),
            ("warehouse_id", "=", shop2.id),
        ])
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops.trigger, "manual")

    def test_kill_switch(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "centric_delivery_method_customisation.auto_shop_orderpoints", "0"
        )
        product = self.env["product.product"].create({
            "name": "Auto OP Switched Off",
            "is_storable": True,
        })
        self.assertFalse(self._shop_orderpoints(product))
