"""Ask-to-split when a delivery goes out ahead of its order's other categories.

Under the packed-quantity-is-final regime an order must never end up
Partially Delivered. When a customer delivery is validated while OTHER
loadsheet categories of the same order are still mid-chain (e.g. Frozen goes
out now, Dry is still in Pack), this wizard asks the operator to split the
order first:

* Confirm - every lagging category is moved to its own new sales order using
  the EXISTING split machinery (``_centric_split_sale_order_for_delivery_route``,
  the same code the Delivery board's route-change split runs), with the
  next-run route assigned when it already exists ("Valletta" -> "Valletta 2");
  the goods delivering NOW keep the original order number and route, and the
  delivery then validates normally, leaving that order Fully Delivered.
* Discard - nothing is validated. There is deliberately no
  "deliver without splitting" option: that is exactly the Partially
  Delivered state this flow exists to prevent.
"""

import re

from odoo import _, api, fields, models


class DeliverySplitConfirmation(models.TransientModel):
    _name = "centric.delivery.split.confirmation"
    _description = "Split Order Before Delivery Confirmation"

    picking_ids = fields.Many2many(
        "stock.picking",
        readonly=True,
    )
    summary = fields.Text(
        readonly=True,
    )

    @api.model
    def _centric_next_run_carrier(self, carrier):
        """The already-existing next-run route for ``carrier``, or nothing.

        "Valletta" -> "Valletta 2", "Valletta 2" -> "Valletta 3", ... Routes
        are NEVER created here: if the next-run route does not exist yet the
        split order is left without one and the office assigns it manually.
        """
        if not carrier:
            return self.env["delivery.carrier"]
        name = (carrier.name or "").strip()
        match = re.match(r"^(.*?)\s+(\d+)$", name)
        if match:
            base, index = match.group(1), int(match.group(2)) + 1
        else:
            base, index = name, 2
        return self.env["delivery.carrier"].search(
            [("name", "=ilike", f"{base} {index}")], limit=1,
        )

    def action_confirm(self):
        self.ensure_one()
        pickings = self.picking_ids
        for picking in pickings:
            if picking.state in ("done", "cancel"):
                continue
            if not picking._centric_is_locked_customer_delivery():
                continue
            for order, lagging_by_category in picking._centric_lagging_categories().items():
                next_carrier = self._centric_next_run_carrier(order.carrier_id)
                previous_carriers = {picking.id: order.carrier_id.display_name or _("No Route")}
                for category in lagging_by_category:
                    picking._centric_split_sale_order_for_delivery_route(
                        order,
                        category,
                        next_carrier.id if next_carrier else False,
                        previous_carriers,
                    )
        return pickings.with_context(
            skip_centric_delivery_split_check=True,
        ).button_validate()
