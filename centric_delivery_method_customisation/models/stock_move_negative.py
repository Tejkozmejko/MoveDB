# -*- coding: utf-8 -*-
from odoo import _, models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _should_assign_at_confirm(self):
        self.ensure_one()
        if self._centric_is_negative_stock_candidate():
            return True
        return super()._should_assign_at_confirm()

    def _action_assign(self, force_qty=False):
        res = super()._action_assign(force_qty=force_qty)
        self._centric_backfill_negative_stock_lots()
        return res

    def _action_done(self, cancel_backorder=False):
        res = super()._action_done(cancel_backorder=cancel_backorder)
        res._centric_reconcile_negative_stock()
        return res

    def _centric_backfill_negative_stock_lots(self):
        MoveLine = self.env["stock.move.line"]
        moves_to_recompute = self.env["stock.move"]
        for move in self:
            if not move._centric_is_negative_stock_candidate():
                continue
            shortfall = move.product_uom.round(move.product_uom_qty - move.quantity)
            if move.product_uom.compare(shortfall, 0) <= 0:
                continue
            lot = move._centric_target_negative_lot()
            if lot in move.move_line_ids.lot_id:
                continue
            MoveLine.create({
                "move_id": move.id,
                "picking_id": move.picking_id.id,
                "product_id": move.product_id.id,
                "product_uom_id": move.product_uom.id,
                "location_id": move.location_id.id,
                "location_dest_id": move.location_dest_id.id,
                "lot_id": lot.id,
                "quantity": shortfall,
                "company_id": move.company_id.id,
            })
            moves_to_recompute |= move
        if moves_to_recompute:
            moves_to_recompute._recompute_state()

    def _centric_reconcile_negative_stock(self):
        if not self._centric_auto_reconcile_enabled():
            return
        Quant = self.env["stock.quant"]
        Lot = self.env["stock.lot"]
        for move in self:
            if move.state != "done":
                continue
            product = move.product_id
            if product.tracking != "lot":
                continue
            if getattr(product, "lot_valuated", False):
                continue
            location = move.location_dest_id
            if location.usage != "internal":
                continue
            neg_lot = Lot.search([
                ("product_id", "=", product.id),
                ("name", "=", Lot._centric_negative_lot_name(product)),
                "|", ("company_id", "=", False), ("company_id", "=", move.company_id.id),
            ], limit=1)
            if not neg_lot:
                continue
            neg_qty = Quant._get_available_quantity(
                product, location, lot_id=neg_lot, strict=True, allow_negative=True)
            if product.uom_id.compare(neg_qty, 0) >= 0:
                continue
            shortage = -neg_qty
            donors = Quant.search([
                ("product_id", "=", product.id),
                ("location_id", "=", location.id),
                ("lot_id", "!=", neg_lot.id),
                ("quantity", ">", 0),
            ], order="in_date asc, id asc")
            cleared = 0.0
            for dq in donors:
                if product.uom_id.compare(shortage - cleared, 0) <= 0:
                    break
                avail = dq.quantity - dq.reserved_quantity
                take = min(avail, shortage - cleared)
                if product.uom_id.compare(take, 0) <= 0:
                    continue
                Quant._update_available_quantity(product, location, -take, lot_id=dq.lot_id)
                cleared += take
            if product.uom_id.compare(cleared, 0) > 0:
                Quant._update_available_quantity(product, location, cleared, lot_id=neg_lot)
                neg_lot.message_post(body=_(
                    "Centric: auto-reconciled %(qty)s %(uom)s of negative stock at "
                    "%(loc)s against incoming stock (%(ref)s). Remaining negative: %(rem)s.",
                    qty=cleared, uom=product.uom_id.name, loc=location.display_name,
                    ref=move.reference or "", rem=shortage - cleared,
                ))

    def _centric_auto_reconcile_enabled(self):
        param = self.env["ir.config_parameter"].sudo().get_param(
            "centric_negative_stock_lot.auto_reconcile", "1")
        return str(param).strip().lower() not in ("0", "false", "no", "off", "")

    def _centric_is_negative_stock_candidate(self):
        self.ensure_one()
        return (
            self.product_id.tracking == "lot"
            and self.state not in ("done", "cancel")
            and not self.move_orig_ids
            and self._is_consuming()
            and self.location_id.usage == "internal"
            and self._centric_chain_delivers_to_customer()
        )

    def _centric_chain_delivers_to_customer(self, _depth=0):
        # A multi-step delivery (Pick/Pack/Ship) reserves the stock-drawing step (the
        # Pick) before the later steps even exist, and in this build the steps are not
        # tied together by a procurement group (the model was removed) nor always by
        # move_dest_ids. The reliable signal that lives on the lone Pick move is
        # `location_final_id` -- the chain's ultimate destination. Fall back to a
        # direct customer destination and to following move_dest_ids when linked.
        self.ensure_one()
        if self.location_dest_id.usage == "customer":
            return True
        final = self.location_final_id
        if final and final.usage == "customer":
            return True
        if _depth <= 20 and self.move_dest_ids:
            return any(
                dest._centric_chain_delivers_to_customer(_depth + 1)
                for dest in self.move_dest_ids
            )
        return False

    def _centric_target_negative_lot(self):
        """The ``<code>-N`` bucket this move's shortfall goes to.

        The real lots already assigned on this move are handed over so the
        negative lot can inherit their expiration date: the shortfall is the
        same goods, only not arrived yet. Without it the lot is created with an
        expiry of "now" and prints as already expired on the invoice.
        """
        self.ensure_one()
        source_lots = self.move_line_ids.lot_id.filtered(
            lambda lot: not self._centric_is_negative_lot(lot)
        )
        return self.env["stock.lot"]._centric_get_or_create_negative_lot(
            self.product_id, self.company_id, source_lots=source_lots)
