from collections import OrderedDict
from datetime import datetime

from odoo import _, fields, models
from odoo.tools import float_compare, float_is_zero, format_date


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _prepare_invoice_lines_vals_list(self, **optional_values):
        vals_list = super()._prepare_invoice_lines_vals_list(**optional_values)
        if self.env.context.get("centric_skip_invoice_lot_split"):
            return vals_list

        self.ensure_one()
        if (
            len(vals_list) != 1
            or self.display_type
            or self.is_downpayment
            or not self.product_id
        ):
            return vals_list

        base_vals = vals_list[0]
        quantity = base_vals.get("quantity") or 0.0
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        if float_compare(quantity, 0.0, precision_digits=precision) <= 0:
            return vals_list

        lot_quantities = self._centric_lot_quantities_to_invoice(quantity)
        if not lot_quantities:
            return vals_list

        split_vals_list = []
        remaining_quantity = quantity
        for lot, lot_quantity in lot_quantities:
            if float_is_zero(remaining_quantity, precision_digits=precision):
                break

            invoice_quantity = min(lot_quantity, remaining_quantity)
            if float_is_zero(invoice_quantity, precision_digits=precision):
                continue

            split_vals = dict(base_vals)
            expiration_date = self._centric_lot_expiration_date(lot)
            split_vals.update({
                "quantity": invoice_quantity,
                "name": self._centric_lot_invoice_line_name(
                    base_vals.get("name"),
                    lot,
                    expiration_date,
                ),
                "centric_lot_id": lot.id,
                "centric_lot_expiration_date": expiration_date,
            })
            split_vals_list.append(split_vals)
            remaining_quantity -= invoice_quantity

        if not float_is_zero(remaining_quantity, precision_digits=precision):
            remaining_vals = dict(base_vals)
            remaining_vals["quantity"] = remaining_quantity
            split_vals_list.append(remaining_vals)

        return split_vals_list or vals_list

    def _centric_lot_quantities_to_invoice(self, invoice_quantity):
        self.ensure_one()
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        delivered_quantities = self._centric_delivered_lot_quantities()
        if not delivered_quantities:
            return []

        invoiced_quantities = self._centric_invoiced_lot_quantities()
        remaining_quantity = invoice_quantity
        quantities = []
        for lot, delivered_quantity in delivered_quantities.items():
            quantity = delivered_quantity - invoiced_quantities.get(lot, 0.0)
            if float_compare(quantity, 0.0, precision_digits=precision) <= 0:
                continue

            quantity = min(quantity, remaining_quantity)
            if float_is_zero(quantity, precision_digits=precision):
                continue

            quantities.append((lot, quantity))
            remaining_quantity -= quantity
            if float_is_zero(remaining_quantity, precision_digits=precision):
                break
        return quantities

    def _centric_delivered_lot_quantities(self):
        self.ensure_one()
        quantities = OrderedDict()
        move_lines = self.move_ids.move_line_ids.filtered(
            lambda line: (
                line.state == "done"
                and line.lot_id
                and line._should_show_lot_in_invoice()
                and line.location_dest_id.usage == "customer"
            )
        ).sorted(lambda line: (line.date, line.id))

        for move_line in move_lines:
            quantity = move_line.product_uom_id._compute_quantity(
                move_line.quantity,
                self.product_uom_id,
            )
            if float_compare(
                quantity,
                0.0,
                precision_digits=self.env["decimal.precision"].precision_get("Product Unit"),
            ) <= 0:
                continue

            quantities.setdefault(move_line.lot_id, 0.0)
            quantities[move_line.lot_id] += quantity
        return quantities

    def _centric_invoiced_lot_quantities(self):
        self.ensure_one()
        quantities = {}
        invoice_lines = self.invoice_lines.filtered(
            lambda line: line.move_id.state != "cancel" and line.centric_lot_id
        )
        for invoice_line in invoice_lines:
            invoice_uom = invoice_line.product_uom_id or self.product_uom_id
            quantity = invoice_uom._compute_quantity(
                invoice_line.quantity,
                self.product_uom_id,
            )
            if invoice_line.move_id.move_type == "out_refund":
                quantity = -quantity

            quantities.setdefault(invoice_line.centric_lot_id, 0.0)
            quantities[invoice_line.centric_lot_id] += quantity
        return quantities

    def _centric_lot_invoice_line_name(self, name, lot, expiration_date):
        self.ensure_one()
        lot_details = [_("Lot: %s") % lot.name]
        if expiration_date:
            lot_details.append(_("Expiry: %s") % format_date(self.env, expiration_date))
        return "%s\n%s" % ((name or "").strip(), " | ".join(lot_details))

    def _centric_lot_expiration_date(self, lot):
        """The lot's expiry as the day a reader here would call it.

        The expiry is stored as a UTC datetime. Truncating it with
        ``fields.Date.to_date`` keeps the UTC day, so an expiry stored at (say)
        23:00 UTC prints as the *previous* day for anyone ahead of UTC — the
        "expiry one day before" seen on the invoice. Converting to the user's
        timezone first gives the day that was actually meant, and matches what
        ``stock_picking_expiry`` already does when it decides whether stock is
        expired.
        """
        self.ensure_one()
        for field_name in ("expiration_date", "life_date"):
            value = lot[field_name] if field_name in lot._fields else False
            if not value:
                continue
            if isinstance(value, datetime):
                return fields.Datetime.context_timestamp(lot, value).date()
            return fields.Date.to_date(value)
        return False
