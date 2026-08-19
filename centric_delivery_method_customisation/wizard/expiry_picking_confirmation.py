from odoo import models


class ExpiryPickingConfirmation(models.TransientModel):
    _inherit = "expiry.picking.confirmation"

    def process(self):
        # "Confirm" on the expiry popup: deliver including the expired lots.
        return self._centric_print_pickings_after_expiry(super().process())

    def process_no_expired(self):
        # "Proceed except expired": drop the expired lots, deliver the rest.
        return self._centric_print_pickings_after_expiry(super().process_no_expired())

    def _centric_print_pickings_after_expiry(self, result):
        """Print/download the pick list once the operator confirms the native
        expiry popup on a "Print & Validate".

        When a PICK is validated from the board's "Print & Validate" button and
        it moves an expired lot, ``button_validate`` returns Odoo's
        ``expiry.picking.confirmation`` popup instead of validating straight
        away, so the button cannot print yet (see
        ``action_centric_print_and_validate``). That button stashes the pickings
        to print in ``centric_print_pickings_after_validate``; product_expiry's
        ``_action_generate_expired_wizard`` copies the whole context onto this
        wizard's action, so the flag is available here for both popup answers -
        "Confirm" (``process``) and "Proceed except expired"
        (``process_no_expired``).

        Unlike the backorder popup (which is terminal), confirming expiry can
        itself return ANOTHER action - typically the out-of-stock backorder
        confirmation popup. That popup carries the same flag and prints on its
        own confirm (see ``stock.backorder.confirmation`` override), so when the
        result is still an action we return it untouched and let that downstream
        step do the printing. We only add the print step when validation has
        actually completed (``super()`` returned a non-action result). When the
        flag is absent (any other expiry popup in the system) the original
        wizard result is returned untouched.
        """
        if isinstance(result, dict):
            # A further action followed (e.g. the backorder popup); let that
            # step handle printing so the pick list is not printed twice.
            return result
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
        # (which auto-downloads the PDF and opens the print dialog) AND closes
        # this popup so the list reloads and the picks proceed to PACK.
        return pickings._centric_picking_print_client_action(report_action)
