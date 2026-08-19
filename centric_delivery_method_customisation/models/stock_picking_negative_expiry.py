# -*- coding: utf-8 -*-
import datetime

from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _check_expired_lots(self):
        """Keep the negative-stock buckets out of product_expiry's expired check.

        Selling more than is on hand parks the shortfall on a single
        ``<code>-N`` lot (see ``stock_move_negative``). That lot stands in for
        goods that have not arrived yet, so it has no expiry of its own and
        Odoo stamps it with ``now() + expiration_time`` -- which, with no
        expiration time configured on these products, is *right now*. The lot
        is therefore born expired, and every delivery that touches it stops on
        product_expiry's "which is expired or should at least be removed from
        stock" popup even though nothing expired is actually being shipped.

        ``_check_expired_lots`` is the single gate feeding
        ``_pre_action_done_hook``, so suppressing it here removes the popup
        without touching ``button_validate`` or the print-and-validate flow.

        Mode comes from the ``centric_negative_stock_lot.auto_confirm_expiry``
        system parameter, so it is switchable without a code change:

        ``all``
            Default, per the client's decision of 2026-08-11: never ask, for
            any lot. Expiry is controlled at the picking bench rather than at
            validation time, and the popup was stopping pickers on stock that
            had not arrived yet -- see ``negative`` for why that happens. Note
            what this gives up: nothing now blocks a genuinely expired lot from
            being delivered, so the expiration dates on the *products* (these
            have ``use_expiration_date`` on but no Expiration Time, which is
            the root of the whole problem) are the only remaining control.
        ``negative``
            Auto-confirm only the ``<code>-N`` buckets; a picking carrying a
            genuinely expired real lot still stops and asks.
        ``off``
            Native behaviour, always ask.
        """
        pickings = super()._check_expired_lots()
        if not pickings:
            return pickings
        mode = self._centric_expiry_auto_confirm_mode()
        if mode == "off":
            return pickings
        if mode == "all":
            return self.browse()
        return pickings.filtered(
            lambda picking: picking._centric_has_real_expired_lot()
        )

    def _centric_has_real_expired_lot(self):
        """Native's expired-line test, minus the ``<code>-N`` negative buckets.

        Mirrors ``product_expiry``'s own filter (lot flagged expired, or a
        removal date already reached) so that a change in core surfaces here as
        a behaviour difference rather than a silent divergence. A line with no
        lot at all is left to the native rule: on a create-lots receipt its
        removal date is derived from the typed expiry, and that warning is not
        ours to suppress.
        """
        self.ensure_one()
        Lot = self.env["stock.lot"]
        now = datetime.datetime.now()
        for move_line in self.move_line_ids:
            lot = move_line.lot_id
            if lot and Lot._centric_is_negative_lot_name(lot.name):
                continue
            if lot.product_expiry_alert or (
                move_line.removal_date and move_line.removal_date <= now
            ):
                return True
        return False

    def _centric_expiry_auto_confirm_mode(self):
        param = self.env["ir.config_parameter"].sudo().get_param(
            "centric_negative_stock_lot.auto_confirm_expiry", "all")
        mode = str(param or "").strip().lower()
        if mode not in ("off", "negative", "all"):
            return "all"
        return mode
