import re

from odoo import api, fields, models

TARGETS = [
    ("product_code", "Product Code (Internal Reference)"),
    ("barcode", "Barcode"),
    ("product_name", "Product Name"),
    ("category", "Product Category"),
    ("quantity", "Counted Quantity"),
    ("location", "Location"),
    ("lot", "Lot / Serial Number"),
    ("price", "Price (follows the mailbox setting)"),
    ("sales_price", "Sales Price"),
    ("cost_price", "Cost Price"),
]
PRICE_TARGETS = ("price", "sales_price", "cost_price")


def normalize_header(value):
    """'Product Code ' / 'PRODUCT_CODE' / 'product-code' -> 'product code'."""
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


class StockEmailImportColumn(models.Model):
    """Which sheet headers feed which import field.

    Kept as data rather than code so a new sheet layout ("SKU", "Bin",
    "Stock Count" ...) is a configuration change, not a module upgrade.
    """

    _name = "stock.email.import.column"
    _description = "Stock Email Import Column Mapping"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    target = fields.Selection(TARGETS, required=True)
    header_names = fields.Char(
        required=True,
        help="Comma-separated header texts that map to this field. Matching "
             "ignores case, spaces and punctuation, but is otherwise exact: "
             "'Product Code' matches 'product_code' but not 'Product'.",
    )
    active = fields.Boolean(default=True)

    @api.model
    def _header_map(self):
        """{normalized header: target}; the first mapping by sequence wins."""
        result = {}
        for column in self.search([]):
            for name in (column.header_names or "").split(","):
                key = normalize_header(name)
                if key and key not in result:
                    result[key] = column.target
        return result
