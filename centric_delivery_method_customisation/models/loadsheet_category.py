from odoo import fields, models


class CentricLoadsheetCategory(models.Model):
    _name = "centric.loadsheet.category"
    _description = "Loadsheet Category"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
