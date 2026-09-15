import base64
import io
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize


class StockEmailImportConfig(models.Model):
    """One mailbox per company: the alias, who may send to it, how to apply."""

    _name = "stock.email.import.config"
    _description = "Stock Email Import Configuration"
    _inherit = ["mail.alias.mixin"]
    _order = "company_id, id"

    name = fields.Char(required=True, default=lambda self: _("Stocktake"))
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Apply As",
        required=True,
        default=lambda self: self.env.user,
        help="Inventory adjustments from emailed sheets are validated as this "
             "user. Must be an Inventory Administrator of the company.",
    )
    allowed_emails = fields.Text(
        string="Allowed Senders",
        help="One email address per line (or comma-separated). Emails from "
             "any other address are recorded as Rejected and never touch "
             "stock. Leave empty to reject every email.",
    )
    location_id = fields.Many2one(
        "stock.location",
        string="Default Location",
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_id)]",
        help="Used for rows without a Location column value. Defaults to the "
             "stock location of the company's first warehouse.",
    )
    price_update = fields.Selection(
        [
            ("none", "Ignore"),
            ("cost", "Update product cost"),
            ("sales", "Update sales price"),
        ],
        string="Price Column",
        default="none",
        required=True,
        help="What a plain 'Price' column does. Columns headed 'Sales Price' "
             "and 'Cost Price' always update their own field, whatever this says. "
             "A cost change also changes the value of stock already on hand.",
    )
    create_missing_products = fields.Boolean(
        help="Create a storable product for rows whose product is not found, "
             "using the Name, Category and Price columns. When off, an "
             "unknown product fails the whole sheet.",
    )
    create_missing_lots = fields.Boolean(
        default=True,
        help="Create lot/serial numbers that do not exist yet for the product.",
    )
    notify_sender = fields.Boolean(
        default=True,
        help="Email the sender a summary once the sheet is applied or failed.",
    )
    template_file = fields.Binary(attachment=True, readonly=True)
    import_count = fields.Integer(compute="_compute_import_count")
    done_count = fields.Integer(compute="_compute_import_count")
    attention_count = fields.Integer(compute="_compute_import_count")

    _company_uniq = models.Constraint(
        "UNIQUE(company_id)",
        "Only one stock email import configuration per company.",
    )

    def _compute_import_count(self):
        data = self.env["stock.email.import"]._read_group(
            [("config_id", "in", self.ids)], ["config_id", "state"], ["__count"],
        )
        counts = {}
        for config, state, count in data:
            counts.setdefault(config.id, {})[state] = count
        for config in self:
            by_state = counts.get(config.id, {})
            config.import_count = sum(by_state.values())
            config.done_count = by_state.get("done", 0)
            config.attention_count = by_state.get("failed", 0) + by_state.get("rejected", 0)

    @api.constrains("user_id", "company_id")
    def _check_user_rights(self):
        for config in self:
            user = config.user_id
            if not user.has_group("stock.group_stock_manager"):
                raise ValidationError(_(
                    "%(user)s must be an Inventory Administrator to apply "
                    "emailed stocktakes.", user=user.name,
                ))
            if config.company_id not in user.company_ids:
                raise ValidationError(_(
                    "%(user)s has no access to %(company)s.",
                    user=user.name, company=config.company_id.name,
                ))

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        values["alias_model_id"] = self.env["ir.model"]._get_id("stock.email.import")
        values["alias_contact"] = "everyone"
        if self.id:
            values["alias_defaults"] = repr({
                "config_id": self.id,
                "company_id": self.company_id.id,
            })
        return values

    def _allowed_email_set(self):
        self.ensure_one()
        emails = set()
        for chunk in re.split(r"[\s,;]+", self.allowed_emails or ""):
            normalized = email_normalize(chunk)
            if normalized:
                emails.add(normalized)
        return emails

    def _is_sender_allowed(self, email_from):
        normalized = email_normalize(email_from or "")
        return bool(normalized) and normalized in self._allowed_email_set()

    def _default_location(self):
        self.ensure_one()
        if self.location_id:
            return self.location_id
        warehouse = self.env["stock.warehouse"].sudo().search(
            [("company_id", "=", self.company_id.id)], limit=1,
        )
        return warehouse.lot_stock_id

    def action_view_imports(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "centric_stock_email_import.action_stock_email_import")
        action["domain"] = [("config_id", "=", self.id)]
        context = {"default_config_id": self.id}
        filter_name = self.env.context.get("import_filter")
        if filter_name:
            context["search_default_%s" % filter_name] = 1
        action["context"] = context
        return action

    def action_download_template(self):
        """A starter sheet whose headers are the first name of each mapping."""
        self.ensure_one()
        from openpyxl import Workbook
        from openpyxl.styles import Font

        headers = []
        seen = set()
        for column in self.env["stock.email.import.column"].search([]):
            # The template uses the explicit Sales Price / Cost Price columns.
            if column.target in seen or column.target == "price":
                continue
            seen.add(column.target)
            first = (column.header_names or "").split(",")[0].strip()
            if first:
                headers.append(first.title())

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Stocktake"
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            sheet.column_dimensions[cell.column_letter].width = 22
        buffer = io.BytesIO()
        workbook.save(buffer)
        self.template_file = base64.b64encode(buffer.getvalue())
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/stock.email.import.config/%s/template_file/"
                   "stocktake_template.xlsx?download=true" % self.id,
            "target": "self",
        }
