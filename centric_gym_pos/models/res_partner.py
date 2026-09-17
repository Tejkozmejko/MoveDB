from odoo import api, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + ["gym_member_state", "gym_pin"]

    @api.model
    def _gym_membership_orders(self, partners):
        """A membership signed at the POS but not paid yet does not count."""
        by_partner = super()._gym_membership_orders(partners)
        for partner_id, orders in by_partner.items():
            by_partner[partner_id] = orders.filtered(lambda o: not o.gym_pos_pending)
        return by_partner
