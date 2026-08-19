import base64

from markupsafe import Markup, escape

from odoo import _, models
from odoo.exceptions import AccessError, UserError


CUSTOMER_STATEMENT_XMLIDS = (
    "account_reports.account_report_customer_statement",
    "account_reports.customer_statement_report",
    "account_reports.partner_statement_report",
    "account_reports.aged_receivable_report",
    "account_reports.aged_payable_report",
)

CUSTOMER_STATEMENT_NAMES = (
    "Customer Statement",
    "Aged Receivable",
    "Aged Payable",
)


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_centric_send_customer_statement(self):
        self.ensure_one()
        partner = self.commercial_partner_id or self
        self._centric_check_can_send_customer_statement(partner)

        report = self._centric_customer_statement_report()
        options = self._centric_customer_statement_options(report, partner)
        attachment = self._centric_customer_statement_pdf_attachment(report, partner, options)

        return self._centric_open_customer_statement_composer(partner, attachment)

    def _centric_check_can_send_customer_statement(self, partner):
        if (
            self.env.user.has_group("centric_sales_rep_customisation.group_centric_sales_representative")
            and partner.user_id != self.env.user
        ):
            raise AccessError(_("You can only send statements for customers assigned to you."))

    def _centric_customer_statement_report(self):
        for xmlid in CUSTOMER_STATEMENT_XMLIDS:
            report = self.env.ref(xmlid, raise_if_not_found=False)
            if report and report._name == "account.report":
                return report

        Report = self.env["account.report"]
        for name in CUSTOMER_STATEMENT_NAMES:
            report = Report.search([("name", "=ilike", name)], limit=1)
            if report:
                return report

            report = Report.search([("name", "ilike", name)], limit=1)
            if report:
                return report

        raise UserError(_("Could not find the Customer Statement accounting report."))

    def _centric_customer_statement_options(self, report, partner):
        previous_options = {
            "report_id": report.id,
            "selected_variant_id": report.id,
            "partner_ids": [partner.id],
            "selected_partner_ids": [partner.id],
            "partner_categories": [],
            "unfold_all": True,
        }

        if hasattr(report, "get_options"):
            options = report.get_options(previous_options)
        elif hasattr(report, "_get_options"):
            options = report._get_options(previous_options)
        else:
            options = dict(previous_options)

        options.update(previous_options)
        return options

    def _centric_customer_statement_pdf_attachment(self, report, partner, options):
        if not hasattr(report, "export_to_pdf"):
            raise UserError(_("The Customer Statement accounting report cannot be exported to PDF."))

        export_result = report.export_to_pdf(options)
        if not isinstance(export_result, dict) or not export_result.get("file_content"):
            raise UserError(_("The Customer Statement accounting report did not generate a PDF."))

        filename = export_result.get("file_name") or _("Customer Statement - %(partner)s.pdf") % {
            "partner": partner.display_name,
        }
        if not filename.lower().endswith(".pdf"):
            filename = f"{filename}.pdf"

        return self.env["ir.attachment"].create(
            {
                "name": filename,
                "type": "binary",
                "datas": base64.b64encode(
                    self._centric_customer_statement_file_content(export_result["file_content"])
                ),
                "res_model": "mail.compose.message",
                "res_id": 0,
                "mimetype": "application/pdf",
            }
        )

    def _centric_customer_statement_file_content(self, file_content):
        if isinstance(file_content, bytes):
            return file_content

        if isinstance(file_content, str):
            raw_content = file_content.encode()
            if raw_content.lstrip().startswith(b"%PDF"):
                return raw_content

            try:
                return base64.b64decode("".join(file_content.split()), validate=True)
            except Exception:
                return raw_content

        raise UserError(_("The Customer Statement PDF content could not be read."))

    def _centric_open_customer_statement_composer(self, partner, attachment):
        compose_form = self.env.ref("mail.email_compose_message_wizard_form", raise_if_not_found=False)
        action = {
            "name": _("Send Customer Statement"),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.message",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_model": "res.partner",
                "default_res_model": "res.partner",
                "default_res_ids": [partner.id],
                "default_composition_mode": "comment",
                "default_partner_ids": partner.ids,
                "default_subject": self._centric_customer_statement_mail_subject(partner),
                "default_body": self._centric_customer_statement_mail_body(partner),
                "default_attachment_ids": [(6, 0, attachment.ids)],
                "force_email": True,
                "mail_post_autofollow": False,
            },
        }
        if compose_form:
            action["views"] = [(compose_form.id, "form")]
        return action

    def _centric_customer_statement_mail_subject(self, partner):
        return _("%(company)s Customer Statement - %(partner)s") % {
            "company": self.env.company.display_name,
            "partner": partner.display_name,
        }

    def _centric_customer_statement_mail_body(self, partner):
        body = Markup("<p>%s</p><p>%s</p><p>%s</p>") % (
            escape(_("Dear %(partner)s,") % {"partner": partner.display_name}),
            escape(
                _("Please find attached your customer statement from %(company)s.")
                % {"company": self.env.company.display_name}
            ),
            escape(_("Do not hesitate to contact us if you have any questions.")),
        )
        if self.env.user.signature:
            body += Markup("<br/>") + Markup(self.env.user.signature)
        return body
