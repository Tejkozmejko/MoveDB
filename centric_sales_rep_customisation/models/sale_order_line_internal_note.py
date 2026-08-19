"""Keep the warehouse's line notes off the customer's invoice.

Two ways of noting something against a product line both used to end up printed
on the invoice:

* a separate note row under the line (``display_type == 'line_note'``), which
  Odoo copies to the invoice on purpose — handled in ``sale_order_info_note``;
* free text typed underneath the product description on the line itself, which
  travels inside ``sale.order.line.name`` and is copied verbatim.

This module handles the second. The description is only cut back when the part
that Odoo generated can still be recognised at the front of it — if someone has
edited the description itself, the text is left exactly as it is rather than
risk throwing away something real.

The note is untouched everywhere it is wanted: it stays on the sales order, and
it still reaches the warehouse through ``description_picking`` (see
``centric_delivery_method_customisation``), so the Operations tab and the
delivery slip keep showing it.
"""

from odoo import models


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _prepare_invoice_line(self, **optional_values):
        vals = super()._prepare_invoice_line(**optional_values)
        description = self._centric_customer_facing_description()
        if description is not None:
            vals["name"] = self.env["account.move.line"]._get_journal_items_full_name(
                description, self.product_id.display_name
            )
        return vals

    def _centric_customer_facing_description(self):
        """The line description without its internal note.

        Returns ``None`` when there is nothing to strip or when the description
        cannot be taken apart safely, so the caller leaves the name alone.
        """
        self.ensure_one()
        if self.display_type or not self.product_id:
            return None

        name = (self.name or "").strip()
        if not name:
            return None

        generated = (self._get_sale_order_line_multiline_description_sale() or "").strip()
        if not generated or name == generated or not name.startswith(generated):
            return None
        return generated

    def _centric_internal_line_note(self):
        """The note itself — the text typed under the product description."""
        self.ensure_one()
        description = self._centric_customer_facing_description()
        if description is None:
            return ""
        return (self.name or "").strip()[len(description):].strip()
