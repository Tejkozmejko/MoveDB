from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class GymPresenceReport(models.TransientModel):
    """Who was inside a gym during a period, e.g. for contact tracing."""

    _name = "gym.presence.report"
    _description = "Who Was Inside?"

    location_id = fields.Many2one(
        "gym.location", string="Location",
        default=lambda self: self.env["gym.location"].search([], limit=1),
        help="Leave empty for all locations.",
    )
    date_from = fields.Datetime(
        string="From", required=True,
        default=lambda self: fields.Datetime.now().replace(minute=0, second=0) - timedelta(hours=1),
    )
    date_to = fields.Datetime(
        string="To", required=True,
        default=lambda self: fields.Datetime.now().replace(minute=0, second=0),
    )

    @api.constrains("date_from", "date_to")
    def _check_period(self):
        for report in self:
            if report.date_to <= report.date_from:
                raise ValidationError(_("The end of the period must be after its start."))

    def _presence_domain(self):
        self.ensure_one()
        domain = [
            ("result", "!=", "denied"),
            ("check_in", "<", self.date_to),
            ("presence_end", ">", self.date_from),
        ]
        if self.location_id:
            domain.append(("location_id", "=", self.location_id.id))
        return domain

    def action_show(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("centric_gym_core.action_gym_checkins")
        action.update({
            "name": _("Inside between %(start)s and %(end)s",
                      start=fields.Datetime.to_string(self.date_from),
                      end=fields.Datetime.to_string(self.date_to)),
            "domain": self._presence_domain(),
            "context": {"create": False, "gym_presence_report": True},
            "view_mode": "list,form",
            "views": [(self.env.ref("centric_gym_core.gym_checkin_view_list_presence").id, "list"), (False, "form")],
        })
        return action
