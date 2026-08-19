"""The order side of wastage: the Scrap button and the line it adds.

See ``sale_order_line_scrap`` for what a scrap line is and why it works the way
it does. This module is the entry point -- the button that sits beside Catalog
under the order lines -- and the bookkeeping that puts the new line in the
right place.
"""

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_centric_add_scrap(self):
        self.ensure_one()
        if self.locked:
            raise UserError(_(
                "This order is locked, so no line can be added to it. Unlock it "
                "first if wastage still has to be recorded."
            ))
        if not self._centric_scrappable_lines():
            raise UserError(_(
                "There is no product on this order yet. Wastage is always "
                "recorded against a product line, so add the product first."
            ))
        return {
            "type": "ir.actions.act_window",
            "name": _("Record Wastage"),
            "res_model": "centric.sale.order.scrap.wizard",
            "view_mode": "form",
            "views": [(
                self.env.ref(
                    "centric_sales_rep_customisation.centric_sale_order_scrap_wizard_form"
                ).id,
                "form",
            )],
            "target": "new",
            "context": {"default_order_id": self.id},
        }

    def _centric_scrappable_lines(self):
        """The lines wastage can be recorded against.

        Goods only: a section, a note, a service or a scrap line of its own has
        nothing that can be lost in preparation.
        """
        self.ensure_one()
        return self.order_line.filtered(
            lambda line: (
                not line.display_type
                and not line.centric_is_scrap
                and line.product_id
                and line.product_id.type == "consu"
            )
        )

    def _centric_add_scrap(self, line, qty_kg):
        """Record ``qty_kg`` kilograms of wastage against ``line``.

        A line that already carries wastage has it topped up rather than
        doubled: one product line, one wastage figure, which is also the figure
        someone can go back and correct in the order line list.
        """
        self.ensure_one()
        if line not in self.order_line:
            raise UserError(_("That line is not on this order."))
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        if float_compare(qty_kg, 0.0, precision_digits=precision) <= 0:
            raise UserError(_("Enter how many kilograms were wasted."))

        existing = line.centric_scrap_ids[:1]
        if existing:
            uom, quantity = self.env["sale.order.line"]._centric_scrap_uom_and_qty(
                existing.product_id, existing.centric_scrap_qty_kg + qty_kg,
            )
            # The unit is written alongside the quantity: the two are one answer
            # from the same conversion, and writing a quantity against a unit it
            # was not measured in is how a wastage figure quietly becomes wrong.
            existing.write({"product_uom_id": uom.id, "product_uom_qty": quantity})
            return existing

        product = line.product_id
        uom, quantity = self.env["sale.order.line"]._centric_scrap_uom_and_qty(
            product, qty_kg,
        )
        # ``sale.order.line.create`` also consults ``default_display_type`` from
        # the context, and this runs from a dialog opened over the order form:
        # a stray default from the lines list would turn the wastage into a note
        # and zero its quantity.
        scrap_line = self.env["sale.order.line"].with_context(
            default_display_type=False,
        ).create({
            "order_id": self.id,
            "product_id": product.id,
            "product_uom_id": uom.id,
            "product_uom_qty": quantity,
            "price_unit": 0.0,
            "discount": 0.0,
            "centric_is_scrap": True,
            "centric_scrap_line_id": line.id,
            "sequence": line.sequence,
        })
        self._centric_place_scrap_line(scrap_line, line)
        return scrap_line

    def _centric_place_scrap_line(self, scrap_line, parent_line):
        """Move the new line directly under the one it belongs to.

        Order lines sort on ``(sequence, id)``, and Odoo hands every line the
        same default sequence, so a freshly created line lands at the bottom of
        the order however its sequence is set. The whole order is therefore
        renumbered with the scrap line slotted into place -- after the parent
        and after any wastage already recorded against it.
        """
        self.ensure_one()
        ordered = [
            line for line in self.order_line.sorted(key=lambda l: (l.sequence, l.id))
            if line != scrap_line
        ]
        if parent_line not in ordered:
            return
        index = ordered.index(parent_line) + 1
        while index < len(ordered) and ordered[index].centric_scrap_line_id == parent_line:
            index += 1
        ordered.insert(index, scrap_line)
        for position, line in enumerate(ordered, start=1):
            if line.sequence != position * 10:
                line.sequence = position * 10

    def _get_update_prices_lines(self):
        """Reapplying the pricelist must leave wastage at zero."""
        lines = super()._get_update_prices_lines()
        return lines.filtered(lambda line: not line.centric_is_scrap)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    @api.readonly
    def action_centric_add_scrap(self):
        """Reached from the button under the order lines.

        The control row belongs to the lines list, so the click arrives on
        ``sale.order.line`` with nothing selected and the order passed in the
        context -- the same route ``action_add_from_catalog`` takes.
        """
        order = self.env["sale.order"].browse(self.env.context.get("order_id"))
        return order.action_centric_add_scrap()
