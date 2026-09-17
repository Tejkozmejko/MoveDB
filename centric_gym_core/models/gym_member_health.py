from odoo import fields, models


class GymMemberHealth(models.Model):
    """A member's health information, kept apart from the contact.

    It is special-category personal data, so it lives in its own table that only
    the Gym Health Data group can open. It deliberately has no chatter: a tracked
    change would print the old and new values on the contact's chatter, where
    anyone who can see the contact would read them.
    """

    _name = "gym.member.health"
    _description = "Gym Member Health Information"
    _rec_name = "partner_id"

    partner_id = fields.Many2one(
        "res.partner",
        string="Member",
        required=True,
        index=True,
        ondelete="cascade",
    )
    show_alert = fields.Boolean(
        string="Alert Reception",
        help="Shows a health-alert flag to reception. The details below are never shown to them.",
    )
    conditions = fields.Text(string="Medical Conditions")
    medications = fields.Text()
    allergies = fields.Text()
    notes = fields.Text(string="Instructions")
    consent_date = fields.Date(
        string="Consent Given On",
        help="When the member agreed to the gym keeping this information.",
    )

    _partner_uniq = models.Constraint(
        "UNIQUE(partner_id)",
        "A member has a single health record.",
    )
