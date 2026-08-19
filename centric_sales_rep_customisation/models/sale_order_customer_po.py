from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    centric_customer_po = fields.Char(
        string="Purchase Order No",
        copy=False,
        help="The customer's own purchase order number, entered manually. It "
             "persists through the order stages and is carried onto the invoice.",
    )

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.centric_customer_po:
            vals["centric_customer_po"] = self.centric_customer_po
        return vals

    def _centric_split_order_carried_fields(self):
        # The customer raised ONE purchase order. When a delivery split moves
        # some categories onto a second sales order, both halves are still
        # being supplied against that same PO number, and the customer matches
        # our paperwork to it - so both invoices have to quote it. ``copy=False``
        # stays: duplicating an order by hand should still start without one.
        return super()._centric_split_order_carried_fields() + ["centric_customer_po"]
