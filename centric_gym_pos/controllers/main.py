import re

from odoo import _, http
from odoo.http import request
from odoo.tools import consteq

from odoo.addons.centric_gym_core.models.res_partner import PIN_PATTERN


class GymCustomerDisplay(http.Controller):

    @http.route("/centric_gym_pos/display/checkin", type="jsonrpc", auth="public", methods=["POST"])
    def display_checkin(self, config_id, access_token, pin):
        """A member types their PIN on a Point of Sale customer screen.

        The screen is a public page, so the Point of Sale's access token stands
        in for a login, and only what the member may see is returned.
        """
        config = request.env["pos.config"].sudo().browse(int(config_id)).exists()
        if not config or not consteq(str(access_token or ""), config.access_token or ""):
            return {"error": _("This screen is not connected to a Point of Sale.")}
        Attempt = request.env["gym.tablet.attempt"].sudo()
        if Attempt._gym_locked(config):
            return {"error": _("Too many wrong PINs. Please ask reception.")}
        pin = re.sub(r"\s", "", str(pin or ""))
        if not PIN_PATTERN.fullmatch(pin):
            Attempt._gym_record(config, False)
            return {"error": _("Type your 4-digit PIN.")}
        location = config._gym_location()
        if not location:
            return {"error": _("This Point of Sale has no gym location.")}
        result = request.env["gym.checkin"].sudo().gym_check_in(
            location.id, code=pin, source="tablet", identified_by="pin",
        )
        Attempt._gym_record(config, bool(result.get("member")))
        if not result.get("member"):
            return {"error": _("Unknown PIN. Please try again or ask reception.")}
        return {"display": result["display"]}
