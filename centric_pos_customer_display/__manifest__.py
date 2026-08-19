{
    "name": "Centric POS",
    "summary": "Loyalty-focused POS customer display for the second screen.",
    "description": """
Replaces the standard Point of Sale customer-facing display with a clean,
loyalty-focused layout optimised for a 7-inch 1024x600 landscape screen.

It shows the selected customer, their current loyalty points in very large
text, the points earned from the current order and the projected new balance.
All values come from the actual configured Odoo loyalty programme(s) - nothing
is hardcoded. The module only patches the customer-display bundle and the POS
customer-display data adapter, so the cashier interface is untouched.

It also carries the shop-floor survey kiosk: a "Kiosk Mode" flag on a survey
turns the native survey frontend into a door tablet - no start screen, big
tappable answers, one tap records the answer and the survey resets itself for
the next customer. Surveys without the flag are untouched.

It also reworks the tax display on the POS receipt: each line prints its VAT
next to the unit price ("F: +0.27 EUR (18%)") instead of a bare letter code in
a column, and the totals block is Subtotal (excl. VAT), the VAT amount, then
Total in a larger font.
""",
    "version": "19.0.2.2.0",
    "category": "Sales/Point of Sale",
    "author": "Centric",
    "license": "LGPL-3",
    # pos_loyalty pulls in point_of_sale + loyalty; we extend both.
    # survey: the door-tablet satisfaction kiosk.
    "depends": ["point_of_sale", "pos_loyalty", "survey"],
    "data": [
        "views/survey_survey_views.xml",
        "views/survey_kiosk_templates.xml",
    ],
    "assets": {
        # Cashier POS UI: the customer-display data adapter runs here, on the
        # live order model, and pushes the computed loyalty data to the screen.
        "point_of_sale._assets_pos": [
            "centric_pos_customer_display/static/src/pos/**/*",
        ],
        # The customer-facing second screen bundle: layout + styling live here.
        "point_of_sale.customer_display_assets": [
            "centric_pos_customer_display/static/src/customer_display/**/*",
        ],
        # The survey frontend has its own bundle (not web.assets_frontend).
        "survey.survey_assets": [
            "centric_pos_customer_display/static/src/survey_kiosk/survey_kiosk.scss",
            "centric_pos_customer_display/static/src/survey_kiosk/survey_kiosk.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
