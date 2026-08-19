from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    centric_loadsheet_category_id = fields.Many2one(
        "centric.loadsheet.category",
        string="Loadsheet Category",
        help="Custom category used to split pick and pack loadsheets.",
    )

    @api.onchange("is_storable")
    def _onchange_is_storable_default_tracking_lot(self):
        for template in self:
            if template.is_storable and template.tracking == "none":
                template.tracking = "lot"


class ProductProduct(models.Model):
    _inherit = "product.product"

    centric_loadsheet_category_id = fields.Many2one(
        "centric.loadsheet.category",
        related="product_tmpl_id.centric_loadsheet_category_id",
        readonly=False,
        store=True,
    )
