{
    "name": "Centric Gym Memberships",
    "summary": "Gym memberships are Odoo Subscriptions: a member may check in while one is running.",
    "description": """
Connects Centric Gym to Subscriptions. A membership is a subscription whose
product is marked "Gym Membership"; nothing about it is stored twice.

* Products: a "Gym Membership" checkbox next to "Subscriptions".
* Members: the membership status (active, not started, suspended, expired,
  cancelled, no membership) is computed from their subscriptions every time it
  is read, with the current and next membership and the end date, and can be
  searched and filtered.
* Check-in: reception lets a member in only while a membership is running, and
  the check-in remembers which subscription it was.
* PIN reuse counts the membership end date as activity.
* Gym > Memberships lists the gym subscriptions.

A paused subscription means "suspended"; a renewed one still counts until its
end date; one closed before its end date means "cancelled".
""",
    "version": "19.0.1.0.0",
    "category": "Services/Gym",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": ["centric_gym_core", "sale_subscription"],
    "data": [
        "views/product_template_views.xml",
        "views/sale_order_views.xml",
        "views/res_partner_views.xml",
        "views/gym_checkin_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
