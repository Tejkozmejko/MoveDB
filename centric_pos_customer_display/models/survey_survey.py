from odoo import fields, models


class SurveySurvey(models.Model):
    _inherit = 'survey.survey'

    centric_kiosk_mode = fields.Boolean(
        string="Kiosk Mode",
        help="Display this survey full screen on a tablet: the start screen is skipped, "
             "answers are big tappable buttons, a single tap records the answer and the "
             "survey resets itself for the next customer.")
    centric_kiosk_reset_delay = fields.Integer(
        string="Reset After", default=3,
        help="Seconds the thank you screen stays on before the survey restarts.")
