import json
from urllib.parse import quote

from odoo import _, api, fields, models
from odoo.fields import Command
from odoo.tools import float_is_zero, formatLang, format_date


class AccountMove(models.Model):
    _inherit = "account.move"

    # Number of copies produced when an invoice is printed. The browser's native
    # print dialog cannot be pre-set to N by web code, so "2 copies" is achieved
    # by rendering each invoice this many times in the print-only auto-print page
    # (the standard report layout page-breaks between them). Single source of
    # truth - change here to adjust the default copy count.
    _CENTRIC_INVOICE_PRINT_COPIES = 2

    def _centric_invoice_auto_print_action(self, report):
        """Open ``report`` for these invoices as an HTML page that auto-prints,
        emitting each invoice ``_CENTRIC_INVOICE_PRINT_COPIES`` times so a single
        print run yields that many copies.

        This is the one place the print copy count is applied, shared by every
        print entry point (single-invoice Print and Sales Order -> Create
        Invoice -> Print, the latter covering batches of invoices). It is scoped
        to this explicit auto-print page via the ``centric_invoice_auto_print``
        context, so emailed, portal and standard PDF renders are never doubled.
        """
        # The web client sends its full user context - which carries
        # allowed_company_ids - whenever it opens a /report/html URL itself, so
        # this hand-built URL has to do the same. A bare GET carries no
        # allowed_company_ids, so the render does not inherit the companies the
        # user has active in the web client and falls back to the user's own
        # default; an invoice booked in another company is then denied by the core
        # "Account Entry" multi-company rule and the print tab shows 403:
        # Forbidden even though the right company is selected in the switcher.
        # Companies the user is not allowed are dropped, so this never widens
        # access.
        companies = self.env.companies | (
            self.mapped("company_id") & self.env.user.company_ids
        )
        context = quote(json.dumps({
            "centric_invoice_auto_print": True,
            "allowed_company_ids": companies.ids,
        }))
        docids = ",".join(
            str(invoice.id)
            for invoice in self
            for _copy in range(self._CENTRIC_INVOICE_PRINT_COPIES)
        )
        return {
            "type": "ir.actions.act_url",
            "target": "new",
            "url": f"/report/html/{report.report_name}/{docids}?context={context}",
        }

    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Shipping Method",
        compute="_compute_carrier_id",
        store=True,
        readonly=True,
        index=True,
    )

    @api.depends("line_ids.sale_line_ids.order_id.carrier_id")
    def _compute_carrier_id(self):
        for move in self:
            carriers = move.line_ids.sale_line_ids.order_id.carrier_id
            move.carrier_id = carriers[:1]

    centric_driver_id = fields.Many2one(
        "hr.employee",
        string="Driver",
        compute="_compute_centric_driver_id",
        store=True,
        readonly=False,
        index=True,
    )

    @api.depends("line_ids.sale_line_ids.order_id.centric_driver_id")
    def _compute_centric_driver_id(self):
        for move in self:
            drivers = move.line_ids.sale_line_ids.order_id.centric_driver_id
            move.centric_driver_id = drivers[:1]

    @api.depends("line_ids.sale_line_ids.order_id.commitment_date")
    def _compute_delivery_date(self):
        # EXTENDS 'account' / 'sale_stock'. Core fills the invoice Delivery Date
        # from the actual delivery (sale order effective_date). For us the date
        # that matters is the planned Delivery Date the office sets on the order
        # (commitment_date), so prefer that and only fall back to core's value.
        super()._compute_delivery_date()
        for move in self:
            commitment_dates = [
                commitment
                for commitment in move.line_ids.sale_line_ids.order_id.mapped("commitment_date")
                if commitment
            ]
            if commitment_dates:
                move.delivery_date = fields.Datetime.context_timestamp(move, max(commitment_dates))

    def _get_invoiced_lot_values(self):
        return []

    def _centric_split_invoice_lines_by_delivered_lot(self):
        for move in self.filtered(lambda invoice: invoice.state == "draft"):
            invoice_lines = move.invoice_line_ids.filtered(
                lambda line: (
                    line.display_type == "product"
                    and line.sale_line_ids
                    and not line.centric_lot_id
                    and line.product_uom_id
                    and not line.product_uom_id.is_zero(line.quantity)
                )
            )
            for line in invoice_lines:
                line._centric_split_by_delivered_lot()


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    centric_lot_id = fields.Many2one(
        "stock.lot",
        string="Lot/Serial Number",
        readonly=True,
    )
    centric_lot_expiration_date = fields.Date(
        string="Expiry Date",
        readonly=True,
    )

    def _centric_split_by_delivered_lot(self):
        self.ensure_one()
        sale_line = self.sale_line_ids[:1]
        if not sale_line:
            return

        precision = self.env["decimal.precision"].precision_get("Product Unit")
        lot_quantities = sale_line._centric_lot_quantities_to_invoice(self.quantity)
        if not lot_quantities:
            return

        remaining_quantity = self.quantity
        first_lot_values = False
        extra_line_commands = []
        for lot, lot_quantity in lot_quantities:
            if float_is_zero(remaining_quantity, precision_digits=precision):
                break

            invoice_quantity = min(lot_quantity, remaining_quantity)
            if float_is_zero(invoice_quantity, precision_digits=precision):
                continue

            values = self._centric_lot_split_values(sale_line, lot, invoice_quantity)
            if not first_lot_values:
                first_lot_values = values
            else:
                extra_line_commands.append(Command.create(values))
            remaining_quantity -= invoice_quantity

        if not first_lot_values:
            return

        if not float_is_zero(remaining_quantity, precision_digits=precision):
            extra_line_commands.append(Command.create(self._centric_lot_split_values(
                sale_line,
                self.env["stock.lot"],
                remaining_quantity,
            )))

        self.with_context(check_move_validity=False).write(first_lot_values)
        if extra_line_commands:
            self.move_id.with_context(check_move_validity=False).write({
                "invoice_line_ids": extra_line_commands,
            })

    def _centric_lot_split_values(self, sale_line, lot, quantity):
        self.ensure_one()
        expiration_date = sale_line._centric_lot_expiration_date(lot) if lot else False
        values = {
            "display_type": self.display_type,
            "sequence": self.sequence,
            "name": (
                sale_line._centric_lot_invoice_line_name(self.name, lot, expiration_date)
                if lot
                else self.name
            ),
            "product_id": self.product_id.id,
            "product_uom_id": self.product_uom_id.id,
            "quantity": quantity,
            "discount": self.discount,
            "price_unit": self.price_unit,
            "tax_ids": [Command.set(self.tax_ids.ids)],
            "sale_line_ids": [Command.set(self.sale_line_ids.ids)],
            "account_id": self.account_id.id,
            "analytic_distribution": self.analytic_distribution,
            "extra_tax_data": self.extra_tax_data,
            "is_downpayment": self.is_downpayment,
            "centric_lot_id": lot.id if lot else False,
            "centric_lot_expiration_date": expiration_date,
        }
        for field_name in ("collapse_prices", "collapse_composition"):
            if field_name in self._fields:
                values[field_name] = self[field_name]
        return values

    def _centric_invoice_lot_texts(self):
        self.ensure_one()
        if self.display_type != "product" or not self.product_id:
            return []

        # Prefer the invoice line's embedded lot text so invoice previews and
        # emails do not require direct stock.lot access for non-inventory users.
        embedded_lot_texts = self._centric_invoice_embedded_lot_texts()
        if embedded_lot_texts:
            return embedded_lot_texts

        lot = self.sudo().centric_lot_id
        if lot:
            return [self._centric_lot_report_text(
                lot,
                self.centric_lot_expiration_date,
                self.quantity,
            )]

        lot_texts = []
        remaining_quantity = self.quantity
        precision = self.env["decimal.precision"].precision_get("Product Unit")
        for sale_line in self.sale_line_ids.sudo():
            if float_is_zero(remaining_quantity, precision_digits=precision):
                break

            for lot, lot_quantity in sale_line._centric_lot_quantities_to_invoice(remaining_quantity):
                quantity = min(lot_quantity, remaining_quantity)
                if float_is_zero(quantity, precision_digits=precision):
                    continue

                lot_texts.append(self._centric_lot_report_text(
                    lot,
                    sale_line._centric_lot_expiration_date(lot),
                    quantity,
                ))
                remaining_quantity -= quantity

        return lot_texts or self._centric_invoice_embedded_lot_texts()

    def _centric_invoice_description_name(self):
        self.ensure_one()
        description_lines = []
        for name_line in (self.name or "").splitlines():
            if self._centric_is_invoice_lot_description_line(name_line):
                continue
            description_lines.append(name_line)
        return "\n".join(description_lines).strip()

    def _centric_invoice_embedded_lot_texts(self):
        self.ensure_one()
        lot_texts = []
        for name_line in (self.name or "").splitlines():
            clean_line = name_line.strip()
            if self._centric_is_invoice_lot_description_line(clean_line):
                lot_texts.append(clean_line)
        return lot_texts

    def _centric_is_invoice_lot_description_line(self, line):
        clean_line = (line or "").strip()
        return clean_line.startswith("Lot: ") or clean_line.startswith(_("Lot: "))

    def _centric_lot_report_text(self, lot, expiration_date, quantity=False):
        self.ensure_one()
        details = [_("Lot: %s") % lot.name]
        if expiration_date:
            details.append(_("Expiry: %s") % format_date(self.env, expiration_date))
        if quantity and len(self.sale_line_ids) <= 1 and self.quantity != quantity:
            quantity_text = formatLang(self.env, quantity, dp="Product Unit")
            if self.product_uom_id:
                quantity_text = "%s %s" % (quantity_text, self.product_uom_id.name)
            details.append(_("Qty: %s") % quantity_text)
        return " | ".join(details)
