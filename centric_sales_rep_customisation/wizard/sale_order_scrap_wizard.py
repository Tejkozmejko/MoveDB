"""The dialog behind the Scrap button: pick a line, type the kilograms lost.

Deliberately small. Everything it knows about wastage lives on the order and
the order line (``sale_order_scrap``, ``sale_order_line_scrap``); this is only
the form that collects the two answers and hands them over.
"""

from odoo import api, fields, models
from odoo.tools import formatLang


class SaleOrderScrapWizard(models.TransientModel):
    _name = "centric.sale.order.scrap.wizard"
    _description = "Record Wastage on a Sales Order"

    order_id = fields.Many2one(
        comodel_name="sale.order",
        string="Sales Order",
        required=True,
        readonly=True,
    )
    available_line_ids = fields.Many2many(
        comodel_name="sale.order.line",
        compute="_compute_available_line_ids",
        string="Available Lines",
    )
    line_id = fields.Many2one(
        comodel_name="sale.order.line",
        string="Product",
        required=True,
        domain="[('id', 'in', available_line_ids)]",
        help="The order line the wastage came off.",
    )
    ordered_qty_display = fields.Char(
        string="On the Order",
        compute="_compute_line_summary",
    )
    existing_scrap_kg = fields.Float(
        string="Wastage Already Recorded",
        compute="_compute_line_summary",
        digits="Product Unit",
    )
    qty_kg = fields.Float(
        string="Wastage (kg)",
        digits="Product Unit",
        help="How much of the product was lost preparing this line. Always in "
             "kilograms, whatever unit the product is sold in.",
    )

    @api.model
    def default_get(self, fields_list):
        """Preselect the line when there is only one it could be."""
        values = super().default_get(fields_list)
        order = self.env["sale.order"].browse(values.get("order_id"))
        if "line_id" in fields_list and order and not values.get("line_id"):
            lines = order._centric_scrappable_lines()
            if len(lines) == 1:
                values["line_id"] = lines.id
        return values

    @api.depends("order_id")
    def _compute_available_line_ids(self):
        for wizard in self:
            order = wizard.order_id
            wizard.available_line_ids = (
                order._centric_scrappable_lines() if order else self.env["sale.order.line"]
            )

    @api.depends("line_id")
    def _compute_line_summary(self):
        for wizard in self:
            line = wizard.line_id
            if not line:
                wizard.ordered_qty_display = ""
                wizard.existing_scrap_kg = 0.0
                continue
            wizard.ordered_qty_display = "%s %s" % (
                formatLang(
                    self.env,
                    line.product_uom_qty,
                    dp="Product Unit",
                ),
                line.product_uom_id.display_name or "",
            )
            wizard.existing_scrap_kg = sum(
                line.centric_scrap_ids.mapped("centric_scrap_qty_kg")
            )

    def action_confirm(self):
        self.ensure_one()
        self.order_id._centric_add_scrap(self.line_id, self.qty_kg)
        return {"type": "ir.actions.act_window_close"}
