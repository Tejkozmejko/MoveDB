{
    "name": "Centric Gym",
    "summary": "Gym members on the contact: member PIN, membership card, health data, locations and access groups.",
    "description": """
The foundation of the Centric Gym Management suite. A gym member is an ordinary
contact - there is no second member table - and this module adds what a gym
needs on it:

* A member state (pending, member, former) that only a manager or the system
  changes, so a plain "New" in Contacts never creates a member by accident.
* A unique 4-digit member PIN, handed out automatically. PINs of members who
  have been inactive long enough are released and, after a waiting period,
  reused. Every assignment is kept in a PIN history.
* A card barcode built from the PIN and a card number. A lost card is replaced
  by bumping the card number, and a reused PIN continues its predecessor's card
  numbers, so an old card can never identify the next holder.
* A printable CR80 membership card and a webcam "Take Photo" button.
* Date of birth, guardian for minors and an emergency contact.
* Health information in its own model, readable only by the Gym Health Data
  group. Reception sees a health-alert flag, never the details.
* Gym locations, ready for more than one site.

Memberships (Subscriptions), agreements (Sign), check-in and the POS flow are
built on top of this in the next phases.
""",
    "version": "19.0.1.0.0",
    "category": "Services/Gym",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "contacts",
        "mail",
    ],
    "data": [
        "security/gym_security.xml",
        "security/ir.model.access.csv",
        "data/gym_cron.xml",
        "report/gym_member_card_report.xml",
        "views/gym_location_views.xml",
        "views/gym_pin_assignment_views.xml",
        "views/gym_member_health_views.xml",
        "views/res_partner_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "centric_gym_core/static/src/member_photo/*",
        ],
        "web.assets_tests": [
            "centric_gym_core/static/tests/tours/*",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
