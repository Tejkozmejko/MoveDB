from odoo import api, fields, models


class GymPinAssignment(models.Model):
    """Who held which member PIN, and when.

    PINs are reused, so the PIN on a contact only says who holds it today. This
    history answers who held it at any earlier date. Rows are written by the
    system only; nobody edits them by hand.
    """

    _name = "gym.pin.assignment"
    _description = "Gym PIN Assignment"
    _order = "date_assigned desc, id desc"
    _rec_name = "pin"

    pin = fields.Char(string="PIN", required=True, index=True, readonly=True)
    partner_id = fields.Many2one(
        "res.partner",
        string="Member",
        required=True,
        index=True,
        readonly=True,
        # The history outlives the membership: a contact that ever held a PIN is
        # archived, not deleted.
        ondelete="restrict",
    )
    date_assigned = fields.Datetime(
        string="Assigned On",
        required=True,
        readonly=True,
        default=fields.Datetime.now,
    )
    date_released = fields.Datetime(string="Released On", index=True, readonly=True)
    is_current = fields.Boolean(
        string="Current",
        compute="_compute_is_current",
        store=True,
    )
    source = fields.Selection(
        [
            ("allocated", "Allocated automatically"),
            ("imported", "Imported"),
            ("manual", "Set by a manager"),
        ],
        required=True,
        readonly=True,
        default="allocated",
    )
    release_reason = fields.Selection(
        [
            ("inactive", "Member inactive"),
            ("manual", "Released by a manager"),
            ("replaced", "Replaced by another PIN"),
        ],
        readonly=True,
    )
    released_by_id = fields.Many2one("res.users", string="Released By", readonly=True)
    card_no = fields.Integer(
        string="Last Card No.",
        readonly=True,
        help="Number of the most recent card printed for this PIN while this member held it.",
    )

    _pin_held_once = models.UniqueIndex(
        "(pin) WHERE date_released IS NULL",
        "This PIN is already held by another member.",
    )
    _partner_holds_one = models.UniqueIndex(
        "(partner_id) WHERE date_released IS NULL",
        "A member can only hold one PIN at a time.",
    )

    @api.depends("date_released")
    def _compute_is_current(self):
        for assignment in self:
            assignment.is_current = not assignment.date_released
