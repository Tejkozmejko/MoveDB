from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _centric_backorders_disabled(self):
        """Whether this transfer should validate WITHOUT creating a backorder.

        True only when the transfer's company has the master switch on AND its
        operation type is in that company's backorder-free scope. Returns (via
        Odoo's own ``_should_ignore_backorders``) are never affected - a return
        must move exactly what it states.

        Customer deliveries are excluded IN CODE, regardless of scope config:
        under the packed-quantity-is-final rule the delivery ships exactly what
        was packed, enforced by the validation hard block
        (``_centric_check_delivery_quantities``) - it must never silently
        under-ship instead. Quantity decisions happen at PICK/PACK only.
        """
        self.ensure_one()
        if self._should_ignore_backorders():
            return False
        if (
            self.picking_type_id.code == "outgoing"
            and self.location_dest_id.usage == "customer"
        ):
            return False
        company = self.company_id or self.env.company
        if not company.centric_disable_backorder:
            return False
        return self.picking_type_id in company.centric_disable_backorder_picking_type_ids

    def _check_backorder(self):
        """Suppress the "Create Backorder?" wizard for backorder-free transfers.

        Core only prompts for operation types whose backorder policy is 'ask'
        (see ``stock/models/stock_picking.py``). We drop our in-scope pickings
        from that check so no popup appears for them; any other picking being
        validated in the same call still prompts exactly as before. The real
        "no backorder, cancel the remainder" step happens in ``button_validate``
        below, via the native ``picking_ids_not_to_backorder`` context.
        """
        candidates = self.filtered(lambda picking: not picking._centric_backorders_disabled())
        return super(StockPicking, candidates)._check_backorder()

    def button_validate(self):
        """Route backorder-free transfers down Odoo's native no-backorder path.

        Adding their ids to the ``picking_ids_not_to_backorder`` context makes
        core validate them at the picked quantity and cancel the outstanding
        remainder instead of creating a backorder (see the handling around
        ``pickings_not_to_backorder`` in ``stock.picking.button_validate``). This
        is the very same context Odoo's own "No Backorder" button sets in
        ``stock.backorder.confirmation.process_cancel_backorder``; the wizard
        itself is skipped by the ``_check_backorder`` override above.

        Behaviour for every other transfer is untouched: we only extend the
        context and call ``super()``.
        """
        to_disable = self.filtered(lambda picking: picking._centric_backorders_disabled())
        if to_disable:
            not_to_backorder = list(self.env.context.get("picking_ids_not_to_backorder") or [])
            not_to_backorder += to_disable.ids
            self = self.with_context(picking_ids_not_to_backorder=not_to_backorder)
        return super().button_validate()
