import base64
import io

from openpyxl import Workbook

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStockEmailImport(TransactionCase):
    """An emailed stocktake sets on-hand stock to the counted quantities,
    all rows or none."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.manager = cls.env["res.users"].create({
            "name": "Stocktake Manager",
            "login": "stocktake_manager_test",
            "email": "stocktake.manager@example.com",
            "company_id": cls.company.id,
            "company_ids": [(6, 0, cls.company.ids)],
            "group_ids": [(6, 0, [cls.env.ref("stock.group_stock_manager").id])],
        })
        cls.stock = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1).lot_stock_id
        cls.shelf = cls.env["stock.location"].create({
            "name": "Stocktake Shelf",
            "location_id": cls.stock.id,
            "usage": "internal",
        })
        cls.config = cls.env["stock.email.import.config"].create({
            "name": "Test Stocktake",
            "company_id": cls.company.id,
            "user_id": cls.manager.id,
            "allowed_emails": "boss@example.com\nsecond@example.com",
            "notify_sender": False,
        })
        cls.apple = cls.env["product.product"].create({
            "name": "Stocktake Apple",
            "default_code": "STK-APPLE",
            "barcode": "5000000000011",
            "is_storable": True,
            "standard_price": 2.0,
        })
        cls.pear = cls.env["product.product"].create({
            "name": "Stocktake Pear",
            "default_code": "STK-PEAR",
            "is_storable": True,
        })
        cls.lotted = cls.env["product.product"].create({
            "name": "Stocktake Lotted",
            "default_code": "STK-LOT",
            "is_storable": True,
            "tracking": "lot",
        })
        cls.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": cls.apple.id,
            "location_id": cls.stock.id,
            "inventory_quantity": 10,
        }).action_apply_inventory()

    # -- helpers -------------------------------------------------------

    @staticmethod
    def _xlsx(rows):
        workbook = Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()

    def _import(self, rows=None, content=None, filename="stocktake.xlsx", **values):
        content = content if content is not None else self._xlsx(rows)
        record = self.env["stock.email.import"].create(dict({
            "name": "Test sheet",
            "config_id": self.config.id,
            "file": base64.b64encode(content),
            "file_name": filename,
        }, **values))
        record.action_process()
        return record

    def _on_hand(self, product, location=None, lot=None):
        quants = self.env["stock.quant"].search([
            ("product_id", "=", product.id),
            ("location_id", "=", (location or self.stock).id),
            ("lot_id", "=", lot.id if lot else False),
        ])
        return sum(quants.mapped("quantity"))

    # -- tests ---------------------------------------------------------

    def test_counted_quantity_is_applied(self):
        record = self._import([
            ["Product Code", "Name", "Category", "Price", "Quantity"],
            ["STK-APPLE", "Stocktake Apple", "All", 2, 25],
            ["STK-PEAR", "Stocktake Pear", "All", 1, 4],
        ])
        self.assertEqual(record.state, "done", record.error_message)
        self.assertEqual(self._on_hand(self.apple), 25)
        self.assertEqual(self._on_hand(self.pear), 4)
        apple_line = record.line_ids.filtered(lambda l: l.product_id == self.apple)
        self.assertEqual(apple_line.previous_qty, 10)
        self.assertEqual(apple_line.difference_qty, 15)
        self.assertAlmostEqual(apple_line.value_change, 30.0)
        self.assertTrue(record.move_ids, "inventory adjustment moves are linked")

    def test_count_down_to_zero(self):
        record = self._import([["SKU", "Qty"], ["STK-APPLE", 0]])
        self.assertEqual(record.state, "done", record.error_message)
        self.assertEqual(self._on_hand(self.apple), 0)

    def test_one_bad_row_changes_nothing(self):
        record = self._import([
            ["Product Code", "Quantity"],
            ["STK-APPLE", 99],
            ["DOES-NOT-EXIST", 5],
            ["STK-PEAR", -1],
        ])
        self.assertEqual(record.state, "failed")
        self.assertEqual(self._on_hand(self.apple), 10)
        self.assertEqual(record.error_count, 2)
        self.assertIn("DOES-NOT-EXIST", record.line_ids.filtered(
            lambda l: l.row_number == 3).message)

    def test_barcode_blank_rows_and_header_below_title(self):
        record = self._import([
            ["Daily stocktake"],
            [],
            ["Barcode", "Counted Quantity"],
            ["5000000000011", 12],
            [None, None],
            ["STK-NOT-A-BARCODE", None],
        ])
        self.assertEqual(record.state, "failed", "unknown product still fails")
        record = self._import([
            ["Daily stocktake"],
            ["Barcode", "Counted Quantity"],
            [5000000000011, 12],
            [None, None],
        ])
        self.assertEqual(record.state, "done", record.error_message)
        self.assertEqual(self._on_hand(self.apple), 12)

    def test_lot_and_location(self):
        record = self._import([
            ["Product Code", "Location", "Lot", "Quantity"],
            ["STK-LOT", self.shelf.complete_name, "LOT-A", 7],
            ["STK-LOT", self.shelf.complete_name, "LOT-A", 3],
        ])
        self.assertEqual(record.state, "done", record.error_message)
        lot = self.env["stock.lot"].search([
            ("name", "=", "LOT-A"), ("product_id", "=", self.lotted.id)])
        self.assertTrue(lot, "missing lot is created")
        self.assertEqual(self._on_hand(self.lotted, self.shelf, lot), 10,
                         "duplicate rows are added together")

    def test_tracked_product_requires_lot(self):
        record = self._import([["Product Code", "Quantity"], ["STK-LOT", 5]])
        self.assertEqual(record.state, "failed")

    def test_custom_column_mapping(self):
        self.env["stock.email.import.column"].create({
            "target": "product_code", "header_names": "Artikelnummer",
        })
        self.env["stock.email.import.column"].create({
            "target": "quantity", "header_names": "Menge",
        })
        record = self._import([["Artikelnummer", "Menge"], ["STK-PEAR", 8]])
        self.assertEqual(record.state, "done", record.error_message)
        self.assertEqual(self._on_hand(self.pear), 8)

    def test_same_file_twice_is_refused(self):
        content = self._xlsx([["Product Code", "Quantity"], ["STK-PEAR", 3]])
        self.assertEqual(self._import(content=content).state, "done")
        second = self._import(content=content)
        self.assertEqual(second.state, "failed")
        third = self._import(content=content, allow_duplicate=True)
        self.assertEqual(third.state, "done", third.error_message)

    def test_price_column_updates_cost(self):
        self.config.price_update = "cost"
        record = self._import([["Product Code", "Cost", "Quantity"], ["STK-PEAR", "3.50", 2]])
        self.assertEqual(record.state, "done", record.error_message)
        self.assertAlmostEqual(self.pear.standard_price, 3.5)

    def test_create_missing_product(self):
        self.config.create_missing_products = True
        record = self._import([
            ["Product Code", "Name", "Category", "Quantity"],
            ["STK-NEW", "Stocktake New", "Stocktake Category", 6],
        ])
        self.assertEqual(record.state, "done", record.error_message)
        product = self.env["product.product"].search([("default_code", "=", "STK-NEW")])
        self.assertTrue(product.is_storable)
        self.assertEqual(product.categ_id.name, "Stocktake Category")
        self.assertEqual(self._on_hand(product), 6)

    def test_csv_sheet(self):
        record = self._import(
            content=b"Product Code;Quantity\nSTK-PEAR;11\n", filename="stock.csv")
        self.assertEqual(record.state, "done", record.error_message)
        self.assertEqual(self._on_hand(self.pear), 11)

    def _email(self, sender):
        content = self._xlsx([["Product Code", "Quantity"], ["STK-APPLE", 40]])
        return self.env["stock.email.import"].message_new({
            "subject": "Stocktake 14/09",
            "email_from": "Boss <%s>" % sender,
            "attachments": [("stocktake.xlsx", content, {})],
        }, custom_values={"config_id": self.config.id, "company_id": self.company.id})

    def test_email_from_allowed_sender_is_applied(self):
        record = self._email("BOSS@example.com")
        self.assertEqual(record.state, "pending")
        self.assertEqual(record.file_name, "stocktake.xlsx")
        self.env["stock.email.import"]._cron_process_pending()
        self.assertEqual(record.state, "done", record.error_message)
        self.assertEqual(self._on_hand(self.apple), 40)

    def test_email_from_unknown_sender_is_rejected(self):
        record = self._email("stranger@example.com")
        self.assertEqual(record.state, "rejected")
        self.env["stock.email.import"]._cron_process_pending()
        self.assertEqual(self._on_hand(self.apple), 10)
