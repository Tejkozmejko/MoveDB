# -*- coding: utf-8 -*-
"""Direct-sale stock deduction.

A customer invoice created straight from Accounting (no Sales Order) is a pure
financial document in standard Odoo: nothing leaves stock, and nothing shows in
the product's move history. This module makes such a *direct sale* behave like a
real sale -- posting the invoice auto-creates and validates a delivery that
deducts stock (FEFO, negative allowed, exactly like the company's normal
deliveries), so on-hand and the move history stay correct and traceable.

Guard rails:
  * Only customer invoices/receipts/credit notes are considered.
  * Invoices that come FROM a Sales Order are skipped entirely -- their stock is
    already handled by the SO's delivery, so touching them would double-count.
  * Only storable product lines move stock.
  * Resetting to draft or cancelling the invoice reverses the delivery (restores
    stock) using the exact lots that left.
  * A credit note that fully reverses a direct-sale invoice restores its stock.

Everything is best-effort: a failure here posts a warning on the invoice chatter
but never blocks posting/drafting/cancelling the invoice itself.
"""
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)

# Customer documents that should DEDUCT stock when posted as a direct sale.
_CENTRIC_DEDUCT_MOVE_TYPES = ("out_invoice", "out_receipt")
# Credit notes that should RESTORE stock when they reverse a direct sale.
_CENTRIC_RESTOCK_MOVE_TYPES = ("out_refund",)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    centric_direct_sale_invoice_id = fields.Many2one(
        "account.move",
        string="Direct-Sale Invoice",
        index=True,
        copy=False,
        readonly=True,
        help="The Accounting invoice/credit note that auto-generated this stock "
             "movement (a direct sale with no Sales Order).",
    )
    centric_direct_sale_role = fields.Selection(
        [
            ("delivery", "Delivery (stock out)"),
            ("return", "Return (stock in)"),
        ],
        string="Direct-Sale Role",
        copy=False,
        readonly=True,
    )
    centric_direct_sale_reversed = fields.Boolean(
        string="Direct-Sale Reversed",
        copy=False,
        readonly=True,
        help="Set once this auto-generated movement has been undone (the invoice "
             "was reset to draft, cancelled, or credited) so it is never undone "
             "or counted twice.",
    )


class AccountMove(models.Model):
    _inherit = "account.move"

    centric_direct_sale_picking_ids = fields.One2many(
        "stock.picking",
        "centric_direct_sale_invoice_id",
        string="Direct-Sale Stock Movements",
        copy=False,
    )
    centric_direct_sale_delivery_count = fields.Integer(
        compute="_compute_centric_direct_sale_delivery_count",
    )

    def _compute_centric_direct_sale_delivery_count(self):
        for move in self:
            move.centric_direct_sale_delivery_count = len(
                move.centric_direct_sale_picking_ids.filtered(
                    lambda picking: picking.state != "cancel"
                )
            )

    # ------------------------------------------------------------------
    # Hooks into the standard invoice lifecycle
    # ------------------------------------------------------------------
    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted:
            move._centric_direct_sale_sync_on_post()
        return posted

    def button_draft(self):
        # Restore stock BEFORE the document leaves the posted state.
        self._centric_direct_sale_reverse_deliveries()
        return super().button_draft()

    def button_cancel(self):
        self._centric_direct_sale_reverse_deliveries()
        return super().button_cancel()

    def action_centric_view_direct_sale_pickings(self):
        self.ensure_one()
        pickings = self.centric_direct_sale_picking_ids
        action = {
            "type": "ir.actions.act_window",
            "name": _("Direct-Sale Stock Movements"),
            "res_model": "stock.picking",
            "domain": [("id", "in", pickings.ids)],
            "context": {"create": False},
        }
        if len(pickings) == 1:
            action.update({
                "view_mode": "form",
                "res_id": pickings.id,
            })
        else:
            action["view_mode"] = "list,form"
        return action

    # ------------------------------------------------------------------
    # Direct-sale detection
    # ------------------------------------------------------------------
    def _centric_is_direct_sale(self):
        """True for a customer invoice/receipt/credit note that is NOT tied to a
        Sales Order and carries at least one storable product line."""
        self.ensure_one()
        if self.move_type not in _CENTRIC_DEDUCT_MOVE_TYPES + _CENTRIC_RESTOCK_MOVE_TYPES:
            return False
        if self.invoice_line_ids.sale_line_ids:
            return False
        return bool(self._centric_direct_sale_product_lines())

    def _centric_direct_sale_product_lines(self):
        self.ensure_one()
        return self.invoice_line_ids.filtered(
            lambda line: (
                line.display_type == "product"
                and line.product_id
                and line.product_id.is_storable
                and line.product_uom_id
                and line.product_uom_id.compare(line.quantity, 0.0) > 0
            )
        )

    # ------------------------------------------------------------------
    # Posting -> create the stock movement
    # ------------------------------------------------------------------
    def _centric_direct_sale_sync_on_post(self):
        self.ensure_one()
        if not self._centric_is_direct_sale():
            return
        try:
            if self.move_type in _CENTRIC_DEDUCT_MOVE_TYPES:
                self._centric_direct_sale_create_delivery()
            else:
                self._centric_direct_sale_restock_for_refund()
        except Exception as error:  # never block the invoice over a stock issue
            _logger.exception(
                "Direct-sale stock sync failed for %s", self.name or self.id)
            self._centric_direct_sale_warn(error)

    def _centric_direct_sale_create_delivery(self):
        self.ensure_one()
        # Idempotent: never create a second delivery while an un-reversed one
        # already exists (e.g. re-post after a validation that needed attention).
        existing = self.centric_direct_sale_picking_ids.filtered(
            lambda picking: (
                picking.centric_direct_sale_role == "delivery"
                and not picking.centric_direct_sale_reversed
                and picking.state != "cancel"
            )
        )
        if existing:
            return existing
        lines = self._centric_direct_sale_product_lines()
        if not lines:
            return self.env["stock.picking"]
        warehouse = self._centric_direct_sale_warehouse()
        picking_type = warehouse.out_type_id
        source = warehouse.lot_stock_id
        destination = self._centric_direct_sale_customer_location(picking_type)
        picking = self._centric_direct_sale_picking_model().create({
            "picking_type_id": picking_type.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "partner_id": self.partner_id.id,
            "origin": self.name,
            "company_id": self.company_id.id,
            "centric_direct_sale_invoice_id": self.id,
            "centric_direct_sale_role": "delivery",
            "move_ids": [
                Command.create(self._centric_direct_sale_move_vals(line, source, destination))
                for line in lines
            ],
        })
        self._centric_direct_sale_validate_outgoing(picking)
        if picking.state == "done":
            self.message_post(body=_(
                "Direct sale: stock deducted via delivery %s.") % picking.name)
        return picking

    def _centric_direct_sale_move_vals(self, line, source, destination):
        # NOTE: stock.move has no 'name' field in this Odoo 19 build.
        return {
            "product_id": line.product_id.id,
            "product_uom": line.product_uom_id.id,
            "product_uom_qty": line.quantity,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "company_id": self.company_id.id,
        }

    def _centric_direct_sale_validate_outgoing(self, picking):
        """Confirm, reserve (FEFO) and validate the delivery. Non-tracked lines
        are forced to their full demand so stock goes negative when short; the
        negative-stock-lot module completes lot-tracked lines at reservation, so
        they already match demand and are left untouched (no lot-less move line).
        The picking already carries the cleaned context from creation."""
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            if move.product_id.tracking == "none":
                if move.product_uom.compare(move.quantity, move.product_uom_qty) != 0:
                    move.quantity = move.product_uom_qty
            move.picked = True
        self._centric_direct_sale_finalize(picking)

    # ------------------------------------------------------------------
    # Reversal (reset to draft / cancel) -> restore stock
    # ------------------------------------------------------------------
    def _centric_direct_sale_reverse_deliveries(self):
        for move in self:
            deliveries = move.centric_direct_sale_picking_ids.filtered(
                lambda picking: (
                    picking.centric_direct_sale_role == "delivery"
                    and picking.state == "done"
                    and not picking.centric_direct_sale_reversed
                )
            )
            for delivery in deliveries:
                try:
                    mirror = move._centric_direct_sale_build_return(delivery)
                    if mirror and mirror.state == "done":
                        delivery.centric_direct_sale_reversed = True
                        move.message_post(body=_(
                            "Direct sale undone: delivery %(orig)s reversed by "
                            "%(mirror)s (stock restored).",
                            orig=delivery.name, mirror=mirror.name))
                except Exception as error:
                    _logger.exception(
                        "Direct-sale reversal failed for %s", delivery.name)
                    move._centric_direct_sale_warn(error)

    def _centric_direct_sale_restock_for_refund(self):
        """A direct credit note that fully reverses a direct-sale invoice restores
        that invoice's delivery (exact lots). Anything ambiguous (standalone or
        partial credit) is left to a manual return, with a note on the chatter."""
        self.ensure_one()
        origin = self.reversed_entry_id
        if not origin:
            self.message_post(body=_(
                "Direct sale: this credit note does not reverse a known "
                "direct-sale invoice, so stock was not changed automatically. "
                "If goods came back, record the return in Inventory."))
            return self.env["stock.picking"]
        delivery = origin.centric_direct_sale_picking_ids.filtered(
            lambda picking: (
                picking.centric_direct_sale_role == "delivery"
                and picking.state == "done"
                and not picking.centric_direct_sale_reversed
            )
        )[:1]
        if not delivery:
            self.message_post(body=_(
                "Direct sale: original invoice %s has no outstanding auto-delivery "
                "to reverse, so stock was not changed.") % origin.name)
            return self.env["stock.picking"]
        if self.centric_direct_sale_picking_ids.filtered(
            lambda picking: picking.centric_direct_sale_role == "return"
            and picking.state != "cancel"
        ):
            return self.env["stock.picking"]
        if not self._centric_direct_sale_refund_matches_delivery(delivery):
            self.message_post(body=_(
                "Direct sale: this credit note does not fully match delivery %s, "
                "so stock was not changed automatically. Record any partial "
                "return in Inventory.") % delivery.name)
            return self.env["stock.picking"]
        mirror = self._centric_direct_sale_build_return(delivery)
        if mirror and mirror.state == "done":
            delivery.centric_direct_sale_reversed = True
            self.message_post(body=_(
                "Direct sale return: stock restored via %(mirror)s "
                "(credit of %(orig)s).", mirror=mirror.name, orig=origin.name))
        return mirror

    def _centric_direct_sale_refund_matches_delivery(self, delivery):
        """True when the credit note's storable quantities (per product) equal
        what the delivery actually moved, so a full restock is unambiguous."""
        self.ensure_one()
        credited = {}
        for line in self._centric_direct_sale_product_lines():
            credited[line.product_id] = credited.get(line.product_id, 0.0) + line.quantity
        delivered = {}
        for move in delivery.move_ids.filtered(lambda mv: mv.state == "done"):
            delivered[move.product_id] = delivered.get(move.product_id, 0.0) + move.quantity
        if set(credited) != set(delivered):
            return False
        return all(
            product.uom_id.compare(credited[product], delivered[product]) == 0
            for product in credited
        )

    def _centric_direct_sale_build_return(self, delivery):
        """Build and validate an incoming picking that puts back exactly what the
        delivery shipped -- same products, lots and quantities -- with the
        delivery's locations swapped."""
        self.ensure_one()
        warehouse = self._centric_direct_sale_warehouse()
        picking_type = warehouse.in_type_id
        source = delivery.location_dest_id
        destination = delivery.location_id
        move_commands = []
        for move in delivery.move_ids.filtered(lambda mv: mv.state == "done"):
            line_commands = []
            for move_line in move.move_line_ids.filtered(
                lambda ml: ml.product_uom_id.compare(ml.quantity, 0.0) > 0
            ):
                line_commands.append(Command.create({
                    "product_id": move_line.product_id.id,
                    "product_uom_id": move_line.product_uom_id.id,
                    "quantity": move_line.quantity,
                    "lot_id": move_line.lot_id.id,
                    "location_id": source.id,
                    "location_dest_id": destination.id,
                    "company_id": self.company_id.id,
                }))
            if not line_commands:
                continue
            move_commands.append(Command.create({
                "product_id": move.product_id.id,
                "product_uom": move.product_uom.id,
                "product_uom_qty": move.quantity,
                "location_id": source.id,
                "location_dest_id": destination.id,
                "company_id": self.company_id.id,
                "move_line_ids": line_commands,
            }))
        if not move_commands:
            return self.env["stock.picking"]
        picking = self._centric_direct_sale_picking_model().create({
            "picking_type_id": picking_type.id,
            "location_id": source.id,
            "location_dest_id": destination.id,
            "partner_id": self.partner_id.id,
            "origin": _("Reversal of %s") % delivery.name,
            "company_id": self.company_id.id,
            "centric_direct_sale_invoice_id": self.id,
            "centric_direct_sale_role": "return",
            "move_ids": move_commands,
        })
        picking.action_confirm()
        for move in picking.move_ids:
            if move.product_uom.compare(move.quantity, move.product_uom_qty) != 0:
                move.quantity = move.product_uom_qty
            move.picked = True
        self._centric_direct_sale_finalize(picking)
        return picking

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------
    def _centric_direct_sale_picking_model(self):
        """stock.picking with a context that is safe for auto-creating stock
        movements from inside the invoice flow. The invoice form seeds the
        context with default_* values (notably default_move_type='out_invoice');
        stock.picking ALSO has a 'move_type' field (the shipping policy), so that
        default would leak in and raise "Wrong value for stock.picking.move_type".
        Drop every default_* key and add our own skip flags so validation never
        triggers the PACK-verify / expiry / carrier-sync side effects or a
        backorder prompt."""
        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_") and key not in (
                # Never inherit another validation's routing/batch/print state.
                "picking_ids_not_to_backorder",
                "button_validate_picking_ids",
                "centric_print_pickings_after_validate",
            )
        }
        clean_context.update(
            skip_centric_expiry_check=True,
            centric_skip_pack_verify_check=True,
            centric_skip_sale_carrier_sync=True,
            skip_backorder=True,
            # Core product_expiry's expired-lot wizard fires on any picking
            # type; a FEFO-reserved alerting lot would otherwise surface as a
            # wizard dict, fail the result-is-True assertion and block invoice
            # posting.
            skip_expired=True,
            # Packed-quantity-is-final guards: the direct-sale delivery is
            # built to exact quantities by construction and has no pick/pack
            # chain, so none of these checks applies - skipped explicitly so
            # invoice posting can never be blocked by them.
            centric_skip_delivery_demand_check=True,
            centric_skip_pack_overpack_check=True,
            centric_skip_pack_final=True,
            skip_centric_delivery_split_check=True,
        )
        return self.env["stock.picking"].with_context(clean_context)

    def _centric_direct_sale_finalize(self, picking):
        result = picking.button_validate()
        if result is not True:
            raise UserError(_(
                "Stock movement %s could not be completed automatically and "
                "needs manual attention in Inventory.") % picking.name)

    def _centric_direct_sale_warehouse(self):
        self.ensure_one()
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], order="sequence, id", limit=1)
        if not warehouse:
            raise UserError(_(
                "No warehouse is configured for %s, so stock cannot be moved for "
                "this direct sale.") % self.company_id.display_name)
        return warehouse

    def _centric_direct_sale_customer_location(self, picking_type):
        self.ensure_one()
        location = self.partner_id.with_company(self.company_id).property_stock_customer
        if location:
            return location
        if picking_type.default_location_dest_id:
            return picking_type.default_location_dest_id
        return self.env.ref("stock.stock_location_customers")

    def _centric_direct_sale_warn(self, error):
        self.ensure_one()
        self.sudo().message_post(body=_(
            "⚠ Stock was NOT adjusted automatically for this direct sale. "
            "Please check inventory manually. Reason: %s") % (error,))
