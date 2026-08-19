from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    def _centric_seed_pack_final_backorder_scope(self):
        """Configure the packed-quantity-is-final regime for these companies.

        For each company: switch 'Disable Backorders' ON and point its scope at
        every warehouse's PICK and PACK operation types - validating those short
        silently cancels the remainder (the quantity decision points). Any
        OUTGOING type is REMOVED from scope: customer deliveries ship exactly
        what was packed and are guarded by the validation hard block instead
        (they must never silently under-ship). Existing non-outgoing scope
        entries an admin added (e.g. other internal types) are preserved.

        Also normalises PICK/PACK types whose own Create Backorder policy is
        'always' back to 'ask' - core exempts 'always' types from the
        no-backorder path, which would silently disable the whole rule.
        """
        Warehouse = self.env["stock.warehouse"].sudo()
        for company in self:
            warehouses = Warehouse.search([("company_id", "=", company.id)])
            pick_pack_types = (
                warehouses.pick_type_id | warehouses.pack_type_id
            ).filtered("active")
            kept_scope = company.centric_disable_backorder_picking_type_ids.filtered(
                lambda picking_type: picking_type.code != "outgoing"
            )
            company.write({
                "centric_disable_backorder": True,
                "centric_disable_backorder_picking_type_ids": [
                    fields.Command.set((kept_scope | pick_pack_types).ids)
                ],
            })
            pick_pack_types.filtered(
                lambda picking_type: picking_type.create_backorder == "always"
            ).write({"create_backorder": "ask"})

    centric_disable_backorder = fields.Boolean(
        string="Disable Backorders",
        help="When enabled, validating a partial transfer of an in-scope "
             "operation type completes at the picked quantity without asking to "
             "create a backorder - the outstanding remainder is dropped. Scope "
             "is set by 'Backorder-Free Operations'. Note: an operation type "
             "whose own Create Backorder policy is set to 'Always' wins over "
             "this switch (core exempts it and still creates a backorder) - "
             "the packed-quantity-is-final rollout therefore normalises PICK "
             "and PACK types from 'Always' back to 'Ask'.",
    )
    centric_disable_backorder_picking_type_ids = fields.Many2many(
        comodel_name="stock.picking.type",
        relation="centric_disable_backorder_company_type_rel",
        column1="company_id",
        column2="picking_type_id",
        string="Backorder-Free Operations",
        help="Operation types the 'Disable Backorders' switch applies to. "
             "Defaults to the sales delivery chain (Pick, Pack, Delivery). Keep "
             "purchase Receipts out to keep tracking stock still owed by "
             "vendors.",
    )
