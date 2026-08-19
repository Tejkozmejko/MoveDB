# -*- coding: utf-8 -*-
from odoo import _, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        if not self.env.context.get("skip_centric_expiry_check"):
            problems = self._centric_collect_expiry_problems()
            if problems:
                return self._centric_open_expiry_wizard(problems)
        return super().button_validate()

    def _centric_collect_expiry_problems(self):
        # Returns a list of (picking, move_line, reason) for incoming lines on
        # expiry-tracked products whose expiration date is missing/today/past.
        problems = []
        for picking in self:
            if picking.picking_type_code != "incoming":
                continue
            for ml in picking.move_line_ids:
                reason = picking._centric_line_expiry_problem(ml)
                if reason:
                    problems.append((picking, ml, reason))
        return problems

    def _centric_line_expiry_problem(self, ml):
        self.ensure_one()
        if not ml.use_expiration_date:
            return None
        if ml.product_uom_id.compare(ml.quantity, 0) <= 0:
            return None
        if not ml.expiration_date:
            return "missing"
        local = fields.Datetime.context_timestamp(ml, ml.expiration_date).date()
        today = fields.Date.context_today(ml)
        if local < today:
            return "past"
        if local == today:
            return "today"
        return None

    def _centric_open_expiry_wizard(self, problems):
        labels = {
            "missing": _("no expiration date set"),
            "today": _("expiration date is TODAY (the product will expire today)"),
            "past": _("expiration date is in the PAST (already expired)"),
        }
        lines = []
        for dummy_picking, ml, reason in problems:
            lot = ml.lot_name or (ml.lot_id.name if ml.lot_id else "")
            lines.append("• %s%s — %s" % (
                ml.product_id.display_name,
                (" [%s]" % lot) if lot else "",
                labels.get(reason, reason),
            ))
        message = _(
            "These products use expiration dates, but the date looks wrong:\n\n"
            "%s\n\n"
            "Please go back and set a correct expiration date, or confirm to "
            "receive anyway."
        ) % "\n".join(lines)
        wizard = self.env["centric.expiry.confirmation"].create({
            "picking_ids": [(6, 0, self.ids)],
            "message": message,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Check Expiration Dates"),
            "res_model": "centric.expiry.confirmation",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }
