from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


# Sentinel stored on a wizard line whose quantity the operator has NOT entered
# yet. Real packed/picked quantities are always >= 0, so a negative value can
# never be a genuine entry; the centric_required_quantity widget renders it as a
# blank cell (see static/src/js/required_quantity_field.js) and Save rejects it.
_QTY_NOT_ENTERED = -1.0


class StockPickingQuantityWizard(models.TransientModel):
    _name = "centric.stock.picking.quantity.wizard"
    _description = "Stock Picking Quantity Wizard"

    picking_id = fields.Many2one(
        "stock.picking",
        required=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        "centric.stock.picking.quantity.wizard.line",
        "wizard_id",
        string="Items",
        copy=False,
    )
    
    def action_save_quantities(self):
        self.ensure_one()

        # Every line must have a quantity the operator actually entered. 0 is a
        # valid entry (out of stock / short-ship) - it just has to be typed, not
        # left blank. A blank/not-entered line carries the negative sentinel, so
        # any line still < 0 is rejected. (The required field + the widget's
        # isEmpty already block this in the browser; this is the server-side
        # backstop.)
        missing_lines = self.line_ids.filtered(
            lambda line: line.product_uom.compare(line.quantity, 0.0) < 0
        )
        if missing_lines:
            raise ValidationError(
                _("Please enter a quantity for every item before saving (0 is allowed).")
            )

        changed_lines = self.line_ids.filtered(lambda line: line._centric_has_quantity_change())

        # Packed quantity is final: a chain-fed customer delivery never has its
        # quantities amended - not through this popup either. Saving with no
        # quantity changes stays allowed (it only flags lines as reviewed).
        if changed_lines and self.picking_id._centric_is_locked_customer_delivery():
            raise ValidationError(_(
                "Delivery quantities cannot be changed. The packed quantity is "
                "the final quantity - adjust quantities at PICK or PACK instead."
            ))

        # Snapshot the logged quantity BEFORE applying the entered values, so the
        # audit log ("First Logged Quantity") can post once on a genuine change.
        picking = self.picking_id
        logged_before = picking._centric_logged_quantity()

        for line in changed_lines:
            move = line.move_id
            # PACK writes to x_pack_entered_qty; PICK/DELIVERY keep writing the
            # standard quantity. Reserved stock quantity is never touched for
            # PACK, so Odoo reservation logic stays intact.
            move[move._centric_editable_quantity_field()] = line.quantity

        # Pressing Save means the operator has reviewed and confirmed every line
        # shown, so each line is flagged verified (green). This is per-line UI
        # status only and never affects stock; the picking-level green flag is a
        # computed roll-up of these per-line flags. Discard (special="cancel")
        # never reaches this method, so it never marks lines verified.
        self.line_ids.move_id.x_pack_line_verified = True

        # First Logged Quantity audit: records the first logged total once and
        # posts a single message if it later changes (replaces the removed Studio
        # automation "Track Inventory Quantity Change"). No-op where the field is
        # absent.
        picking._centric_track_first_logged_quantity({picking.id: logged_before})

        return {
            "type": "ir.actions.client",
            "tag": "centric_highlight_stock_picking",
            "params": {
                "picking_id": self.picking_id.id,
            },
        }

    def action_open(self):
        self.ensure_one()
        view = self.env.ref(
            "centric_delivery_method_customisation.view_stock_picking_quantity_wizard_form"
        )
        title_parts = [self.picking_id.name]
        if self.picking_id.centric_loadsheet_category_id:
            title_parts.append(self.picking_id.centric_loadsheet_category_id.display_name)
        return {
            "type": "ir.actions.act_window",
            "name": _("Items - %s") % " / ".join(title_parts),
            "res_model": self._name,
            "view_mode": "form",
            "views": [(view.id, "form")],
            "res_id": self.id,
            "target": "new",
            "context": dict(self.env.context, dialog_size="large"),
        }

    @api.model
    def create_for_picking(self, picking):
        moves = picking._centric_quantity_moves().sorted(lambda move: (move.sequence, move.id))
        wizard = self.create({
            "picking_id": picking.id,
            "line_ids": [
                fields.Command.create({
                    "move_id": move.id,
                    "quantity": self._centric_initial_line_quantity(move),
                })
                for move in moves
            ],
        })
        return wizard

    @api.model
    def _centric_initial_line_quantity(self, move):
        """Initial value shown in the Items popup for a move.

        - A move already CONFIRMED via the wizard (``x_pack_line_verified`` /
          green row) shows its stored value, even if that value is 0. The
          operator already entered it, so reopening the popup - e.g. to adjust a
          different line - must NOT blank it out or force it to be re-typed. This
          is the key: x_pack_entered_qty of 0 means "not entered" for a fresh
          line but "deliberately packed 0" (out of stock / short-ship) once the
          line has been confirmed, and the verified flag is what tells them apart.
        - Otherwise a move that still carries a real value (> 0 - e.g. a PICK
          line auto-filled with the available quantity) shows it.
        - A move with nothing entered yet - the usual fresh PACK line, packed
          quantity 0 and not yet confirmed - is shown BLANK via the not-entered
          sentinel, so the operator must type the quantity (0 included) instead
          of accepting a pre-filled 0.
        """
        prefill = move[move._centric_editable_quantity_field()]
        if move.x_pack_line_verified:
            return prefill
        if move.product_uom.compare(prefill, 0.0) > 0:
            return prefill
        return _QTY_NOT_ENTERED


class StockPickingQuantityWizardLine(models.TransientModel):
    _name = "centric.stock.picking.quantity.wizard.line"
    _description = "Stock Picking Quantity Wizard Line"
    _order = "id"

    wizard_id = fields.Many2one(
        "centric.stock.picking.quantity.wizard",
        required=True,
        ondelete="cascade",
    )
    move_id = fields.Many2one(
        "stock.move",
        required=True,
        readonly=True,
    )
    verified = fields.Boolean(
        string="Confirmed",
        related="move_id.x_pack_line_verified",
        readonly=True,
    )
    show_details_visible = fields.Boolean(
        related="move_id.show_details_visible",
        readonly=True,
    )
    product_id = fields.Many2one(
        "product.product",
        related="move_id.product_id",
        readonly=True,
    )
    centric_loadsheet_category_id = fields.Many2one(
        "centric.loadsheet.category",
        related="move_id.centric_loadsheet_category_id",
        readonly=True,
    )
    product_uom_qty = fields.Float(
        related="move_id.product_uom_qty",
        readonly=True,
    )
    quantity = fields.Float(
        digits="Product Unit",
        required=True,
    )
    product_uom = fields.Many2one(
        "uom.uom",
        related="move_id.product_uom",
        readonly=True,
    )
    centric_unit_price = fields.Monetary(
        string="Unit Price",
        related="move_id.centric_unit_price",
        currency_field="centric_currency_id",
        readonly=True,
    )
    centric_currency_id = fields.Many2one(
        "res.currency",
        related="move_id.centric_currency_id",
        readonly=True,
    )
    centric_operation_note = fields.Text(
        related="move_id.centric_operation_note",
        readonly=True,
    )
    centric_sale_order_note = fields.Text(
        related="move_id.centric_sale_order_note",
        readonly=True,
    )
    state = fields.Selection(
        related="move_id.state",
        readonly=True,
    )
    centric_quantity_locked = fields.Boolean(
        compute="_compute_centric_quantity_locked",
        help="Quantities on a chain-fed customer delivery are the packed "
             "quantities and cannot be edited.",
    )

    @api.depends("move_id.picking_id")
    def _compute_centric_quantity_locked(self):
        for line in self:
            picking = line.move_id.picking_id
            line.centric_quantity_locked = bool(
                picking
            ) and picking._centric_is_locked_customer_delivery()

    def action_centric_show_details(self):
        self.ensure_one()
        return self.move_id.action_centric_show_details()

    def _centric_has_quantity_change(self):
        self.ensure_one()
        move = self.move_id
        current_quantity = move[move._centric_editable_quantity_field()]
        return move.product_uom.compare(self.quantity, current_quantity) != 0
