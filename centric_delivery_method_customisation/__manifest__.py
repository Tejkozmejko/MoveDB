{
    "name": "Centric Inventory & Delivery",
    "summary": "Inventory & delivery customisations - delivery methods, lot assignment, backorder control, expiry warnings, and the returns flow.",
    "description": "Umbrella inventory & delivery application. Consolidates the "
                   "previously separate Centric inventory modules into a single "
                   "installable app. This module is the container: it keeps its own "
                   "technical name (centric_delivery_method_customisation) so the "
                   "modules that depend on it (Centric Sales, the accounting modules) "
                   "keep resolving, and it adopts the data of the absorbed modules via "
                   "an upgrade migration so existing columns, config and reports are "
                   "preserved rather than dropped. The absorbed modules are left "
                   "installed as inert shells and can be removed in a later step.\n\n"
                   "Note: the former centric_backorder_toggle post_init_hook (which "
                   "seeded per-company backorder picking-type scope on fresh install) "
                   "is intentionally not carried over -- the existing company config is "
                   "preserved by the adoption migration, and re-seeding could overwrite "
                   "an administrator's choices.",
    "version": "19.0.2.11.3",
    "category": "Sales/Inventory",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "sale_stock",
        "stock_delivery",
        "hr",
        "product_expiry",
        "stock",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/loadsheet_category_data.xml",
        "data/ir_config_parameter.xml",
        "views/loadsheet_category_views.xml",
        "views/product_template_views.xml",
        "views/sale_order_views.xml",
        "views/res_partner_views.xml",
        "views/stock_picking_views.xml",
        "views/stock_picking_quantity_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "views/account_move_views.xml",
        "wizard/expiry_confirmation_views.xml",
        "wizard/delivery_split_confirmation_views.xml",
        "views/res_config_settings_views_auto_lot.xml",
        "views/res_config_settings_views_backorder.xml",
        "views/sale_order_views_not_delivered.xml",
        "views/stock_picking_views_not_delivered.xml",
        "report/report_stockpicking_operations.xml",
        "report/report_saleorder_delivery_date.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "centric_delivery_method_customisation/static/src/js/carrier_dropdown_field.js",
            "centric_delivery_method_customisation/static/src/js/required_quantity_field.js",
            "centric_delivery_method_customisation/static/src/js/stock_picking_quantity_wizard.js",
            "centric_delivery_method_customisation/static/src/js/lots_serials_button.js",
            "centric_delivery_method_customisation/static/src/xml/lots_serials_button.xml",
            "centric_delivery_method_customisation/static/src/scss/stock_picking_quantity_wizard.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
