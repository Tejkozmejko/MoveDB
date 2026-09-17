from odoo import api, fields, models

from odoo.addons.centric_gym_core.models.res_partner import GROUP_RECEPTION


class PosConfig(models.Model):
    _inherit = "pos.config"

    gym_location_id = fields.Many2one(
        "gym.location", string="Gym Location",
        help="Members checking in with their PIN on this Point of Sale's customer screen are checked in here.",
    )

    def _gym_location(self):
        self.ensure_one()
        return self.gym_location_id or self.env["gym.location"].sudo().search(
            [("company_id", "=", self.company_id.id)], limit=1
        )

    @api.model
    def gym_notify_display(self, location_id, display, device_uuid):
        """Show a reception check-in on a customer screen running on another device.

        A screen in the same browser gets it through the BroadcastChannel already.
        """
        self.env["gym.checkin"]._gym_require(GROUP_RECEPTION)
        if not device_uuid:
            return False
        configs = self.sudo().search([("gym_location_id", "=", location_id)])
        for config in configs:
            config._notify(f"UPDATE_CUSTOMER_DISPLAY-{device_uuid}", {"gym_welcome": display})
        return bool(configs)
