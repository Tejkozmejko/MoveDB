from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = "sale.order"

    show_not_delivered_button = fields.Boolean(
        string="Show Not Delivered Button",
        compute="_compute_not_delivered_button",
    )
    not_delivered_available_picking_id = fields.Many2one(
        "stock.picking",
        string="Delivery Available for Not Delivered",
        compute="_compute_not_delivered_button",
    )
    not_delivered_next_invoice_date = fields.Date(
        string="Not Delivered Next Invoice Date",
        copy=False,
    )


    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        forced_date = self.env.context.get("not_delivered_invoice_date") or self.not_delivered_next_invoice_date
        if forced_date and "invoice_date" in self.env["account.move"]._fields:
            vals["invoice_date"] = forced_date
        return vals

    @api.depends(
        "state",
        "picking_ids.state",
        "picking_ids.date_done",
        "picking_ids.scheduled_date",
        "picking_ids.not_delivered_origin_id",
        "picking_ids.not_delivered_replacement_id",
    )
    def _compute_not_delivered_button(self):
        for order in self:
            picking = order._get_not_delivered_candidate_pickings()[:1]
            order.not_delivered_available_picking_id = picking.id if picking else False
            order.show_not_delivered_button = bool(order.state in ("sale", "done") and picking)

    def _get_not_delivered_candidate_pickings(self):
        self.ensure_one()
        pickings = self.picking_ids.filtered(
            lambda p: p.state == "done"
            and p.picking_type_code == "outgoing"
            and not p.not_delivered_replacement_id
        )
        return pickings.sorted(
            key=lambda p: p.date_done or p.scheduled_date or p.create_date or fields.Datetime.now(),
            reverse=True,
        )

    def action_not_delivered_from_sale_order(self):
        self.ensure_one()

        picking = self.not_delivered_available_picking_id or self._get_not_delivered_candidate_pickings()[:1]
        if not picking:
            raise UserError(_(
                "No completed Delivery Order was found for this Sales Order. "
                "Use Not Delivered only after the Delivery Order is validated."
            ))

        # Process the Not Delivered flow, but do not use the action returned by
        # stock.picking.action_not_delivered(). The user clicked the button from
        # the Sales Order and should remain on the Sales Order after processing.
        picking.action_not_delivered()
        replacement = picking.not_delivered_replacement_id

        self.message_post(body=_(
            "Not Delivered processed. Original delivery: %(original)s. Replacement delivery: %(replacement)s."
        ) % {
            "original": picking.display_name,
            "replacement": replacement.display_name if replacement else _("Not created"),
        })

        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.id,
            "target": "current",
        }
