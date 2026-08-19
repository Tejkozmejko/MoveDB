# -*- coding: utf-8 -*-
from odoo import models


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    def _action_done(self):
        self._centric_assign_negative_stock_lots()
        return super()._action_done()

    def _centric_assign_negative_stock_lots(self):
        for ml in self:
            if ml.lot_id or ml.lot_name:
                continue
            if ml.product_id.tracking != "lot":
                continue
            if ml.product_uom_id.compare(ml.quantity, 0) <= 0:
                continue
            move = ml.move_id
            if not move or not move._centric_is_negative_stock_candidate():
                continue
            ml.lot_id = move._centric_target_negative_lot().id
