{
    "name": "Centric Stock Email Import",
    "summary": "Receive stocktake Excel sheets by email and apply the counted "
               "quantities to Physical Inventory, updating stock value.",
    "description": "An administrator emails an Excel stocktake sheet to a "
                   "dedicated mail alias (e.g. stocktake@yourcompany.odoo.com). "
                   "Each email becomes a Stock Email Import record. The sheet is "
                   "validated as a whole - product, location, lot and quantity on "
                   "every row - and only if every row is valid are the counted "
                   "quantities applied as inventory adjustments, exactly as "
                   "Inventory > Physical Inventory > Apply does. On-hand stock "
                   "and, with automated valuation, the inventory value and its "
                   "journal entries follow.\n\n"
                   "Columns are matched by header name through an editable "
                   "column mapping, so sheets are not tied to one fixed layout.",
    "version": "19.0.1.4.0",
    "category": "Inventory/Inventory",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "stock",
        "stock_account",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "data": [
        "security/stock_email_import_security.xml",
        "security/ir.model.access.csv",
        "data/stock_email_import_column_data.xml",
        "data/ir_cron.xml",
        "views/stock_email_import_views.xml",
        "views/stock_email_import_config_views.xml",
        "views/stock_email_import_column_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "centric_stock_email_import/static/src/scss/stock_email_import.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
