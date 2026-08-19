from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    centric_disable_backorder = fields.Boolean(
        related="company_id.centric_disable_backorder",
        readonly=False,
    )
    centric_disable_backorder_picking_type_ids = fields.Many2many(
        related="company_id.centric_disable_backorder_picking_type_ids",
        readonly=False,
    )
