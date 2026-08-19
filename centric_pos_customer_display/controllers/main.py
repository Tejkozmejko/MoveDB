import re

from odoo import http
from odoo.http import request
from odoo.tools import consteq

# Deliberately loose - just enough to reject obvious typos on a kiosk keyboard.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FarmMeatsPosCustomerDisplay(http.Controller):
    """Self-service account creation from the POS customer-facing display.

    The customer display page is served with auth="public" and is trusted only
    through the pos.config access_token (same token the display itself is
    validated with). We therefore re-check that token here, create the partner
    with sudo (limited to a few whitelisted fields) and then notify the cashier
    POS - over the same bus channel the config already uses - so it loads and
    selects the new customer on the live order.
    """

    @http.route(
        "/centric_pos_customer_display/create_partner",
        auth="public",
        type="jsonrpc",
    )
    def create_partner(
        self,
        config_id=None,
        access_token=None,
        device_uuid=None,
        name=None,
        phone=None,
        email=None,
        **kw,
    ):
        config = request.env["pos.config"].sudo().browse(int(config_id or 0))
        if (
            not config.exists()
            or not access_token
            or not config.access_token
            or not consteq(access_token, config.access_token)
        ):
            return {"error": "invalid_token"}

        name = (name or "").strip()
        if not name:
            return {"error": "name_required"}

        phone = (phone or "").strip()
        email = (email or "").strip()
        if email and not EMAIL_RE.match(email):
            return {"error": "invalid_email"}

        vals = {"name": name}
        if phone:
            vals["phone"] = phone
        if email:
            vals["email"] = email

        partner = (
            request.env["res.partner"]
            .sudo()
            .with_company(config.company_id)
            .create(vals)
        )

        # Tell the cashier POS (same access_token + device_uuid channel the
        # customer display already talks over) to select this new partner.
        if device_uuid:
            config._notify(f"AZZ_NEW_PARTNER-{device_uuid}", {"id": partner.id})

        return {"id": partner.id, "name": partner.name}
