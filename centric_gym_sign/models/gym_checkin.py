from odoo import fields, models


class GymCheckin(models.Model):
    _inherit = "gym.checkin"

    deny_reason = fields.Selection(
        selection_add=[("waiver_outdated", "New waiver version not signed")],
        ondelete={"waiver_outdated": "set null"},
    )
