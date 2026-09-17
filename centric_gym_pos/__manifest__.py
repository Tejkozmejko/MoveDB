{
    "name": "Centric Gym POS",
    "summary": "Sell and renew gym memberships in the Point of Sale, signed on the customer screen, and let members check in there with their PIN.",
    "description": """
The Point of Sale side of Centric Gym.

Selling a membership:

* Tapping a gym membership product requires a customer, who must already be a
  member with a signed waiver.
* Odoo creates the subscription quotation: it starts today, or the day after
  the current membership ends for a renewal, and lasts the product's recurring
  plan. It also sends the membership agreement for signature.
* The agreement is shown on the customer screen for the member (or their
  guardian) to sign; the cashier can also open it on their own screen. Once it
  is signed, the subscription is confirmed and added to the order for payment.
* Payment is refused while any membership in the order is unsigned. After
  payment the POS order is linked to the agreement.
* A sale abandoned before payment is cancelled (straight away, or after 12
  hours) and its agreement voided. Until then it does not count as a
  membership. A refunded membership creates a to-do for the manager.

On the customer screen (the member's tablet):

* Members check in by typing their PIN. Wrong PINs are rate-limited.
* After a check-in at reception or on the tablet, the screen shows the
  member's name, photo and "Active" / "Please speak to reception", never any
  other details.

Set the gym location of each Point of Sale in its settings.
""",
    "version": "19.0.1.0.1",
    "category": "Services/Gym",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "centric_gym_membership",
        "centric_gym_sign",
        "point_of_sale",
        "pos_sale",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/gym_pos_data.xml",
        "views/res_config_settings_views.xml",
        "views/gym_agreement_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "centric_gym_pos/static/src/pos/**/*",
        ],
        "point_of_sale.customer_display_assets": [
            "centric_gym_pos/static/src/customer_display/**/*",
        ],
        "web.assets_backend": [
            "centric_gym_pos/static/src/reception/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
