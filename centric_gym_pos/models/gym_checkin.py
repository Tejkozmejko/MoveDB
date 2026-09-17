from odoo import _, models


class GymCheckin(models.Model):
    _inherit = "gym.checkin"

    def _gym_payload(self, status=None, result=None):
        payload = super()._gym_payload(status=status, result=result)
        payload["display"] = self._gym_display_payload(payload)
        return payload

    def _gym_display_payload(self, payload):
        """What the member-facing screen shows: nothing about health, blocks or notes."""
        self.ensure_one()
        public_status = {
            "expired": _("Expired"),
            "suspended": _("Suspended"),
            "not_started": _("Not started yet"),
            "no_membership": _("No membership"),
            "waiver_missing": _("Waiver to sign"),
            "waiver_outdated": _("Waiver to sign"),
            "already_inside": _("Already checked in"),
        }
        allowed = payload["result"] in ("allowed", "override")
        status = _("Active") if allowed else public_status.get(payload.get("reason"), _("Not active"))
        photo = self.partner_id.sudo().image_256
        return {
            "name": self.partner_id.name,
            "photo": photo.decode() if isinstance(photo, bytes) else (photo or False),
            "allowed": allowed,
            "already_inside": payload["result"] == "already_inside",
            "status": status,
        }
