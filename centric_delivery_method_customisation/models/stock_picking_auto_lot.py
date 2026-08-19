# -*- coding: utf-8 -*-
from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        # Assign real available lots to eligible un-lotted move lines BEFORE core
        # validation runs its "You need to supply a Lot/Serial number" gate
        # (stock.picking._sanity_check, which fires early in button_validate --
        # ahead of _action_done). Doing it here is what actually prevents the
        # operator from being blocked when stock is available. It also runs ahead
        # of any negative-stock "-N" fallback (which acts at _action_done), so
        # real stock is always consumed before going negative.
        self.move_ids._centric_assign_available_lots()
        return super().button_validate()
