# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    centric_auto_assign_lots = fields.Boolean(
        string="Auto Assign Lots",
        config_parameter="centric_auto_lot_assignment.auto_assign_lots",
        help="Automatically assign available lots on deliveries, Pick/Pack and "
             "internal transfers for lot-tracked products, so operators are not "
             "asked to pick a lot when stock is on hand. Incoming receipts and "
             "serial-tracked products are never affected.",
    )
