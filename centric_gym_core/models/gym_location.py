from odoo import fields, models
from odoo.addons.base.models.res_partner import _tz_get


class GymLocation(models.Model):
    _name = "gym.location"
    _description = "Gym Location"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(help="Short code used on reports, e.g. BUG for Bugibba.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    # Check-in times are stored in UTC; this is the clock they are shown and
    # reported in, so "who was here at 15:00" means 15:00 at this site.
    tz = fields.Selection(
        _tz_get,
        string="Timezone",
        required=True,
        default=lambda self: self.env.user.tz or "Europe/Malta",
    )
    max_stay_minutes = fields.Integer(
        string="Automatic Check-Out After",
        default=120,
        required=True,
        help="Minutes after check-in at which a member still inside is checked out automatically.",
    )
    capacity = fields.Integer(help="How many members may be inside at once. 0 means no limit.")
    member_count = fields.Integer(compute="_compute_member_count")

    _code_company_uniq = models.Constraint(
        "UNIQUE(code, company_id)",
        "Another location of this company already uses this code.",
    )
    _max_stay_positive = models.Constraint(
        "CHECK(max_stay_minutes > 0)",
        "The automatic check-out time must be at least one minute.",
    )
    _capacity_not_negative = models.Constraint(
        "CHECK(capacity >= 0)",
        "Capacity cannot be negative.",
    )

    def _compute_member_count(self):
        counts = dict(self.env["res.partner"]._read_group(
            [("gym_home_location_id", "in", self.ids), ("gym_member_state", "=", "member")],
            ["gym_home_location_id"],
            ["__count"],
        ))
        for location in self:
            location.member_count = counts.get(location, 0)

    def action_view_members(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("centric_gym_core.action_gym_members")
        action["domain"] = [("gym_home_location_id", "=", self.id)]
        return action
