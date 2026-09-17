{
    "name": "Centric Gym Agreements",
    "summary": "New members sign the gym waiver with Odoo Sign before they become members.",
    "description": """
Connects Centric Gym to Odoo Sign.

* Agreement templates: the waiver for new members and the membership
  agreement, each pointing to a Sign template the gym prepares from its own PDF,
  with a version. A new wording is a new template, and members must then sign
  again.
* Agreements: one record per document sent, following its Sign request
  (waiting, signed, cancelled). It keeps the member, the signer, the version and
  the signing time. Managers can void one and download the signed PDF.
* New Gym Member: reception enters the details and takes the photo. Odoo creates
  the contact as "waiting for waiver" and sends the waiver. Once it is signed
  (on this screen, a second screen or the emailed link), the contact becomes a
  member and gets a PIN. A minor's parent or guardian signs.
* Check-in is refused until the current waiver version is signed. Members who
  signed on paper get "Paper Waiver Version" (importable), so existing members
  are not blocked.

Odoo Sign emails every signer, so a signer needs an email address.
""",
    "version": "19.0.1.0.0",
    "category": "Services/Gym",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": ["centric_gym_core", "sign"],
    "data": [
        "security/gym_sign_security.xml",
        "security/ir.model.access.csv",
        "data/gym_sign_data.xml",
        "views/gym_agreement_views.xml",
        "wizard/gym_member_intake_views.xml",
        "views/res_partner_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
