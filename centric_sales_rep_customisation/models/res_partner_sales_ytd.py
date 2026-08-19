from dateutil.relativedelta import relativedelta

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    centric_sales_ytd_current = fields.Monetary(
        string="Sales YTD",
        compute="_compute_centric_sales_ytd",
        currency_field="centric_sales_ytd_currency_id",
        help="Net invoiced sales (untaxed) from 1 January to today, for this "
             "customer's whole company.",
    )
    centric_sales_ytd_last_year = fields.Monetary(
        string="Sales YTD Last Year",
        compute="_compute_centric_sales_ytd",
        currency_field="centric_sales_ytd_currency_id",
        help="Net invoiced sales (untaxed) from 1 January last year to the same "
             "date last year, for this customer's whole company.",
    )
    centric_sales_ytd_variance = fields.Monetary(
        string="YTD Variance",
        compute="_compute_centric_sales_ytd",
        currency_field="centric_sales_ytd_currency_id",
        help="This year to date minus last year to the same date.",
    )
    centric_sales_ytd_variance_pct = fields.Float(
        string="YTD Variance %",
        compute="_compute_centric_sales_ytd",
        help="Variance as a share of last year to date. Zero when there were no "
             "sales in that period last year.",
    )
    centric_sales_ytd_currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_centric_sales_ytd_currency",
    )

    def _compute_centric_sales_ytd_currency(self):
        currency = self.env.company.currency_id
        for partner in self:
            partner.centric_sales_ytd_currency_id = currency

    def _compute_centric_sales_ytd(self):
        """Compute both periods for the whole recordset in two queries.

        Batched on purpose: these fields are shown on the contacts list, so a
        per-record query would mean two round trips per row.
        """
        today = fields.Date.context_today(self)
        start_current = today.replace(month=1, day=1)
        start_last = start_current - relativedelta(years=1)
        end_last = today - relativedelta(years=1)
        company_ids = self.env.companies.ids
        commercial_ids = self.commercial_partner_id.ids

        totals = {"current": {}, "last": {}}
        if commercial_ids:
            for key, date_from, date_to in (
                ("current", start_current, today),
                ("last", start_last, end_last),
            ):
                groups = self.env["account.move"]._read_group(
                    [
                        ("move_type", "in", ("out_invoice", "out_refund")),
                        ("state", "=", "posted"),
                        ("commercial_partner_id", "in", commercial_ids),
                        ("company_id", "in", company_ids),
                        ("invoice_date", ">=", date_from),
                        ("invoice_date", "<=", date_to),
                    ],
                    groupby=["commercial_partner_id"],
                    aggregates=["amount_untaxed_signed:sum"],
                )
                # amount_untaxed_signed is positive for invoices and negative
                # for credit notes, so the sum is net untaxed revenue.
                totals[key] = {
                    partner.id: amount or 0.0 for partner, amount in groups
                }

        for partner in self:
            commercial_id = partner.commercial_partner_id.id
            current = totals["current"].get(commercial_id, 0.0)
            last = totals["last"].get(commercial_id, 0.0)
            partner.centric_sales_ytd_current = current
            partner.centric_sales_ytd_last_year = last
            partner.centric_sales_ytd_variance = current - last
            partner.centric_sales_ytd_variance_pct = (
                (current - last) / last if last else 0.0
            )

    def _centric_sum_invoiced(self, account_move, base_domain, date_from, date_to):
        domain = base_domain + [
            ("invoice_date", ">=", date_from),
            ("invoice_date", "<=", date_to),
        ]
        # amount_untaxed_signed is positive for customer invoices and negative
        # for credit notes, so the sum is the net untaxed revenue.
        groups = account_move._read_group(domain, aggregates=["amount_untaxed_signed:sum"])
        return groups[0][0] or 0.0
