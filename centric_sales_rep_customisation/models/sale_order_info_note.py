"""Info Note — the one note on a sales order that IS meant for the customer.

Notes typed against the product lines are working instructions for the warehouse
("4 boxes x500 packets each box") and must not reach the customer's invoice; see
``sale_order_line_internal_note``. This field is the deliberate opposite: a note
entered at the top of the order that is carried onto the invoice and printed on
it, for things the customer needs to read — a VAT number, a reference, a
delivery instruction they asked to have on the paperwork.
"""

from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    centric_info_note = fields.Text(
        string="Info Note",
        copy=False,
        help="A note for the customer, printed on the invoice and the order "
             "confirmation — for example a VAT number or a reference they need "
             "to see. Notes typed against the product lines stay internal and "
             "are never printed on the invoice.",
    )

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.centric_info_note:
            vals["centric_info_note"] = self.centric_info_note
        return vals

    def _centric_split_order_carried_fields(self):
        # The note exists to be read by the customer on their paperwork. A
        # delivery split hands them a second invoice for the same order, and a
        # note that appears on one but not the other is worse than none at all.
        return super()._centric_split_order_carried_fields() + ["centric_info_note"]

    def _get_invoiceable_lines(self, final=False):
        """Keep internal note lines on the sales order.

        Odoo deliberately carries ``line_note`` rows onto the invoice (see
        ``sale.order._get_invoiceable_lines``, which lets them through even with
        nothing to invoice). Here those notes are instructions for the warehouse,
        so they are dropped on the way to the invoice and the customer-facing
        note goes in ``centric_info_note`` instead.
        """
        lines = super()._get_invoiceable_lines(final=final)
        return lines.filtered(lambda line: line.display_type != "line_note")
