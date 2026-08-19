from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain


class StockMove(models.Model):
    _inherit = "stock.move"

    def unlink(self):
        # Packed quantity is final: removing a line from a chain-fed customer
        # delivery would ship less than was packed (the validation check only
        # sees the moves that remain). Deleting the delivery line is therefore
        # blocked; cancelling the WHOLE delivery stays possible (that goes
        # through action_cancel, not unlink) and draft/cancelled moves - e.g.
        # an accidentally added line - can still be removed.
        blocked = self.filtered(
            lambda move: move.state not in ("draft", "cancel")
            and move.picking_id
            and move.picking_id._centric_is_locked_customer_delivery()
        )
        if blocked and not self.env.context.get("centric_skip_delivery_demand_check"):
            raise UserError(_(
                "Delivery lines cannot be removed. The packed quantity is the "
                "final quantity - a delivery ships exactly what was packed. "
                "Cancel the whole delivery instead if it must not go out."
            ))
        return super().unlink()

    centric_loadsheet_category_id = fields.Many2one(
        "centric.loadsheet.category",
        related="product_id.centric_loadsheet_category_id",
        store=True,
        readonly=True,
    )
    # Exposed from the picking so the picking-type "Operations" (moves) view can be
    # grouped by carrier/route alongside the loadsheet category. carrier_id is a
    # stock.picking field (stock_delivery); without this related copy a group_by on
    # carrier_id over stock.move raises "Invalid field 'carrier_id'".
    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Shipping Method",
        related="picking_id.carrier_id",
        store=True,
        readonly=True,
    )
    centric_operation_note = fields.Text(
        string="Operation Note",
        compute="_compute_centric_operation_note",
    )
    centric_sale_order_note = fields.Text(
        string="Order Note",
        related="picking_id.centric_sale_order_note",
        readonly=True,
    )
    x_pack_entered_qty = fields.Float(
        string="Pack Entered Qty",
        digits="Product Unit",
        copy=False,
        help="Quantity the operator counts for this line in the PACK Items "
             "popup. During packing it is a separate working/verification value "
             "that never touches reservation logic. At PACK validation it "
             "becomes the source of truth for execution: it is copied into the "
             "move's done quantity (stock.move.quantity) so Odoo delivers exactly "
             "what was packed and natively backorders the rest. Used only for "
             "PACK; PICK and DELIVERY keep using the standard quantity field.",
    )
    x_pack_line_verified = fields.Boolean(
        string="Pack Line Verified",
        copy=False,
        default=False,
        help="UI/operational status only: True once the operator has reviewed "
             "and confirmed (saved) this line in the PACK Items popup. Drives "
             "the green per-line highlight and gates PACK validation. It never "
             "affects stock quantity, reservation or valuation.",
    )
    # Display-only reference price surfaced on the Pick/Pack Items popup. It is a
    # non-stored computed field, so it only ever READS existing data and can never
    # influence stock, valuation, reservation, pricing or invoicing.
    centric_unit_price = fields.Monetary(
        string="Unit Price",
        compute="_compute_centric_unit_price",
        currency_field="centric_currency_id",
        help="Display-only reference price: the linked sale order line's unit "
             "price when available, otherwise the product's sales price.",
    )
    centric_currency_id = fields.Many2one(
        "res.currency",
        string="Unit Price Currency",
        compute="_compute_centric_unit_price",
    )

    def _key_assign_picking(self):
        self.ensure_one()
        keys = super()._key_assign_picking()
        if self._centric_splits_by_loadsheet_category():
            keys += (self._centric_loadsheet_category(),)
        return keys

    def _search_picking_for_assignation_domain(self):
        self.ensure_one()
        domain = super()._search_picking_for_assignation_domain()
        if self._centric_splits_by_loadsheet_category():
            category = self._centric_loadsheet_category()
            category_condition = (
                "centric_loadsheet_category_id",
                "=",
                category.id or False,
            )
            if isinstance(domain, list):
                domain.append(category_condition)
            else:
                domain &= Domain(*category_condition)
        return domain

    def _get_new_picking_values(self):
        vals = super()._get_new_picking_values()
        first_move = self[:1]
        if first_move._centric_splits_by_loadsheet_category():
            category = first_move._centric_loadsheet_category()
            vals["centric_loadsheet_category_id"] = category.id or False
        return vals

    def _centric_loadsheet_category(self):
        self.ensure_one()
        return self.product_id.centric_loadsheet_category_id

    def _centric_splits_by_loadsheet_category(self):
        self.ensure_one()
        picking_type = self.picking_type_id
        operation_names = {
            (picking_type.name or "").strip().casefold(),
            (picking_type.sequence_code or "").strip().casefold(),
        }
        return picking_type.code == "outgoing" or bool(operation_names & {"pick", "pack"})

    def _centric_is_pack_operation_move(self):
        self.ensure_one()
        picking_type = self.picking_type_id
        operation_names = {
            (picking_type.name or "").strip().casefold(),
            (picking_type.sequence_code or "").strip().casefold(),
        }
        return "pack" in operation_names

    def _centric_editable_quantity_field(self):
        """Field the Items popup reads and writes for this move.

        PACK quantities are captured in the dedicated ``x_pack_entered_qty``
        field so Odoo's reserved ``quantity`` and all reservation logic stay
        completely untouched. PICK and DELIVERY keep using the standard
        ``quantity`` field exactly as before.
        """
        self.ensure_one()
        return "x_pack_entered_qty" if self._centric_is_pack_operation_move() else "quantity"

    def _centric_quantity_available_to_fill(self):
        self.ensure_one()
        if self.move_orig_ids.filtered(lambda move: move.state not in ("done", "cancel")):
            return 0.0

        if not self.product_id.is_storable or self._should_bypass_reservation():
            return self.product_uom_qty

        demand_quantity = self.product_uom._compute_quantity(
            self.product_uom_qty,
            self.product_id.uom_id,
            rounding_method="HALF-UP",
        )
        available_quantity = self.env["stock.quant"]._get_available_quantity(
            self.product_id,
            self.location_id,
        )
        if self.product_id.uom_id.compare(available_quantity, demand_quantity) < 0:
            return 0.0
        return self.product_uom_qty

    def _centric_pick_report_lot_summary(self):
        """Per-lot breakdown of this move's quantities for the pick list PDF.

        The pick list prints one row per move so it matches the transfer's
        Items popup: a product reserved out of several lots is still ONE line
        carrying the full quantity, exactly like any single-lot line. This
        summary feeds the small sub-lines under the product name with each
        lot's own share. It mirrors the report's line filter (entire-pack move
        lines are skipped) and merges move lines that picked the same lot from
        different locations. Shares are converted into the move's unit the
        same way the popup quantity is computed - no per-line rounding, one
        display rounding at the end - so they always add up to the printed
        row total. Quantity sitting on lines that have no lot yet is reported
        as a trailing lot-less entry instead of being silently folded into
        another lot's share; an untracked product has no lot lines at all and
        returns no entries.
        """
        self.ensure_one()
        summary = []
        by_lot = {}
        no_lot_quantity = 0.0
        lines = self.move_line_ids.filtered(lambda ml: not ml.is_entire_pack)
        for line in lines.sorted(
            key=lambda ml: (
                ml.location_id.complete_name or "",
                ml.location_dest_id.complete_name or "",
            )
        ):
            quantity = line.product_uom_id._compute_quantity(
                line.quantity, self.product_uom, round=False
            )
            name = line.lot_id.name or line.lot_name
            if not name:
                no_lot_quantity += quantity
                continue
            key = line.lot_id.id or name
            entry = by_lot.get(key)
            if entry is None:
                expiration = False
                if line.lot_id and "expiration_date" in line.lot_id._fields:
                    expiration = line.lot_id.expiration_date
                entry = {
                    "lot": line.lot_id,
                    "name": name,
                    "quantity": 0.0,
                    "expiration_date": expiration,
                }
                by_lot[key] = entry
                summary.append(entry)
            entry["quantity"] += quantity
        if summary and self.product_uom.compare(no_lot_quantity, 0.0) > 0:
            summary.append({
                "lot": self.env["stock.lot"],
                "name": False,
                "quantity": no_lot_quantity,
                "expiration_date": False,
            })
        for entry in summary:
            entry["quantity"] = self.product_uom.round(entry["quantity"])
        return summary

    def action_centric_show_details(self):
        self.ensure_one()
        if self.picking_id:
            self.picking_id._centric_auto_fill_available_quantities()
        action = self.action_show_details()
        action["context"] = dict(
            action.get("context") or {},
            centric_show_lots_serials=True,
        )
        return action

    @api.depends(
        "sale_line_id.price_unit",
        "sale_line_id.currency_id",
        "product_id.lst_price",
        "company_id.currency_id",
    )
    def _compute_centric_unit_price(self):
        for move in self:
            currency = move.company_id.currency_id or move.env.company.currency_id
            if move.sale_line_id:
                move.centric_unit_price = move.sale_line_id.price_unit
                move.centric_currency_id = move.sale_line_id.currency_id or currency
            else:
                move.centric_unit_price = move.product_id.lst_price
                move.centric_currency_id = currency

    @api.depends("sale_line_id.name", "description_picking", "product_id.name", "product_id.display_name")
    def _compute_centric_operation_note(self):
        for move in self:
            move.centric_operation_note = (
                move._centric_sale_line_note()
                or move._centric_extract_operation_note(move.description_picking)
            )

    def _centric_sale_line_note(self):
        """The text an operator actually typed on the sale order line.

        ``_centric_extract_operation_note`` treats everything after the first
        line as a note, but a sale order line description is generated as
        ``product name`` + newline + the product's **Sales Description**. So a
        product that carries a Sales Description had it copied onto the picking
        as though someone had typed it, printing the same text twice.

        The generated text is asked for directly and stripped off the front,
        leaving only what was added by hand. When the description does not start
        with the generated text it has been rewritten wholesale, and there is no
        way to tell a note from a replacement -- so the older heuristic still
        applies there and the text keeps reaching the warehouse.
        """
        self.ensure_one()
        line = self.sale_line_id
        if not line:
            return False
        name = (line.name or "").strip()
        generated = (
            line._get_sale_order_line_multiline_description_sale() or ""
        ).strip()
        if generated and name.startswith(generated):
            return name[len(generated):].strip() or False
        return self._centric_extract_operation_note(name)

    def _centric_extract_operation_note(self, text):
        self.ensure_one()
        lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
        if not lines:
            return False

        if len(lines) > 1:
            return "\n".join(lines[1:]).strip() or False

        line = lines[0]
        product_names = {self.product_id.name, self.product_id.display_name}
        return False if line in product_names else line

    @api.depends(
        "product_id",
        "picking_type_id",
        "description_picking_manual",
        "sale_line_id",
        "sale_line_id.name",
    )
    def _compute_description_picking(self):
        """Carry the sale order line's note into the move's picking description.

        Native Odoo only feeds the *variant* description into
        ``description_picking``; the free text an operator types on the sale
        order line (e.g. "no onions") is dropped. Appending it here surfaces the
        note wherever ``description_picking`` already shows - the transfer's
        Operations tab ("Description" field), the delivery slip and the picking
        report - so it stays visible through every internal step.

        It is only appended when the operator has not manually overridden the
        description (``description_picking_manual``), keeping the field editable.
        """
        super()._compute_description_picking()
        for move in self:
            if not move.sale_line_id or move.description_picking_manual:
                continue
            note = move._centric_sale_line_note()
            if not note:
                continue
            current = (move.description_picking or "").strip()
            move.description_picking = f"{current}\n{note}".strip() if current else note
