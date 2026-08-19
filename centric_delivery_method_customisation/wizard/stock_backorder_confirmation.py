from odoo import models


class StockBackorderConfirmation(models.TransientModel):
    _inherit = "stock.backorder.confirmation"

    def process(self):
        # "Create Backorder" on the out-of-stock popup.
        return self._centric_print_pickings_after_validate(super().process())

    def process_cancel_backorder(self):
        # "No Backorder" on the out-of-stock popup.
        return self._centric_print_pickings_after_validate(
            super().process_cancel_backorder()
        )

    def _centric_print_pickings_after_validate(self, result):
        """Print the pick list once the operator confirms the backorder popup.

        When a PICK is validated from the board's "Print & Validate" button and
        stock is short, ``button_validate`` returns Odoo's backorder
        confirmation popup instead of validating straight away, so the button
        cannot print yet (see ``action_centric_print_and_validate``). That button
        stashes the pickings to print in the context key
        ``centric_print_pickings_after_validate``; Odoo copies the context onto
        this wizard's action, so the flag is available here for both popup
        answers - "Create Backorder" (``process``) and "No Backorder"
        (``process_cancel_backorder``).

        The pickings are already validated by the ``super()`` call, so here we
        only add the missing print step: return the very same auto-print dialog
        action the button uses on the no-popup path, so the pick list prints
        every time. When the flag is absent (any other backorder popup in the
        system) the original wizard result is returned untouched.
        """
        picking_ids = self.env.context.get("centric_print_pickings_after_validate")
        if not picking_ids:
            return result
        pickings = self.env["stock.picking"].browse(picking_ids).exists().filtered(
            lambda picking: picking.state != "cancel"
        )
        if not pickings:
            return result
        report_action = pickings.do_print_picking()
        # Client-action variant (not the plain act_url): it opens the print tab
        # AND closes this popup so the list reloads and the picks proceed to
        # PACK. A bare act_url would print but leave the popup open.
        return pickings._centric_picking_print_client_action(report_action)
