from odoo import _, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    not_delivered_origin_id = fields.Many2one(
        "stock.picking",
        string="Original Not Delivered Delivery",
        copy=False,
        readonly=True,
    )
    not_delivered_replacement_id = fields.Many2one(
        "stock.picking",
        string="Replacement Delivery",
        copy=False,
        readonly=True,
    )
    not_delivered_credit_note_ids = fields.Many2many(
        "account.move",
        "stock_picking_not_delivered_credit_note_rel",
        "picking_id",
        "move_id",
        string="Not Delivered Credit Notes",
        copy=False,
        readonly=True,
    )
    not_delivered_return_picking_id = fields.Many2one(
        "stock.picking",
        string="Not Delivered Return",
        copy=False,
        readonly=True,
    )

    # -------------------------------------------------------------------------
    # Main flow
    # -------------------------------------------------------------------------
    def action_not_delivered(self):
        self.ensure_one()
        picking = self

        if picking.state != "done":
            raise UserError(_("Only done deliveries can be marked as Not Delivered."))
        if picking.picking_type_code != "outgoing":
            raise UserError(_("Only outgoing deliveries can be marked as Not Delivered."))
        if picking.not_delivered_replacement_id:
            raise UserError(_("This delivery already has a replacement delivery: %s") % picking.not_delivered_replacement_id.display_name)
        # Replacement deliveries can also be marked as Not Delivered again.
        # The flow must be repeatable if a second attempted delivery also fails.

        sale_order = picking.sale_id
        if not sale_order:
            raise UserError(_("This delivery is not linked to a Sales Order."))

        credit_notes = picking._handle_not_delivered_invoices(sale_order)
        return_picking = picking._create_and_validate_not_delivered_return()
        new_picking = picking._copy_not_delivered_replacement_delivery()

        picking.write({
            "not_delivered_replacement_id": new_picking.id,
            "not_delivered_return_picking_id": return_picking.id,
            "not_delivered_credit_note_ids": [(6, 0, credit_notes.ids)],
        })

        picking.message_post(body=_(
            "Delivery marked as Not Delivered. Credit notes: %(credit_notes)s. "
            "Return transfer: %(return_picking)s. Replacement delivery: %(new_picking)s."
        ) % {
            "credit_notes": ", ".join(credit_notes.mapped("name")) or _("None"),
            "return_picking": return_picking.display_name,
            "new_picking": new_picking.display_name,
        })

        return {
            "type": "ir.actions.act_window",
            "name": _("Delivery Orders"),
            "res_model": "stock.picking",
            "view_mode": "form",
            "res_id": new_picking.id,
            "target": "current",
            "context": {
                "default_picking_type_id": picking.picking_type_id.id,
                "default_company_id": picking.company_id.id,
            },
        }

    # -------------------------------------------------------------------------
    # Invoice / credit note
    # -------------------------------------------------------------------------
    def _handle_not_delivered_invoices(self, sale_order):
        all_posted_invoices = sale_order.invoice_ids.filtered(
            lambda inv: inv.move_type == "out_invoice" and inv.state == "posted"
        )

        # The flow can happen more than once. Do not credit-note the same invoice
        # again if it was already reversed in a previous Not Delivered cycle.
        already_reversed_invoice_ids = set(self.env["account.move"].search([
            ("move_type", "=", "out_refund"),
            ("reversed_entry_id", "in", all_posted_invoices.ids),
            ("state", "!=", "cancel"),
        ]).mapped("reversed_entry_id").ids)

        posted_invoices = all_posted_invoices.filtered(
            lambda inv: inv.id not in already_reversed_invoice_ids
        )
        posted_invoices = posted_invoices.sorted(
            key=lambda inv: inv.invoice_date or inv.date or inv.create_date or fields.Datetime.now(),
            reverse=True,
        )

        draft_invoices = sale_order.invoice_ids.filtered(
            lambda inv: inv.move_type == "out_invoice" and inv.state == "draft"
        )

        credit_notes = self.env["account.move"]
        if posted_invoices:
            credit_notes = self._create_not_delivered_credit_notes(posted_invoices)
        if draft_invoices:
            draft_invoices.unlink()
        return credit_notes

    def _create_not_delivered_credit_notes(self, invoices):
        credit_notes = self.env["account.move"]
        Reversal = self.env["account.move.reversal"]

        for invoice in invoices:
            before = self.env["account.move"].search([
                ("move_type", "=", "out_refund"),
                ("reversed_entry_id", "=", invoice.id),
                ("state", "!=", "cancel"),
            ])

            reversal_vals = {}
            if "reason" in Reversal._fields:
                reversal_vals["reason"] = _("Delivery not completed / Not delivered")
            if "journal_id" in Reversal._fields and invoice.journal_id:
                reversal_vals["journal_id"] = invoice.journal_id.id
            if "date" in Reversal._fields:
                reversal_vals["date"] = fields.Date.context_today(self)
            if "refund_method" in Reversal._fields:
                reversal_vals["refund_method"] = "refund"

            reversal = Reversal.with_context(
                active_model="account.move",
                active_ids=invoice.ids,
            ).create(reversal_vals)
            reversal.reverse_moves()

            after = self.env["account.move"].search([
                ("move_type", "=", "out_refund"),
                ("reversed_entry_id", "=", invoice.id),
                ("state", "!=", "cancel"),
            ])
            created = after - before
            for refund in created.filtered(lambda m: m.state == "draft"):
                refund.action_post()
            credit_notes |= created

        return credit_notes

    # -------------------------------------------------------------------------
    # Return original delivery
    # -------------------------------------------------------------------------
    def _create_and_validate_not_delivered_return(self):
        self.ensure_one()
        picking = self

        ReturnWizard = self.env["stock.return.picking"]
        wizard = ReturnWizard.with_context(
            active_id=picking.id,
            active_ids=picking.ids,
            active_model="stock.picking",
        ).create({})

        if not wizard.product_return_moves:
            raise UserError(_("No returnable products were found for this delivery."))

        picking._set_return_wizard_quantities(wizard)
        if not any(line.quantity for line in wizard.product_return_moves):
            raise UserError(_("Odoo prepared a return transfer with zero quantities. Please check the original delivery quantities."))

        if hasattr(wizard, "action_create_returns"):
            action = wizard.action_create_returns() or {}
            return_picking_id = action.get("res_id")
            if not return_picking_id and action.get("domain"):
                return_picking_id = self.env["stock.picking"].search(action["domain"], limit=1).id
        elif hasattr(wizard, "_create_returns"):
            return_picking_id, _picking_type_id = wizard._create_returns()
        else:
            raise UserError(_("This Odoo version does not expose a return creation method on stock.return.picking."))

        return_picking = self.env["stock.picking"].browse(return_picking_id)
        if not return_picking.exists():
            raise UserError(_("Odoo did not create a return transfer."))

        picking._try_auto_validate_not_delivered_return(return_picking)

        # IMPORTANT: do not block the Not Delivered flow if the return cannot be
        # auto-validated. Some Odoo 19 / 3-step warehouse configurations open an
        # immediate transfer, backorder, package, or barcode wizard instead of
        # finishing the return directly. The replacement delivery must still be
        # created and opened in Delivery Orders.
        if return_picking.state != "done":
            return_picking.message_post(body=_(
                "This return transfer was created by the Not Delivered flow, "
                "but Odoo did not allow automatic validation. Validate this "
                "return manually if stock needs to be restored."
            ))

        return return_picking

    def _try_auto_validate_not_delivered_return(self, return_picking):
        """Best-effort validation for the stock return.

        This must never raise a UserError that stops replacement delivery
        creation. In this client's Odoo 19 database, returns may require an
        extra wizard/manual step depending on warehouse configuration.
        """
        self.ensure_one()

        try:
            if return_picking.state == "draft":
                return_picking.action_confirm()
            if return_picking.state not in ("assigned", "done", "cancel"):
                return_picking.action_assign()

            self._set_done_quantities_for_validation(return_picking)

            result = return_picking.with_context(
                skip_immediate=True,
                skip_backorder=True,
                button_validate_picking_ids=return_picking.ids,
            ).button_validate()

            self._process_stock_validation_action(result, return_picking)
        except Exception as error:
            # Do not break the business flow. Keep the error on the return
            # transfer chatter for debugging, then continue with replacement
            # delivery creation.
            return_picking.message_post(body=_(
                "Automatic validation failed during Not Delivered flow: %s"
            ) % str(error))

        return return_picking

    def _process_stock_validation_action(self, action, picking):
        """Try to process standard stock validation wizards returned by button_validate.

        Odoo may return stock.immediate.transfer or stock.backorder.confirmation.
        This method is intentionally defensive because Odoo 19 branches can have
        slightly different wizard fields/methods.
        """
        if not isinstance(action, dict):
            return False

        res_model = action.get("res_model")
        if not res_model or res_model not in self.env:
            return False

        Wizard = self.env[res_model]
        ctx = action.get("context") or {}
        wizard = self.env[res_model]

        if action.get("res_id"):
            wizard = Wizard.browse(action["res_id"])
        else:
            vals = {}
            if "pick_ids" in Wizard._fields:
                vals["pick_ids"] = [(4, picking.id)]
            if "show_transfers" in Wizard._fields:
                vals["show_transfers"] = False
            wizard = Wizard.with_context(ctx).create(vals)

            if "immediate_transfer_line_ids" in Wizard._fields:
                line_model = self.env[Wizard._fields["immediate_transfer_line_ids"].comodel_name]
                line_vals = {}
                if "picking_id" in line_model._fields:
                    line_vals["picking_id"] = picking.id
                if "to_immediate" in line_model._fields:
                    line_vals["to_immediate"] = True
                if line_vals:
                    wizard.write({"immediate_transfer_line_ids": [(0, 0, line_vals)]})

        for method_name in ("process", "process_cancel_backorder", "process_validate"):
            if hasattr(wizard, method_name):
                getattr(wizard, method_name)()
                return True

        return False

    def _set_return_wizard_quantities(self, wizard):
        for line in wizard.product_return_moves:
            if line.quantity:
                continue
            move = line.move_id
            qty = self._get_done_quantity_from_move(move)
            if qty:
                line.quantity = qty

    def _set_done_quantities_for_validation(self, picking):
        moves = self._get_picking_moves_compat(picking).filtered(lambda m: m.state not in ("done", "cancel"))

        for move in moves:
            qty = self._get_ordered_quantity_from_move(move) or self._get_done_quantity_from_move(move)
            if not qty:
                continue

            move_lines = self._get_move_lines_compat(move, picking)
            if not move_lines:
                continue

            remaining = qty
            for line in move_lines:
                if remaining <= 0:
                    break

                line_qty = self._get_reserved_quantity_from_move_line(line) or remaining
                line_qty = min(line_qty, remaining)

                if "quantity" in line._fields:
                    line.quantity = line_qty
                elif "qty_done" in line._fields:
                    line.qty_done = line_qty

                if "picked" in line._fields:
                    line.picked = True

                remaining -= line_qty

    # -------------------------------------------------------------------------
    # Replacement delivery - FIXED APPROACH
    # -------------------------------------------------------------------------
    def _copy_not_delivered_replacement_delivery(self):
        """Create the new delivery by copying the original picking.

        Previous versions tried to manually create stock.moves. This Odoo 19
        branch has different field names on sale.order.line and stock.move, so
        manual move creation is fragile. Copying lets Odoo reuse its own copy_data
        logic for the installed stock model and avoids fields like stock.move.name,
        sale.order.line.product_uom, procurement_group_id, etc.
        """
        self.ensure_one()
        picking = self
        sale_order = picking.sale_id

        Picking = self.env["stock.picking"]
        defaults = {}

        if "origin" in Picking._fields:
            defaults["origin"] = sale_order.name
        if "sale_id" in Picking._fields:
            defaults["sale_id"] = sale_order.id
        if "not_delivered_origin_id" in Picking._fields:
            defaults["not_delivered_origin_id"] = picking.id
        if "not_delivered_replacement_id" in Picking._fields:
            defaults["not_delivered_replacement_id"] = False
        if "not_delivered_return_picking_id" in Picking._fields:
            defaults["not_delivered_return_picking_id"] = False
        if "not_delivered_credit_note_ids" in Picking._fields:
            defaults["not_delivered_credit_note_ids"] = [(5, 0, 0)]
        if "date_done" in Picking._fields:
            defaults["date_done"] = False
        if "scheduled_date" in Picking._fields:
            defaults["scheduled_date"] = fields.Datetime.now()
        if "backorder_id" in Picking._fields:
            defaults["backorder_id"] = False

        new_picking = picking.copy(defaults)

        # Confirm/assign using native stock logic. Do not write state manually.
        if new_picking.state == "draft":
            new_picking.action_confirm()
        if new_picking.state not in ("assigned", "done", "cancel"):
            new_picking.action_assign()

        if new_picking.state == "done":
            raise UserError(_(
                "Odoo copied the replacement delivery as Done. This should not happen; "
                "please check custom copy logic on stock.picking."
            ))

        new_picking.message_post(body=_(
            "Replacement delivery created by copying original delivery %s after it was marked as Not Delivered."
        ) % picking.display_name)

        return new_picking

    # -------------------------------------------------------------------------
    # Auto-invoice replacement delivery when validated
    # -------------------------------------------------------------------------
    def button_validate(self):
        result = super().button_validate()

        for picking in self:
            if picking.state != "done":
                continue
            if picking.picking_type_code != "outgoing":
                continue
            if not picking.not_delivered_origin_id:
                continue
            picking._create_invoice_after_not_delivered_replacement_done()

        return result

    def _create_invoice_after_not_delivered_replacement_done(self):
        self.ensure_one()
        picking = self
        sale_order = picking.sale_id
        if not sale_order:
            return

        if sale_order.invoice_status != "to invoice":
            picking.message_post(body=_(
                "Replacement delivery was completed, but no invoice was created because the Sales Order invoice status is '%s'."
            ) % sale_order.invoice_status)
            return

        if not hasattr(sale_order, "_create_invoices"):
            picking.message_post(body=_("Invoice was not created because sale.order has no _create_invoices method."))
            return

        invoice_date = fields.Datetime.context_timestamp(
            picking,
            picking.date_done or fields.Datetime.now(),
        ).date()

        # Put the delivery date on the Sales Order and pass it in context.
        # sale.order._prepare_invoice() in this module injects that date into the
        # invoice values BEFORE the account.move is created/posted.
        # Important: do NOT write invoice_date on a posted invoice here.
        if "not_delivered_next_invoice_date" in sale_order._fields:
            sale_order.not_delivered_next_invoice_date = invoice_date

        sale_order_with_date = sale_order.with_context(
            not_delivered_invoice_date=invoice_date,
            default_invoice_date=invoice_date,
            invoice_date=invoice_date,
        )
        invoice = sale_order_with_date._create_invoices()
        if not invoice:
            return

        for move in invoice:
            if move.state == "draft":
                # invoice_date should already be set by _prepare_invoice.
                # Only set it while still draft as a last safe fallback.
                if "invoice_date" in move._fields and not move.invoice_date:
                    move.write({"invoice_date": invoice_date})
                move.action_post()

        picking.message_post(body=_(
            "New invoice %(invoice)s was created using delivery date %(date)s."
        ) % {
            "invoice": ", ".join(invoice.mapped("name")),
            "date": invoice_date,
        })

    # -------------------------------------------------------------------------
    # Compatibility helpers
    # -------------------------------------------------------------------------
    def _get_picking_moves_compat(self, picking):
        StockMove = self.env["stock.move"]
        for field_name in ("move_ids", "move_lines", "move_ids_without_package"):
            if field_name in picking._fields:
                return picking[field_name]
        return StockMove.search([("picking_id", "=", picking.id)])

    def _get_move_lines_compat(self, move, picking=None):
        StockMoveLine = self.env["stock.move.line"]
        if "move_line_ids" in move._fields:
            lines = move.move_line_ids
            if lines:
                return lines
        domain = [("move_id", "=", move.id)]
        if picking and "picking_id" in StockMoveLine._fields:
            domain = ["|", ("move_id", "=", move.id), ("picking_id", "=", picking.id)]
        return StockMoveLine.search(domain)

    def _get_done_quantity_from_move(self, move):
        if not move:
            return 0.0
        for field_name in ("quantity", "quantity_done", "qty_done"):
            if field_name in move._fields and move[field_name]:
                return move[field_name]
        qty = 0.0
        if "move_line_ids" in move._fields:
            for line in move.move_line_ids:
                for field_name in ("quantity", "qty_done"):
                    if field_name in line._fields and line[field_name]:
                        qty += line[field_name]
                        break
        return qty

    def _get_ordered_quantity_from_move(self, move):
        if not move:
            return 0.0
        for field_name in ("product_uom_qty", "product_qty", "quantity"):
            if field_name in move._fields and move[field_name]:
                return move[field_name]
        return 0.0

    def _get_reserved_quantity_from_move_line(self, line):
        for field_name in ("reserved_uom_qty", "product_uom_qty", "quantity_product_uom", "quantity"):
            if field_name in line._fields and line[field_name]:
                return line[field_name]
        return 0.0
