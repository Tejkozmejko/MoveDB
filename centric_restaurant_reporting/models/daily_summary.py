# -*- coding: utf-8 -*-
import logging
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Comma-separated override for who receives the summary. When unset the mail
# goes to every user in the POS Manager group that has an email address.
RECIPIENTS_PARAM = "centric_restaurant_reporting.summary_recipients"

TOP_N = 5


class CentricRestaurantDailySummary(models.AbstractModel):
    """The nightly trading summary emailed to the restaurant managers.

    Abstract rather than transient: there is nothing worth storing, the cron
    just calls ``_cron_send_daily_summary`` and the figures are read straight
    off ``centric.restaurant.menu.report``.
    """

    _name = "centric.restaurant.daily.summary"
    _description = "Restaurant Daily Trading Summary"

    # ------------------------------------------------------------------
    # Timezone helpers
    # ------------------------------------------------------------------
    def _timezone(self):
        """The restaurant's trading day, not the server's.

        A service that runs past midnight UTC would otherwise be split across
        two reports.
        """
        return self.env.company.partner_id.tz or self.env.user.tz or "UTC"

    def _day_bounds(self, day):
        tz = pytz.timezone(self._timezone())
        start = tz.localize(datetime.combine(day, time.min))
        end = tz.localize(datetime.combine(day + timedelta(days=1), time.min))
        to_utc = lambda dt: dt.astimezone(pytz.utc).replace(tzinfo=None)
        return to_utc(start), to_utc(end)

    def _yesterday(self):
        tz = pytz.timezone(self._timezone())
        return (fields.Datetime.now().replace(tzinfo=pytz.utc).astimezone(tz).date()
                - timedelta(days=1))

    # ------------------------------------------------------------------
    # Figures
    # ------------------------------------------------------------------
    @api.model
    def _summary_values(self, day=None, company=None):
        """Return everything the email template renders, for one trading day."""
        company = company or self.env.company
        day = day or self._yesterday()
        start, end = self._day_bounds(day)

        base_domain = [
            ("date", ">=", start),
            ("date", "<", end),
            ("company_id", "=", company.id),
        ]
        Report = self.env["centric.restaurant.menu.report"]

        totals = Report._read_group(
            base_domain, [], ["qty:sum", "revenue:sum", "cost:sum", "margin:sum"]
        )
        qty, revenue, cost, margin = totals[0] if totals else (0.0, 0.0, 0.0, 0.0)

        orders = self.env["pos.order"].search(
            [
                ("date_order", ">=", start),
                ("date_order", "<", end),
                ("company_id", "=", company.id),
                ("state", "in", ["paid", "done"]),
            ]
        )
        covers = sum(orders.mapped("customer_count"))

        by_product = Report._read_group(
            base_domain,
            ["product_id"],
            ["qty:sum", "revenue:sum", "margin:sum"],
        )
        # Sorted in Python: the two lists want different orderings of the same
        # single read, and there are only ever a menu's worth of rows.
        ranked_by_revenue = sorted(by_product, key=lambda r: r[2], reverse=True)
        ranked_by_margin = sorted(by_product, key=lambda r: r[3])

        line = lambda row: {
            "product": row[0].display_name,
            "qty": row[1],
            "revenue": row[2],
            "margin": row[3],
        }

        scrap = self.env["stock.scrap"].search_count(
            [
                ("date_done", ">=", start),
                ("date_done", "<", end),
                ("company_id", "=", company.id),
                ("state", "=", "done"),
            ]
        )

        return {
            "company": company,
            "date": day,
            "currency": company.currency_id,
            "orders": len(orders),
            "covers": covers,
            "qty": qty,
            "revenue": revenue,
            "cost": cost,
            "margin": margin,
            "margin_percent": (margin / revenue * 100) if revenue else 0.0,
            "average_spend": (revenue / covers) if covers else 0.0,
            "top_sellers": [line(r) for r in ranked_by_revenue[:TOP_N]],
            "worst_margins": [line(r) for r in ranked_by_margin[:TOP_N]],
            "scrap_count": scrap,
        }

    # ------------------------------------------------------------------
    # Recipients and sending
    # ------------------------------------------------------------------
    @api.model
    def _recipients(self):
        override = self.env["ir.config_parameter"].sudo().get_param(RECIPIENTS_PARAM)
        if override:
            return [e.strip() for e in override.split(",") if e.strip()]
        group = self.env.ref("point_of_sale.group_pos_manager", raise_if_not_found=False)
        if not group:
            return []
        return [u.email for u in group.sudo().users if u.email]

    @api.model
    def _cron_send_daily_summary(self):
        recipients = self._recipients()
        if not recipients:
            _logger.warning(
                "centric_restaurant_reporting: no recipients for the daily summary "
                "(set the %r system parameter, or give the POS managers an email "
                "address); nothing sent",
                RECIPIENTS_PARAM,
            )
            return

        values = self._summary_values()
        body = self.env["ir.qweb"]._render(
            "centric_restaurant_reporting.daily_summary_body", values
        )
        subject = "%s - trading summary for %s" % (
            values["company"].name,
            fields.Date.to_string(values["date"]),
        )
        self.env["mail.mail"].sudo().create(
            {
                "subject": subject,
                "body_html": body,
                "email_to": ",".join(recipients),
                "auto_delete": True,
            }
        ).send()
        _logger.info(
            "centric_restaurant_reporting: daily summary for %s sent to %s",
            values["date"],
            ", ".join(recipients),
        )
