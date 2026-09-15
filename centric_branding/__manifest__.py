{
    "name": "Centric Branding",
    "summary": "Centric look and feel for the Odoo backend, starting with a "
               "photographic background on the home apps screen.",
    "description": "Applies Centric's own branding to the Odoo web client. At "
                   "present this is the background of the home apps screen: "
                   "Odoo's default backdrop is replaced with a Centric "
                   "warehouse photograph, darkened just enough that the white "
                   "app names stay readable over it.\n\n"
                   "The module holds styling only - no models, no data, no "
                   "access rules - so it can be installed or uninstalled "
                   "without touching business records.",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "web",
    ],
    "assets": {
        "web.assets_backend": [
            "centric_branding/static/src/scss/home_menu_background.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
