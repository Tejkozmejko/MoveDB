from odoo import _, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_view_centric_sales_drilldown(self):
        """Open the "Client Statistics" drill-down screen for this customer:
        cascading Year -> Month -> Day -> Invoice columns with a products-sold
        panel, replicating the legacy system's screen.

        Scoped to the commercial entity so purchases invoiced to any
        contact/delivery address of the same company are counted together.
        Posted customer invoices + credit notes only; the invoice analysis
        model signs refund amounts/quantities negative, so returns net off.
        """
        self.ensure_one()
        commercial = self.commercial_partner_id
        return {
            "type": "ir.actions.client",
            "tag": "centric_client_statistics",
            "name": _("Sales Statistics — %s", commercial.display_name),
            "params": {
                "partner_id": commercial.id,
                "partner_name": commercial.display_name,
                "currency_id": self.env.company.currency_id.id,
            },
        }
