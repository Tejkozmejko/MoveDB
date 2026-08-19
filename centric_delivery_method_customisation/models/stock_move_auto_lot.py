# -*- coding: utf-8 -*-
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    # ------------------------------------------------------------------ hooks
    def _action_assign(self, force_qty=False):
        # After standard reservation (which already lot-assigns the reserved
        # quantity), fill any lot-tracked line that still has a quantity but no
        # lot -- e.g. done quantities typed in by an operator outside reservation.
        res = super()._action_assign(force_qty=force_qty)
        self._centric_assign_available_lots()
        return res

    def _action_done(self, cancel_backorder=False):
        # Final safety net, and the funnel every button_validate flow passes
        # through. Running BEFORE super() guarantees real available lots are
        # placed before core validation checks for a required lot, and before any
        # negative-stock fallback that acts at line-level _action_done -- so real
        # stock is always consumed before going negative.
        self._centric_assign_available_lots()
        return super()._action_done(cancel_backorder=cancel_backorder)

    # ---------------------------------------------------------------- helpers
    @api.model
    def _centric_auto_assign_lots_enabled(self):
        value = self.env["ir.config_parameter"].sudo().get_param(
            "centric_auto_lot_assignment.auto_assign_lots", default="True")
        return str(value).strip().lower() not in ("false", "0", "no", "off", "", "none")

    def _centric_is_lot_autoassign_candidate(self):
        """Only lot-tracked lines on an outgoing/internal transfer leaving an
        internal location qualify. This excludes serial and untracked products,
        incoming receipts, dropshipping and customer returns (their source is not
        internal), and non-transfer moves (manufacturing, scrap: no picking)."""
        self.ensure_one()
        if self.state in ("done", "cancel"):
            return False
        if self.product_id.tracking != "lot":
            return False
        picking = self.picking_id
        if not picking:
            return False
        if picking.picking_type_code not in ("outgoing", "internal"):
            return False
        if self.location_id.usage != "internal":
            return False
        return True

    @api.model
    def _centric_is_negative_lot(self, lot):
        # Never draw from the synthetic per-product "<code>-N" negative-stock lot
        # created by centric_negative_stock_lot; that bucket represents a debt,
        # not on-hand stock.
        return bool(lot) and (lot.name or "").endswith("-N")

    def _centric_assign_available_lots(self):
        """Give each eligible, un-lotted move line a real available lot.

        Idempotent and non-destructive:
          * lines that already carry a lot or lot_name are never touched;
          * no demand is added or duplicated (a split preserves the line total);
          * no lots are created.

        Stock is drawn only from positive available (unreserved) quant quantity
        in the move's source location, ordered by the location's removal strategy
        (FEFO by removal date -> FIFO by in_date -> oldest, via
        stock.quant._gather), scoped to the move's company. A line is split
        across several lots when one lot cannot cover it. Whatever real stock
        cannot cover is left un-lotted for standard Odoo / a negative-stock
        fallback to handle.
        """
        if not self or not self._centric_auto_assign_lots_enabled():
            return

        Quant = self.env["stock.quant"]
        # Shared availability ledger so several lines/moves handled in the same
        # batch do not each claim the *same* free quantity of a lot.
        # Keyed (company_id, product_id, location_id, lot_id) -> qty already taken.
        claimed = {}

        for move in self:
            if not move._centric_is_lot_autoassign_candidate():
                continue

            unlotted = move.move_line_ids.filtered(
                lambda ml: not ml.lot_id
                and not ml.lot_name
                and ml.product_uom_id.compare(ml.quantity, 0) > 0
            )
            if not unlotted:
                continue

            candidates = move._centric_available_lot_candidates(Quant, claimed)
            if not candidates:
                _logger.debug(
                    "centric_auto_lot: no available lot for %s at %s (move %s); "
                    "left for standard handling",
                    move.product_id.display_name, move.location_id.display_name, move.id,
                )
                continue

            move._centric_distribute_lots_to_lines(unlotted, candidates, claimed)

    def _centric_available_lot_candidates(self, Quant, claimed):
        """Ordered list of [lot, ledger_key, free_qty] to draw from, following
        the source location's removal strategy and excluding the -N lot and any
        quant with no free quantity."""
        self.ensure_one()
        product = self.product_id
        location = self.location_id
        company = self.company_id
        rounding = product.uom_id

        quants = Quant.with_company(company)._gather(product, location, strict=False)
        candidates = []
        for quant in quants:
            lot = quant.lot_id
            if not lot:
                continue
            if quant.company_id and quant.company_id != company:
                continue
            if self._centric_is_negative_lot(lot):
                continue
            key = (company.id, product.id, location.id, lot.id)
            free = quant.quantity - quant.reserved_quantity - claimed.get(key, 0.0)
            if rounding.compare(free, 0) <= 0:
                continue
            candidates.append([lot, key, free])
        return candidates

    def _centric_distribute_lots_to_lines(self, unlotted_lines, candidates, claimed):
        """Stamp/split the given un-lotted lines onto the ordered candidate lots.

        ``candidates`` items are mutable [lot, key, free] lists; ``claimed`` is the
        shared ledger, both updated in place so a later call sees what this one
        consumed.
        """
        self.ensure_one()
        move = self
        MoveLine = self.env["stock.move.line"]
        rounding = move.product_id.uom_id
        idx = 0

        for line in unlotted_lines:
            remaining = line.quantity
            reused_line = False
            while rounding.compare(remaining, 0) > 0 and idx < len(candidates):
                lot, key, free = candidates[idx]
                if rounding.compare(free, 0) <= 0:
                    idx += 1
                    continue
                take = min(free, remaining)
                if not reused_line:
                    # First chunk reuses the existing line (shrinking it if the
                    # lot only partly covers it), so we never duplicate demand.
                    if rounding.compare(take, line.quantity) < 0:
                        line.quantity = take
                    line.lot_id = lot.id
                    reused_line = True
                else:
                    # Further chunks need their own line for the extra lot.
                    MoveLine.create(move._centric_lot_line_vals(line, lot, take))
                claimed[key] = claimed.get(key, 0.0) + take
                candidates[idx][2] = free - take
                remaining -= take
                if rounding.compare(candidates[idx][2], 0) <= 0:
                    idx += 1
            if rounding.compare(remaining, 0) > 0 and reused_line:
                # Real stock ran out mid-line: the original line was shrunk to its
                # first chunk, so put the leftover demand back on its own un-lotted
                # line for standard Odoo / negative-stock handling.
                MoveLine.create(move._centric_lot_line_vals(line, False, remaining))

    def _centric_lot_line_vals(self, template_line, lot, qty):
        self.ensure_one()
        vals = {
            "move_id": self.id,
            "picking_id": self.picking_id.id,
            "product_id": self.product_id.id,
            "product_uom_id": template_line.product_uom_id.id or self.product_uom.id,
            "location_id": self.location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "quantity": qty,
            "company_id": self.company_id.id,
        }
        if lot:
            vals["lot_id"] = lot.id
        return vals
