from datetime import timedelta

from odoo import api, fields, models

WINDOW_MINUTES = 5
MAX_FAILURES = 8


class GymTabletAttempt(models.TransientModel):
    """PIN attempts on a customer screen, to slow down guessing.

    Transient: Odoo deletes old rows by itself.
    """

    _name = "gym.tablet.attempt"
    _description = "Gym Tablet PIN Attempt"

    config_id = fields.Many2one("pos.config", required=True, index=True, ondelete="cascade")
    success = fields.Boolean()

    @api.model
    def _gym_locked(self, config):
        since = fields.Datetime.now() - timedelta(minutes=WINDOW_MINUTES)
        failures = self.sudo().search_count([
            ("config_id", "=", config.id), ("success", "=", False), ("create_date", ">=", since),
        ])
        return failures >= MAX_FAILURES

    @api.model
    def _gym_record(self, config, success):
        self.sudo().create({"config_id": config.id, "success": success})
