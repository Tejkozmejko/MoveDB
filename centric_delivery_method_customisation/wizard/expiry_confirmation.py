# -*- coding: utf-8 -*-
from odoo import fields, models


class CentricExpiryConfirmation(models.TransientModel):
    _name = "centric.expiry.confirmation"
    _description = "Confirm receipt despite missing/expired expiration dates"

    picking_ids = fields.Many2many("stock.picking")
    message = fields.Text(readonly=True)

    def action_confirm(self):
        self.ensure_one()
        # skip_centric_expiry_check: don't re-raise our own wizard.
        # skip_expired: the lots we just warned about would also trigger Odoo's
        # native expiry confirmation -- suppress it to avoid a double pop-up.
        return self.picking_ids.with_context(
            skip_centric_expiry_check=True,
            skip_expired=True,
        ).button_validate()
