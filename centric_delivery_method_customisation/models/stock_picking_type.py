from odoo import models
from odoo.fields import Domain


class StockPickingType(models.Model):
    _inherit = "stock.picking.type"

    # The Pick/Pack/Delivery operation cards open the "All Transfers" board, which
    # carries no state filter and therefore lists every picking ever made -- so
    # Done/Cancelled/Draft transfers pile up and clutter the stage. On those
    # operation boards we want only live, in-progress work, so a validated
    # transfer drops off the stage (it "moved on") instead of staying populated.
    # Nothing is deleted: the records remain in the database and are still
    # reachable from the main Transfers list and Reporting.
    _CENTRIC_HIDE_STATES_ON_BOARD = ("draft", "done", "cancel")

    def _get_action(self, action_xmlid):
        action = super()._get_action(action_xmlid)
        if len(self) == 1:
            operation_name = (self.name or "").strip().casefold()
            is_pick_operation = operation_name == "pick"
            is_pack_operation = operation_name == "pack"
            is_delivery_operation = self.code == "outgoing"
            context = dict(action.get("context") or {})
            context.update({
                "centric_is_pick_operation": is_pick_operation,
                "centric_is_pack_operation": is_pack_operation,
                "centric_is_delivery_operation": is_delivery_operation,
            })
            if is_pick_operation or is_pack_operation or is_delivery_operation:
                context.pop("search_default_centric_carrier_loadsheet", None)
                # Group only by carrier (van). The loadsheet category (Dry/Frozen)
                # is shown as a column on each picking line instead of as a nested
                # group header, so it reads on the order line itself.
                group_by = ["carrier_id"]
                # Only group by fields that actually exist on the action's model:
                # the "Operations" stat opens a stock.move list, so a field missing
                # on that model (e.g. carrier_id before it was exposed) must never
                # be injected or read_group raises "Invalid field ...".
                model = action.get("res_model")
                model_fields = self.env[model]._fields if model in self.env else {}
                group_by = [gb for gb in group_by if gb in model_fields]
                if group_by:
                    context["group_by"] = group_by
            action["context"] = context
            if is_delivery_operation:
                action["domain"] = [(
                    "picking_type_id",
                    "in",
                    self._centric_van_status_picking_types().ids,
                )]
            # Keep only live, in-progress work on every Pick/Pack/Delivery
            # pickings action: hide validated (Done), Cancelled and Draft so each
            # stage shows just what still has to be processed. We apply this
            # UNCONDITIONALLY (no xmlid match, no search-default heuristic -- both
            # proved unreliable across Odoo builds and were the cause of the
            # earlier misses). It is safe to apply to the To-Do/Waiting/Ready
            # count links too: they already restrict to active states, so ANDing
            # this filter is a no-op for them; only the unfiltered "All Transfers"
            # board actually changes. The res_model guard keeps the stock.move
            # Reporting action untouched. These operation flags are reliably set
            # here -- the list's custom action buttons depend on them.
            if (
                (is_pick_operation or is_pack_operation or is_delivery_operation)
                and action.get("res_model") == "stock.picking"
            ):
                live_only_domain = [(
                    "state", "not in", list(self._CENTRIC_HIDE_STATES_ON_BOARD),
                )]
                action["domain"] = Domain.AND([action.get("domain") or [], live_only_domain])
        return action

    def _centric_van_status_picking_types(self):
        self.ensure_one()
        domain = [("company_id", "=", self.company_id.id)]
        if self.warehouse_id:
            domain.append(("warehouse_id", "=", self.warehouse_id.id))

        picking_types = self.search(domain)
        pick_pack_types = picking_types.filtered(
            lambda picking_type: picking_type._centric_is_pick_or_pack_operation()
        )
        return self | pick_pack_types

    def _centric_is_pick_or_pack_operation(self):
        self.ensure_one()
        operation_names = {
            (self.name or "").strip().casefold(),
            (self.sequence_code or "").strip().casefold(),
        }
        return bool(operation_names & {"pick", "pack"})
