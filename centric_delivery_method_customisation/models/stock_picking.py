import json
from urllib.parse import quote

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tools.float_utils import float_compare


class StockPicking(models.Model):
    _inherit = "stock.picking"

    # Storage field for the "First Logged Quantity" audit feature. It is the
    # Studio field that already exists on this deployment (and drives the board
    # column); the code below reads/writes it only when it is present, so the
    # module stays installable on databases without it (fresh installs, tests).
    _CENTRIC_FIRST_LOGGED_FIELD = "x_studio_first_logged_quantity"

    centric_loadsheet_category_id = fields.Many2one(
        "centric.loadsheet.category",
        string="Loadsheet Category",
        copy=False,
        index=True,
        readonly=True,
    )
    centric_demand_quantity = fields.Float(
        string="Demand",
        compute="_compute_centric_pack_quantities",
        digits="Product Unit",
        readonly=True,
    )
    centric_quantity = fields.Float(
        string="Quantity",
        compute="_compute_centric_pack_quantities",
        inverse="_inverse_centric_quantity",
        digits="Product Unit",
        readonly=False,
    )
    centric_pack_entered_qty = fields.Float(
        # Distinct technical label from ``centric_quantity`` (also "Quantity")
        # so Odoo's field reflection does not log a "two fields have the same
        # label" warning for stock.picking. The PACK list column still shows
        # "Quantity" to operators via an explicit string= on the view field.
        string="Pack Quantity",
        compute="_compute_centric_pack_quantities",
        digits="Product Unit",
        readonly=True,
        help="Sum of the operator-entered PACK quantities (move "
             "x_pack_entered_qty). Shown as the Quantity column on the PACK "
             "list. Display only - it does not change reserved stock.",
    )
    centric_van_order_status = fields.Char(
        string="Order Status",
        compute="_compute_centric_van_order_status",
    )
    centric_driver_id = fields.Many2one(
        "hr.employee",
        string="Driver",
        index=True,
        copy=True,
        help="Employee (driver) for this delivery. Defaults from the sale order; "
             "editable at dispatch and kept in sync with the order.",
    )
    centric_sale_order_note = fields.Text(
        string="Order Note",
        compute="_compute_centric_sale_order_note",
    )
    centric_quantity_verified = fields.Boolean(
        string="Quantity Verified",
        help="True when every active PACK line on this picking has been "
             "confirmed (green) through the Items popup. Computed roll-up of "
             "move.x_pack_line_verified; drives the green row highlight so "
             "fully-confirmed pickings stand out for bulk validation. "
             "UI/status only - it never affects stock.",
        compute="_compute_centric_quantity_verified",
        store=True,
        copy=False,
        readonly=True,
        index=True,
    )
    centric_single_quantity_move = fields.Boolean(
        string="Single-line",
        help="True when the picking has exactly one active (non done/cancel) "
             "quantity move. The inline board Quantity may only be edited for "
             "single-line pickings; multi-line quantities must be entered per "
             "line through the Items popup, so the inline field is read-only.",
        compute="_compute_centric_single_quantity_move",
    )

    def write(self, vals):
        previous_carriers = {}
        if "carrier_id" in vals:
            previous_carriers = {
                picking.id: picking.carrier_id.display_name or _("No Route")
                for picking in self
            }

        result = super().write(vals)
        if "carrier_id" in vals and not self.env.context.get("centric_skip_sale_carrier_sync"):
            if self.env.context.get("centric_is_delivery_operation"):
                self._centric_split_delivery_route_by_category(previous_carriers, vals["carrier_id"])
            else:
                self._centric_sync_sale_order_carrier(vals["carrier_id"])
        if "centric_driver_id" in vals and not self.env.context.get("centric_skip_sale_driver_sync"):
            self._centric_sync_sale_order_driver(vals["centric_driver_id"])
        return result

    def _centric_logged_quantity(self):
        """The quantity figure the 'First Logged Quantity' feature tracks.

        For a PACK transfer this is the operator-entered pack quantity
        (``centric_pack_entered_qty``); for PICK/DELIVERY it is the standard
        ``centric_quantity`` - i.e. the same field the operator edits at each
        stage, so the audit reflects what was actually logged.
        """
        self.ensure_one()
        if self._centric_van_stage_sequence() == 20:
            return self.centric_pack_entered_qty or 0.0
        return self.centric_quantity or 0.0

    def _centric_track_first_logged_quantity(self, quantities_before):
        """Maintain the 'First Logged Quantity' audit value and change log.

        Code replacement for the Studio automation 'Track Inventory Quantity
        Change', which was bound to stock.picking On Create/Update with NO
        watched-field filter - so it fired on every single picking write and
        re-wrote the picking while posting a fresh 'Pack quantity changed'
        message each time, producing a storm of duplicate chatter (11+ per
        save) and reentrant writes mid-save.

        Instead this is called from the genuine logging events only (the Items
        popup Save and the inline board Quantity edit), with a snapshot of the
        logged quantity taken just BEFORE that edit. For each picking it:
          * records the first logged quantity a single time (when still unset
            and a quantity now exists);
          * posts exactly ONE audit message - to the transfer and its sale
            order - only when the logged quantity actually MOVED in this edit
            and differs from the first logged value.

        No-op where the storage field is absent (fresh installs / tests), so
        the module stays installable without it.

        :param quantities_before: {picking_id: logged_quantity_before_the_edit}
        """
        field = self._CENTRIC_FIRST_LOGGED_FIELD
        if field not in self._fields:
            return
        for picking in self:
            if picking.id not in quantities_before or picking.state in ("done", "cancel"):
                continue
            current = picking._centric_logged_quantity()
            before = quantities_before[picking.id]
            first_logged = picking[field] or 0.0

            if not first_logged:
                if float_compare(current, 0.0, precision_digits=2) > 0:
                    picking[field] = current
                continue

            changed_now = float_compare(current, before, precision_digits=2) != 0
            differs_from_first = float_compare(current, first_logged, precision_digits=2) != 0
            if changed_now and differs_from_first:
                picking._centric_post_quantity_change(first_logged, current)

    def _centric_post_quantity_change(self, first_logged, current):
        self.ensure_one()
        body = Markup(
            "<p><b>Pack quantity changed</b></p>"
            "<p>Transfer: %(name)s<br/>"
            "First logged quantity: %(first)s<br/>"
            "Current quantity: %(current)s<br/>"
            "Source document: %(origin)s<br/>"
            "Updated by: %(user)s</p>"
        ) % {
            "name": self.name or "",
            "first": first_logged,
            "current": current,
            "origin": self.origin or "",
            "user": self.env.user.name,
        }
        self.message_post(body=body)
        for sale_order in self._centric_sale_orders():
            sale_order.message_post(body=body)

    def _centric_sync_sale_order_driver(self, driver_id):
        sale_orders = self._centric_sale_orders()
        if sale_orders:
            sale_orders.with_context(centric_skip_picking_driver_sync=True).write({
                "centric_driver_id": driver_id or False,
            })

    def _centric_sale_orders(self):
        return (
            self.mapped("sale_id")
            | self.mapped("move_ids.sale_line_id.order_id")
            | self.mapped("reference_ids.sale_ids")
        )

    @api.depends(
        "sale_id.order_line.display_type",
        "sale_id.order_line.name",
        "sale_id.order_line.sequence",
        "move_ids.sale_line_id.order_id.order_line.display_type",
        "move_ids.sale_line_id.order_id.order_line.name",
        "move_ids.sale_line_id.order_id.order_line.sequence",
        "reference_ids.sale_ids.order_line.display_type",
        "reference_ids.sale_ids.order_line.name",
        "reference_ids.sale_ids.order_line.sequence",
    )
    def _compute_centric_sale_order_note(self):
        for picking in self:
            picking.centric_sale_order_note = picking._centric_sale_order_note_text()

    def _centric_sale_order_note_text(self):
        self.ensure_one()
        note_lines = self._centric_sale_orders().mapped("order_line").filtered(
            lambda line: line.display_type == "line_note" and line.name
        ).sorted(lambda line: (line.order_id.id, line.sequence, line.id))

        notes = []
        seen_notes = set()
        for line in note_lines:
            note = line.name.strip()
            if note and note not in seen_notes:
                notes.append(note)
                seen_notes.add(note)
        return "\n".join(notes) or False

    def _centric_sync_sale_order_carrier(self, carrier_id):
        sale_orders = self._centric_sale_orders()
        if sale_orders:
            sale_orders.write({
                "carrier_id": carrier_id or False,
            })

    def _centric_direct_sale_orders(self):
        return self.mapped("sale_id") | self.mapped("move_ids.sale_line_id.order_id")

    def _centric_split_delivery_route_by_category(self, previous_carriers, carrier_id):
        processed_keys = set()
        for picking in self.filtered(lambda record: record.state != "cancel"):
            for order in picking._centric_direct_sale_orders().filtered(
                lambda sale_order: sale_order.state == "sale"
            ):
                key = (order.id, picking.centric_loadsheet_category_id.id or False)
                if key in processed_keys:
                    continue
                processed_keys.add(key)
                picking._centric_split_sale_order_for_delivery_route(
                    order,
                    picking.centric_loadsheet_category_id,
                    carrier_id,
                    previous_carriers,
                )

    def _centric_split_sale_order_for_delivery_route(self, order, category, carrier_id, previous_carriers):
        self.ensure_one()
        category_pickings = order._centric_stock_pickings().filtered(
            lambda picking: (
                picking.state != "cancel"
                and picking.centric_loadsheet_category_id == category
                and (
                    picking.sale_id == order
                    or order in picking.move_ids.sale_line_id.order_id
                )
            )
        )
        if not category_pickings:
            return

        category_moves = category_pickings.move_ids.filtered(lambda move: move.state != "cancel")
        sale_lines = category_moves.sale_line_id.filtered(
            lambda line: line.order_id == order and not line.display_type
        )
        if not sale_lines:
            return

        category_pickings.with_context(centric_skip_sale_carrier_sync=True).write({
            "carrier_id": carrier_id or False,
        })

        remaining_lines = order.order_line.filtered(lambda line: not line.display_type) - sale_lines
        if not remaining_lines:
            order.with_context(centric_skip_picking_carrier_sync=True).write({
                "carrier_id": carrier_id or False,
            })
            self._centric_log_delivery_route_update(order, category, previous_carriers)
            return

        new_order = self._centric_create_split_sale_order(order, sale_lines, carrier_id)
        new_reference = self.env["stock.reference"].create({
            "name": new_order.name,
            "sale_ids": [Command.link(new_order.id)],
        })
        category_moves.write({
            "origin": new_order.name,
            "reference_ids": [Command.set(new_reference.ids)],
        })
        category_pickings.with_context(centric_skip_sale_carrier_sync=True).write({
            "origin": new_order.name,
            "sale_id": new_order.id,
        })

        self._centric_log_delivery_order_split(
            order,
            new_order,
            category,
            previous_carriers,
        )

    def _centric_create_split_sale_order(self, order, sale_lines, carrier_id):
        defaults = {
            "origin": order.name if not order.origin else "%s, %s" % (order.origin, order.name),
            "order_line": [Command.clear()],
            "carrier_id": carrier_id or False,
            "stock_reference_ids": [Command.clear()],
        }
        # A split is not a duplicate. Fields deliberately marked copy=False so
        # that a manually duplicated order starts clean - the customer's PO
        # number, the info note printed on their invoice - still describe BOTH
        # halves here, because the customer placed one order and is getting one
        # set of paperwork under two numbers. Owning modules opt their fields in
        # through the hook rather than relaxing copy=False, which would also
        # (wrongly) carry them through the Duplicate action.
        defaults.update(order._centric_split_order_carried_values())
        new_order = order.with_context(
            centric_skip_picking_carrier_sync=True,
            mail_create_nosubscribe=True,
        ).copy(defaults)
        sale_lines.with_context(skip_procurement=True).write({
            "order_id": new_order.id,
        })
        new_order.with_context(
            skip_procurement=True,
            centric_skip_picking_carrier_sync=True,
        ).action_confirm()
        return new_order

    def _centric_log_delivery_route_update(self, order, category, previous_carriers):
        self.ensure_one()
        old_route = previous_carriers.get(self.id) or _("No Route")
        new_route = self.carrier_id.display_name or _("No Route")
        if old_route == new_route:
            return

        category_name = category.display_name or _("Uncategorized")
        message = _(
            "Delivery route updated: %(category)s items stayed on %(order)s and moved "
            "from %(old_route)s to %(new_route)s."
        ) % {
            "category": category_name,
            "order": order.name,
            "old_route": old_route,
            "new_route": new_route,
        }
        self.message_post(body=message)
        order.message_post(body="%s: %s" % (self.name, message))

    def _centric_log_delivery_order_split(self, order, new_order, category, previous_carriers):
        self.ensure_one()
        old_route = previous_carriers.get(self.id) or _("No Route")
        new_route = self.carrier_id.display_name or _("No Route")
        category_name = category.display_name or _("Uncategorized")
        message = _(
            "Delivery order split confirmed: %(category)s items were moved from %(old_order)s "
            "to new order %(new_order)s and from %(old_route)s to %(new_route)s. "
            "The remaining categories stayed on %(old_order)s."
        ) % {
            "category": category_name,
            "old_order": order.name,
            "new_order": new_order.name,
            "old_route": old_route,
            "new_route": new_route,
        }
        self.message_post(body=message)
        order.message_post(body=message)
        new_order.message_post(body=message)

    @api.depends(
        "state",
        "picking_type_id",
        "centric_loadsheet_category_id",
        "origin",
        "sale_id.picking_ids.state",
        "move_ids.sale_line_id.order_id.picking_ids.state",
    )
    def _compute_centric_van_order_status(self):
        for picking in self:
            current_stage = picking._centric_current_van_stage_picking()
            if current_stage:
                picking.centric_van_order_status = current_stage._centric_van_stage_label()
            elif picking.state == "done":
                picking.centric_van_order_status = "Done"
            else:
                picking.centric_van_order_status = picking._centric_van_stage_label()

    def _centric_current_van_stage_picking(self):
        self.ensure_one()
        open_pickings = self._centric_related_van_pickings().filtered(
            lambda picking: picking.state != "done"
        )
        return open_pickings.sorted(
            lambda picking: (picking._centric_van_stage_sequence(), picking.id)
        )[:1]

    def _centric_related_van_pickings(self):
        self.ensure_one()
        pickings = self
        sale_orders = self._centric_sale_orders()
        if sale_orders:
            pickings |= sale_orders._centric_stock_pickings()
        if self.reference_ids:
            pickings |= self.env["stock.picking"].search([
                ("reference_ids", "in", self.reference_ids.ids),
                ("company_id", "=", self.company_id.id),
            ])
        if self.origin:
            pickings |= self.env["stock.picking"].search([
                ("origin", "=", self.origin),
                ("company_id", "=", self.company_id.id),
            ])

        category_id = self.centric_loadsheet_category_id.id
        warehouse = self.picking_type_id.warehouse_id
        return pickings.filtered(
            lambda picking: (
                picking.state != "cancel"
                and picking.company_id == self.company_id
                and picking.centric_loadsheet_category_id.id == category_id
                and (not warehouse or picking.picking_type_id.warehouse_id == warehouse)
                and picking._centric_is_van_workflow_stage()
            )
        )

    def _centric_is_van_workflow_stage(self):
        self.ensure_one()
        return self._centric_van_stage_sequence() < 90

    def _centric_van_stage_sequence(self):
        self.ensure_one()
        picking_type = self.picking_type_id
        operation_names = {
            (picking_type.name or "").strip().casefold(),
            (picking_type.sequence_code or "").strip().casefold(),
        }
        if "pick" in operation_names:
            return 10
        if "pack" in operation_names:
            return 20
        if picking_type.code == "outgoing":
            return 30
        return 90

    def _centric_van_stage_label(self):
        self.ensure_one()
        stage_sequence = self._centric_van_stage_sequence()
        if stage_sequence == 10:
            return "In Pick"
        if stage_sequence == 20:
            return "In Pack"
        if stage_sequence == 30:
            return "Ready for Delivery"
        return self.picking_type_id.name or self.state

    def button_validate(self):
        # Packed-quantity-is-final layering, in order:
        #   1. block validation unless every active PACK line is confirmed;
        #   2. make the operator-entered PACK quantity the source of truth for
        #      execution (x_pack_entered_qty -> stock.move.quantity);
        #   3. block a customer delivery whose quantities differ from demand -
        #      the delivery always ships exactly what was packed.
        # Packing MORE than the pick brought in is allowed (per business
        # decision 2026-08-10): the surplus draws the Packing Zone negative,
        # negatives being permitted there. The leftover auto-return copes -
        # it skips lines whose leftover is zero or negative.
        # After core validation, PACK pickings that just completed set their
        # sale order lines to the packed quantity - down or up - and send the
        # un-packed leftovers back to Stock. PICK validation is unaffected.
        self._centric_check_pack_lines_verified()
        self._centric_apply_pack_quantities()
        self._centric_check_delivery_quantities()
        split_action = self._centric_delivery_split_confirmation_action()
        if split_action:
            # A delivery is going out ahead of the order's other categories:
            # defer to the split-confirmation wizard instead of validating.
            # Its Confirm re-enters button_validate with the skip key set.
            return split_action
        finishing_packs = self.filtered(
            lambda picking: picking.state not in ("done", "cancel")
            and picking._centric_van_stage_sequence() == 20
        )
        result = super().button_validate()
        done_packs = finishing_packs.filtered(lambda picking: picking.state == "done")
        if done_packs and not self.env.context.get("centric_skip_pack_final"):
            done_packs._centric_apply_pack_final_quantities()
        if result is True:
            # Only once something actually WAS validated. A dict result means a
            # backorder / expiry / split wizard intervened instead, and that
            # wizard re-enters button_validate on confirmation, so the resync
            # still runs at the real validation.
            self._centric_resync_open_chain_scheduled_dates()
        return result

    def _centric_resync_open_chain_scheduled_dates(self):
        """Re-assert the order's Delivery Date on every still-open transfer of
        the chain once a stage has been validated.

        A downstream transfer does not inherit the Scheduled Date of the stage
        before it. Core dates each next step from the moment the previous one was
        *processed* - at validation ``_action_done`` overwrites the move's
        ``date`` with ``now()`` (correct in itself: on a done move ``date`` means
        "processed at"), and the next step is derived from that. So validating a
        PICK today produced a PACK - and later an OUT - scheduled for today, even
        when the order promised tomorrow, which is exactly what the warehouse
        reported: shifting an order to tomorrow on the pick, then seeing it come
        back as today in pack.

        The Delivery Date the office sets on the order is the source of truth
        here, and ``sale.order._centric_sync_picking_scheduled_date`` already
        knows how to push it onto the whole chain - it simply never ran again
        after order confirmation, when the later steps either did not exist yet
        or had not been re-dated. Re-running it at each validation keeps every
        remaining step on the promised day, whichever way the downstream
        transfers come into being (chained up front, or pushed into existence at
        validation time).

        Orders with no Delivery Date are skipped by the sync itself, and the
        just-validated transfer is skipped because it is now ``done`` - so this
        only ever moves the steps still ahead of the warehouse. Transfers with no
        sale order behind them (the pack-leftover return this module creates and
        validates itself) resolve to no orders and are left alone.
        """
        self._centric_sale_orders()._centric_sync_picking_scheduled_date()

    def _centric_apply_pack_quantities(self):
        """Make the operator-entered PACK quantity the single source of truth for
        stock execution.

        At PACK validation, copy each move's ``x_pack_entered_qty`` (the count the
        operator entered and confirmed in the Items popup) into the move's DONE
        quantity. Odoo then delivers exactly what was packed and natively creates
        a backorder for the remainder - no sales order split, no custom backorder
        logic, no core change. The packed quantity flows downstream through the
        standard chained moves, so the delivery and the sale order's delivery
        status reflect the real result (e.g. demand 5, packed 3 -> delivered 3,
        backorder 2, Partially Delivered).

        Field mapping (Odoo 19): the done quantity is ``stock.move.quantity``.
        That is the field that used to be called ``quantity_done`` before Odoo
        17 - it is the sum of the move lines' done quantity and is what
        ``_action_done`` reads to decide on a backorder. We write ONLY this done
        field through its standard inverse (``_set_quantity`` -> Odoo's
        ``_set_quantity_done``). We never write the demand (``product_uom_qty``)
        and never touch reservation: reducing the done quantity below the
        reserved amount lets Odoo release the surplus and backorder it natively,
        exactly as if the operator typed the Done value in the detailed-operations
        UI.

        Scope is strictly the PACK stage (van stage 20). PICK and DELIVERY keep
        using the standard quantity untouched, and reservation during packing is
        never affected - only the final done quantity at validation time is.
        Idempotent: re-running (e.g. the backorder-confirmation re-validate) only
        re-writes a value that is already set.
        """
        for picking in self:
            if picking.state in ("done", "cancel"):
                continue
            if picking._centric_van_stage_sequence() != 20:
                continue
            for move in picking._centric_quantity_moves().filtered(
                lambda move: move.state not in ("done", "cancel")
            ):
                packed_quantity = move.x_pack_entered_qty
                # Write ONLY the done quantity (Odoo 19 stock.move.quantity =
                # the former quantity_done). Demand and reservation are untouched;
                # Odoo's standard validation handles the backorder from here.
                if move.product_uom.compare(move.quantity, packed_quantity) != 0:
                    move.quantity = packed_quantity

    def _centric_check_pack_lines_verified(self):
        """Block PACK validation while any active line is unconfirmed (not green).

        Operational/validation control only. It inspects the per-line
        ``x_pack_line_verified`` status set from the Items popup and raises a
        clear error that identifies the unconfirmed lines. It applies ONLY to
        PACK-stage pickings (stage 20): PICK, DELIVERY and the invoice-time
        auto-validation are never affected, and it touches no stock, move or
        core validation logic. Programmatic flows may bypass it with the
        ``centric_skip_pack_verify_check`` context key.
        """
        if self.env.context.get("centric_skip_pack_verify_check"):
            return

        unverified_by_picking = {}
        for picking in self:
            if picking.state in ("done", "cancel"):
                continue
            if picking._centric_van_stage_sequence() != 20:
                continue
            unverified = picking._centric_quantity_moves().filtered(
                lambda move: move.state not in ("done", "cancel")
                and not move.x_pack_line_verified
            )
            if unverified:
                unverified_by_picking[picking] = unverified

        if not unverified_by_picking:
            return

        details = []
        for picking, moves in unverified_by_picking.items():
            products = ", ".join(moves.mapped("product_id.display_name"))
            details.append("- %s: %s" % (picking.name, products))
        raise UserError(_(
            "Validation blocked: one or more PACK lines have not been confirmed "
            "(green) in the Items popup.\n\nConfirm every line on these "
            "transfers before validating:\n%s"
        ) % "\n".join(details))

    # ------------------------------------------------------------------
    # Packed quantity is final
    # ------------------------------------------------------------------
    # The former _centric_check_pack_not_over_picked guard (pack <= picked)
    # was removed on 2026-08-10 at the business's request: operators must be
    # able to pack more than the pick brought into the Packing Zone (and more
    # than the zone holds - negatives are allowed there). Callers that passed
    # centric_skip_pack_overpack_check still may; the key is simply inert.

    def _centric_check_delivery_quantities(self):
        """Hard block: a customer delivery ships EXACTLY what was packed.

        Quantities on the delivery order are never amended - the quantity
        decision was made at PACK. Every active move must have its done
        quantity equal to its demand (which the push chain set to the packed
        quantity when the delivery was created). Bypass for controlled
        programmatic flows: ``centric_skip_delivery_demand_check`` context key.
        Idempotent - it re-runs harmlessly on wizard re-entries.
        """
        if self.env.context.get("centric_skip_delivery_demand_check"):
            return

        offending = []
        for picking in self:
            if picking.state in ("done", "cancel"):
                continue
            if not picking._centric_is_locked_customer_delivery():
                continue
            for move in picking._centric_quantity_moves().filtered(
                lambda move: move.state not in ("done", "cancel")
            ):
                if not move.move_orig_ids:
                    offending.append("- %s: %s (%s)" % (
                        picking.name,
                        move.product_id.display_name,
                        _("added at the delivery stage"),
                    ))
                elif move.product_uom.compare(move.quantity, move.product_uom_qty) != 0:
                    offending.append("- %s: %s (packed %s, attempting %s)" % (
                        picking.name,
                        move.product_id.display_name,
                        move.product_uom_qty,
                        move.quantity,
                    ))
        if offending:
            raise UserError(_(
                "Validation blocked: delivery quantities cannot be changed.\n\n"
                "A delivery order always ships exactly the packed quantity - "
                "quantity changes are made at PICK or PACK, never at the "
                "delivery stage:\n%s"
            ) % "\n".join(offending))

        # Close the picked-flag side door: core only auto-picks everything
        # when NOTHING is picked, and at _action_done it UNLINKS the unpicked
        # lines of partially-picked pickings - so ticking "picked" on one move
        # only would under-ship past the quantity check above. On a locked
        # delivery everything ships by definition, so pick all active moves.
        for picking in self:
            if picking.state in ("done", "cancel"):
                continue
            if not picking._centric_is_locked_customer_delivery():
                continue
            unpicked = picking._centric_quantity_moves().filtered(
                lambda move: move.state not in ("done", "cancel") and not move.picked
            )
            if unpicked:
                unpicked.picked = True

    def _centric_is_locked_customer_delivery(self):
        """A customer-bound delivery fed by the pick/pack chain.

        Only chain-fed deliveries are locked: their demand IS the packed
        quantity (the push rule created them from the pack's done moves).
        Deliveries with no chained origin at all (single-step warehouses, the
        direct-sale auto-delivery) have no packed quantity to enforce and keep
        standard behaviour.
        """
        self.ensure_one()
        if (
            self._centric_van_stage_sequence() != 30
            or self.location_dest_id.usage != "customer"
        ):
            return False
        active_moves = self._centric_quantity_moves().filtered(
            lambda move: move.state not in ("done", "cancel")
        )
        return any(move.move_orig_ids for move in active_moves)

    def _centric_lagging_categories(self):
        """Order lines left behind when THIS delivery goes out, by category.

        Returns ``{sale.order: [loadsheet categories]}`` for every order this
        customer delivery serves: product lines that are neither covered by
        this delivery nor already fully delivered, grouped by their product's
        loadsheet category. Categories that are themselves on this delivery
        are excluded (splitting them would drag this very delivery along).
        Service lines never lag - they do not ship.
        """
        self.ensure_one()
        result = {}
        active_moves = self._centric_quantity_moves().filtered(
            lambda move: move.state not in ("done", "cancel")
        )
        covered_lines = active_moves.sale_line_id
        own_categories = set(
            active_moves.product_id.mapped("centric_loadsheet_category_id").ids
        ) | ({False} if any(
            not move.product_id.centric_loadsheet_category_id
            for move in active_moves
        ) else set())
        for order in self._centric_direct_sale_orders().filtered(
            lambda sale_order: sale_order.state == "sale"
        ):
            categories = []
            for line in order.order_line:
                if line.display_type or not line.product_id:
                    continue
                if line.product_id.type == "service":
                    continue
                if line in covered_lines:
                    continue
                precision = self.env["decimal.precision"].precision_get("Product Unit")
                if float_compare(
                    line.qty_delivered, line.product_uom_qty,
                    precision_digits=precision,
                ) >= 0:
                    continue
                category = line.product_id.centric_loadsheet_category_id
                if (category.id or False) in own_categories:
                    continue
                if category not in categories:
                    categories.append(category)
            if categories:
                result[order] = categories
        return result

    def _centric_delivery_split_confirmation_action(self):
        """The split-confirmation wizard action, or ``False`` when no delivery
        in ``self`` is going out ahead of its order's other categories.

        Skipped via ``skip_centric_delivery_split_check`` (the wizard's own
        re-entry and controlled programmatic flows)."""
        if self.env.context.get("skip_centric_delivery_split_check"):
            return False

        summaries = []
        for picking in self:
            if picking.state in ("done", "cancel"):
                continue
            if not picking._centric_is_locked_customer_delivery():
                continue
            for order, categories in picking._centric_lagging_categories().items():
                names = ", ".join(
                    category.display_name or _("Uncategorized")
                    for category in categories
                )
                summaries.append(_(
                    "%(order)s still has undelivered items (%(categories)s) that "
                    "are not on %(picking)s.",
                    order=order.name, categories=names, picking=picking.name,
                ))
        if not summaries:
            return False

        wizard = self.env["centric.delivery.split.confirmation"].create({
            "picking_ids": [Command.set(self.ids)],
            "summary": "\n".join(summaries) + "\n\n" + _(
                "Splitting moves those items to their own new sales order "
                "(next run's route is assigned when it exists, e.g. "
                "\"Valletta\" → \"Valletta 2\"), so this delivery completes "
                "its order in full. Without the split, the delivery cannot "
                "be validated."
            ),
        })
        view = self.env.ref(
            "centric_delivery_method_customisation.view_centric_delivery_split_confirmation"
        )
        return {
            "type": "ir.actions.act_window",
            "name": _("Split Order Before Delivering?"),
            "res_model": wizard._name,
            "res_id": wizard.id,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "target": "new",
            "context": dict(self.env.context),
        }

    def _centric_apply_pack_final_quantities(self):
        """Post-validation consequences of "the packed quantity is final".

        Runs on PACK pickings that just reached ``done``:
          1. the sale order lines are set to the packed quantity - down OR up
             (the order now states what the customer actually gets, the amount
             and invoice follow, and it reads Fully Delivered coherently);
          2. picked-but-not-packed leftovers go back from the Packing Zone to
             Stock with their lots, so no phantom stock accumulates there.
        """
        for picking in self:
            picking._centric_trim_sale_lines_to_packed()
            picking._centric_return_pack_leftovers()

    def _centric_trim_sale_lines_to_packed(self):
        """Set each sale order line to its total packed quantity.

        Only lines whose PACK-stage moves are ALL settled (done or cancelled)
        are adjusted - an order split over several pack transfers (e.g. Dry and
        Frozen loadsheets) is only adjusted for the lines each validation
        completes; lines with another pack still pending wait for it. The write
        goes through ``skip_procurement`` so sale_stock does not launch a
        procurement for the delta (downwards it would spawn native return
        pickings alongside our own leftover return; upwards - over-packing is
        allowed since 2026-08-10 - the surplus already shipped through the
        over-packed moves, so nothing more must be picked). Equality leaves
        the line untouched.
        """
        self.ensure_one()
        trims_by_order = {}
        # Resolve the sale lines through the chain as well: the push rule may
        # or may not copy sale_line_id onto the PACK move, but the PICK move
        # (created by the order's procurement) always carries it.
        lines = self.env["sale.order.line"]
        for move in self.move_ids:
            lines |= move.sale_line_id or move.move_orig_ids.sale_line_id
        for line in lines:
            if line.display_type or not line.product_id:
                continue
            pack_moves = (line.move_ids | line.move_ids.move_dest_ids).filtered(
                lambda move: move._centric_is_pack_operation_move()
            )
            if any(move.state not in ("done", "cancel") for move in pack_moves):
                continue
            packed_quantity = sum(
                move.product_uom._compute_quantity(
                    move.quantity, line.product_uom_id, rounding_method="HALF-UP"
                )
                for move in pack_moves.filtered(lambda move: move.state == "done")
            )
            if line.product_uom_id.compare(packed_quantity, line.product_uom_qty) == 0:
                continue
            order = line.order_id
            if order.locked:
                order.message_post(body=_(
                    "%(picking)s packed %(packed)s of %(product)s but the order "
                    "is locked, so its quantity was not adjusted.",
                    picking=self.name,
                    packed=packed_quantity,
                    product=line.product_id.display_name,
                ))
                continue
            trims_by_order.setdefault(order, []).append(
                (line, line.product_uom_qty, packed_quantity)
            )

        for order, trims in trims_by_order.items():
            for line, _old_quantity, packed_quantity in trims:
                line.with_context(skip_procurement=True).write({
                    "product_uom_qty": packed_quantity,
                })
            order.message_post(body=Markup("<br/>").join(
                [Markup(_(
                    "Order quantities set to the packed amounts at %s:"
                )) % self.name]
                + [
                    Markup(_("- %(product)s: %(old)s → %(new)s")) % {
                        "product": line.product_id.display_name,
                        "old": old_quantity,
                        "new": packed_quantity,
                    }
                    for line, old_quantity, packed_quantity in trims
                ]
            ))

    def _centric_return_pack_leftovers(self):
        """Send picked-but-not-packed units back from the Packing Zone to Stock.

        The leftover is computed per product and lot as (what the pick moves
        brought into the Packing Zone) minus (what this pack shipped out),
        clamped to zero and to what is actually still available un-reserved in
        the Packing Zone - so pre-existing phantom quants are never swept up.
        Negative-stock ``-N`` bucket lots are included on purpose: returning
        them to Stock lets the existing reconciler net them against real lots.
        The transfer is built explicitly (lots set on the lines - reservation
        and auto-lot both refuse -N lots) and validated immediately.
        """
        self.ensure_one()
        incoming = {}
        outgoing = {}
        origin_locations = {}
        origin_moves = self.env["stock.move"]
        for move in self.move_ids.filtered(lambda move: move.state == "done"):
            origin_moves |= move.move_orig_ids.filtered(
                lambda orig: orig.state == "done"
            )
            for move_line in move.move_line_ids:
                key = (move.product_id, move_line.lot_id)
                outgoing[key] = outgoing.get(key, 0.0) + move_line.product_uom_id._compute_quantity(
                    move_line.quantity, move.product_id.uom_id, rounding_method="HALF-UP"
                )
        for orig in origin_moves:
            origin_locations.setdefault(orig.product_id, orig.location_id)
            for move_line in orig.move_line_ids:
                key = (orig.product_id, move_line.lot_id)
                incoming[key] = incoming.get(key, 0.0) + move_line.product_uom_id._compute_quantity(
                    move_line.quantity, orig.product_id.uom_id, rounding_method="HALF-UP"
                )

        Quant = self.env["stock.quant"]
        source_location = self.location_id
        move_commands = []
        for (product, lot), quantity_in in incoming.items():
            leftover = quantity_in - outgoing.get((product, lot), 0.0)
            if product.uom_id.compare(leftover, 0.0) <= 0:
                continue
            # strict=True: exact location only, and (for lot keys) the
            # untracked bucket is excluded - otherwise pre-existing phantom
            # quants (untracked or in child locations) inflate every lot's
            # availability and the force-validated return re-mints the very
            # negative Packing Zone quants this feature exists to eliminate.
            available = Quant._get_available_quantity(
                product, source_location, lot_id=lot or None, strict=True,
            )
            leftover = min(leftover, available)
            if product.uom_id.compare(leftover, 0.0) <= 0:
                continue
            destination = origin_locations.get(product) or (
                self.picking_type_id.warehouse_id.lot_stock_id
            )
            move_commands.append(Command.create({
                "product_id": product.id,
                "product_uom": product.uom_id.id,
                "product_uom_qty": leftover,
                "location_id": source_location.id,
                "location_dest_id": destination.id,
                "company_id": self.company_id.id,
                "move_line_ids": [Command.create({
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "quantity": leftover,
                    "lot_id": lot.id if lot else False,
                    "location_id": source_location.id,
                    "location_dest_id": destination.id,
                    "company_id": self.company_id.id,
                })],
            }))

        if not move_commands:
            return self.env["stock.picking"]

        warehouse = self.picking_type_id.warehouse_id
        picking = self._centric_pack_leftover_picking_model().create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": source_location.id,
            "location_dest_id": (origin_locations and next(iter(origin_locations.values())) or warehouse.lot_stock_id).id,
            "origin": _("Pack leftovers of %s") % self.name,
            "company_id": self.company_id.id,
            "return_id": self.id,
            "move_ids": move_commands,
        })
        picking.action_confirm()
        for move in picking.move_ids:
            if move.product_uom.compare(move.quantity, move.product_uom_qty) != 0:
                move.quantity = move.product_uom_qty
            move.picked = True
        result = picking.button_validate()
        if result is not True:
            # Raising here rolls the WHOLE validation back (the PACK included),
            # so nothing half-happens - the message must reflect that: the
            # leftover transfer named in it will not exist after the rollback.
            raise UserError(_(
                "Validation cancelled: the un-packed leftovers of %(pack)s "
                "could not be returned to stock automatically. Nothing was "
                "validated - resolve the leftover stock in the Packing Zone "
                "and validate again.",
                pack=self.name,
            ))
        self.message_post(body=_(
            "Un-packed leftovers returned to stock: %s.") % picking.name)
        return picking

    def _centric_pack_leftover_picking_model(self):
        """stock.picking prepared with a context that is safe for the
        auto-created leftover return: every ``default_*`` key is dropped (a
        leaked default_move_type raises on stock.picking) along with the
        validation-context keys of the PACK being validated (the native
        no-backorder routing, the button-validate batch and the auto-print
        flag must not leak into the return's own validation), and the skip
        flags for every interceptor are set."""
        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not key.startswith("default_") and key not in (
                "picking_ids_not_to_backorder",
                "button_validate_picking_ids",
                "centric_print_pickings_after_validate",
            )
        }
        clean_context.update(
            skip_backorder=True,
            # Core product_expiry's expired-lot wizard fires on ANY picking
            # type; aged lots left on the packing bench are exactly what this
            # return carries, and a wizard here would surface as a validation
            # failure that rolls back the whole PACK. The stock physically
            # stays in the warehouse either way - returning it must never ask.
            skip_expired=True,
            skip_centric_expiry_check=True,
            centric_skip_pack_verify_check=True,
            centric_skip_pack_overpack_check=True,
            centric_skip_delivery_demand_check=True,
            centric_skip_pack_final=True,
            centric_skip_sale_carrier_sync=True,
            skip_centric_delivery_split_check=True,
        )
        return self.env["stock.picking"].with_context(clean_context)

    def action_centric_print_and_validate(self):
        pickings = self.filtered(lambda picking: picking.state != "cancel")
        pickings._centric_auto_fill_available_quantities()
        validation_action = pickings.with_context(
            centric_print_pickings_after_validate=pickings.ids
        ).button_validate()
        if isinstance(validation_action, dict):
            # Out of stock: button_validate defers to the backorder confirmation
            # popup instead of validating now, so we cannot print yet. The
            # context flag set above rides along into that popup's action (Odoo
            # copies the context onto the wizard), and the
            # stock.backorder.confirmation override prints the pick list once the
            # operator confirms - for both "Create Backorder" and "No Backorder".
            # Return the popup untouched so it displays and behaves as before.
            return validation_action
        report_action = pickings.do_print_picking()
        return pickings._centric_picking_print_dialog_action(report_action)

    def _centric_picking_print_dialog_action(self, report_action):
        """Deliver the standard picking report as an HTML page in a new browser
        tab so the browser print dialog opens automatically, instead of only
        downloading the PDF.

        ``do_print_picking`` has already flagged the pickings as printed and
        resolved the correct report; here we only change how that very same
        report reaches the user. The print dialog itself is triggered by the
        gated auto-print snippet injected into the ``stock.report_picking``
        template (see report/report_stockpicking_operations.xml). The original
        report action is returned untouched whenever the print URL cannot be
        built, so picking printing keeps working in every other situation.

        As a backup, the same snippet also auto-downloads a PDF of the very same
        report (``/report/pdf/<report>/<ids>``); the URL and a suggested file
        name are passed through the page context so the snippet can save it
        client-side before opening the print dialog.
        """
        print_url = self._centric_picking_print_url(report_action)
        if not print_url:
            return report_action
        return {
            "type": "ir.actions.act_url",
            "target": "new",
            "url": print_url,
        }

    def _centric_picking_print_client_action(self, report_action):
        """Same auto-print page as ``_centric_picking_print_dialog_action`` but
        wrapped in a client action that BOTH opens the print tab AND closes the
        calling dialog.

        This is the variant used after the out-of-stock backorder confirmation
        popup. That popup is a modal wizard, and returning a bare ``act_url``
        from a wizard opens the print tab but never closes the wizard, so the
        dialog stays up and the picks never appear to proceed to PACK (the list
        behind the dialog only reloads once the dialog closes). The client
        action ``centric_open_picking_print`` opens the very same print URL in a
        new tab and then returns ``act_window_close``, which dismisses the popup
        and lets the standard list reload run - so the picks proceed exactly as
        they do on the in-stock path. The plain report action is returned
        untouched whenever the print URL cannot be built.
        """
        print_url = self._centric_picking_print_url(report_action)
        if not print_url:
            return report_action
        return {
            "type": "ir.actions.client",
            "tag": "centric_open_picking_print",
            "params": {"url": print_url},
        }

    def _centric_picking_print_url(self, report_action):
        """Build the auto-print HTML URL for these pickings' standard report.

        Returns the ``/report/html/<report>/<ids>?context=...`` URL that opens
        the report as an HTML page which auto-triggers the browser print dialog
        (and, as a backup, auto-downloads the same report as a PDF) through the
        gated snippet injected into ``stock.report_picking`` (see
        report/report_stockpicking_operations.xml). Returns ``None`` whenever the
        URL cannot be built (no pickings, or the report action carries no
        ``report_name``), so callers can fall back to the plain report action.

        Both URLs carry the active companies explicitly: the web client sends its
        full user context - which holds ``allowed_company_ids`` - whenever it
        opens a report URL itself, but these URLs are opened as bare GETs in a new
        tab, and a bare GET inherits nothing. The render would then fall back to
        the user's own default company and the core multi-company rule refuses a
        transfer belonging to another one, so the print tab shows 403: Forbidden
        even though the right company is selected in the switcher.
        """
        if not self or not isinstance(report_action, dict):
            return None
        report_name = report_action.get("report_name")
        if not report_name:
            return None
        docids = ",".join(str(picking_id) for picking_id in self.ids)
        if len(self) == 1:
            # Strip characters that are illegal in file names (operators are on
            # Windows); picking names like CTWH/PICK/00056 -> CTWH-PICK-00056.
            safe = (self.name or "Pick List").translate(
                {ord(char): "-" for char in '\\/:*?"<>|'})
            pdf_name = "%s.pdf" % safe
        else:
            pdf_name = "Pick Lists.pdf"
        # Companies the user is not entitled to are dropped, so carrying the
        # transfers' own companies along never widens access.
        companies = self.env.companies | (
            self.mapped("company_id") & self.env.user.company_ids
        )
        # The backup PDF is fetched by the page as a second bare GET, so it needs
        # the companies just as much as the page itself does.
        pdf_context = quote(json.dumps({"allowed_company_ids": companies.ids}))
        context = quote(json.dumps({
            "centric_picking_auto_print": True,
            "centric_picking_pdf_url": "/report/pdf/%s/%s?context=%s" % (
                report_name, docids, pdf_context),
            "centric_picking_pdf_name": pdf_name,
            "allowed_company_ids": companies.ids,
        }))
        return f"/report/html/{report_name}/{docids}?context={context}"

    def action_assign(self):
        result = super().action_assign()
        self._centric_auto_fill_available_quantities()
        return result

    def action_centric_open_quantity_lines(self):
        self.ensure_one()
        self._centric_auto_fill_available_quantities()
        wizard = self.env["centric.stock.picking.quantity.wizard"].create_for_picking(self)
        return wizard.action_open()

    def _centric_quantity_moves(self):
        return self.move_ids.filtered(lambda move: move.state != "cancel")

    def _centric_auto_fill_available_quantities(self):
        moves = self.filtered(
            lambda picking: picking._centric_should_auto_fill_quantities()
        )._centric_quantity_moves().filtered(
            lambda move: (
                move.state not in ("done", "cancel")
                and move.product_uom.compare(move.product_uom_qty, 0.0) > 0
                and move.product_uom.is_zero(move.quantity)
            )
        )

        for move in moves:
            quantity = move._centric_quantity_available_to_fill()
            if move.product_uom.compare(quantity, 0.0) > 0:
                move.quantity = quantity

    def _centric_should_auto_fill_quantities(self):
        self.ensure_one()
        return self.state not in ("done", "cancel") and self._centric_van_stage_sequence() == 10

    @api.depends(
        "move_ids.product_uom_qty",
        "move_ids.quantity",
        "move_ids.x_pack_entered_qty",
        "move_ids.state",
    )
    def _compute_centric_pack_quantities(self):
        for picking in self:
            moves = picking._centric_quantity_moves()
            picking.centric_demand_quantity = sum(moves.mapped("product_uom_qty"))
            picking.centric_quantity = sum(moves.mapped("quantity"))
            picking.centric_pack_entered_qty = sum(moves.mapped("x_pack_entered_qty"))

    @api.depends("move_ids.x_pack_line_verified", "move_ids.state")
    def _compute_centric_quantity_verified(self):
        for picking in self:
            moves = picking._centric_quantity_moves().filtered(
                lambda move: move.state not in ("done", "cancel")
            )
            picking.centric_quantity_verified = bool(moves) and all(
                move.x_pack_line_verified for move in moves
            )

    centric_delivery_quantity_locked = fields.Boolean(
        compute="_compute_centric_delivery_quantity_locked",
        help="True on a customer delivery fed by the pick/pack chain: its "
             "quantities are the packed quantities and can never be amended.",
    )

    @api.depends(
        "picking_type_id",
        "location_dest_id",
        "move_ids.state",
        "move_ids.move_orig_ids",
    )
    def _compute_centric_delivery_quantity_locked(self):
        for picking in self:
            picking.centric_delivery_quantity_locked = (
                picking._centric_is_locked_customer_delivery()
            )

    @api.depends("move_ids.state")
    def _compute_centric_single_quantity_move(self):
        for picking in self:
            moves = picking._centric_quantity_moves().filtered(
                lambda move: move.state not in ("done", "cancel")
            )
            picking.centric_single_quantity_move = len(moves) == 1

    def _inverse_centric_quantity(self):
        # The inline board "Quantity" is a single picking-level figure. It is
        # only meaningful for a SINGLE-move picking, where it unambiguously sets
        # that one move. For a multi-move picking there is no sound way to split
        # one number across lines: the previous greedy fill front-loaded the
        # early moves, silently ZEROED the later ones and BALLOONED the last one
        # onto whatever was left over -- which is exactly how a delivery ended up
        # with one line at 291 and another at 0. Multi-line quantities MUST be
        # entered per line through the Items popup (the wizard writes each move
        # directly), so here we only ever set a genuine single-move picking and
        # never redistribute across several moves.
        #
        # Distributing the inline quantity does not mark the picking as verified;
        # the green "verified" flag is only ever set through the Items popup Save
        # (see action_save_quantities on the wizard).
        for picking in self:
            if picking._centric_is_locked_customer_delivery():
                # Packed quantity is final: delivery quantities are never
                # amended. Raised BEFORE any snapshot/write so a blocked edit
                # cannot log a phantom quantity-change audit message.
                raise UserError(_(
                    "Delivery quantities cannot be changed. The packed "
                    "quantity is the final quantity - adjust quantities at "
                    "PICK or PACK instead."
                ))
            moves = picking._centric_quantity_moves().filtered(
                lambda move: move.state not in ("done", "cancel")
            )
            if len(moves) == 1:
                # Snapshot the logged quantity from the moves BEFORE writing them
                # (picking.centric_quantity is already the new value here), then
                # log the change once the new quantity is in.
                before = sum(moves.mapped("quantity"))
                moves.quantity = max(picking.centric_quantity, 0.0)
                picking._centric_track_first_logged_quantity({picking.id: before})
