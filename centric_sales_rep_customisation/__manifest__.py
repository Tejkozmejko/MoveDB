{
    "name": "Centric Sales",
    "summary": "Sales customisations - rep access control, barcode entry, catalog tools, customer PO, and customer analytics.",
    "description": "Umbrella sales application. Consolidates the previously separate "
                   "Centric sales modules into a single installable app. This module is "
                   "the container: it keeps its own technical name "
                   "(centric_sales_rep_customisation) so the sales-representative "
                   "security group and its 21 record rules never move, and it adopts the "
                   "data of the other sales modules via an upgrade migration, so existing "
                   "columns, groups, rules and reports are preserved rather than dropped. "
                   "The absorbed modules are left installed as inert shells and can be "
                   "removed in a later step.",
    "version": "19.0.2.5.6",
    "category": "Sales/Sales",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "sale_management",
        "account",
        "account_reports",
        "sale_stock",
        "sales_team",
        "product",
        "centric_delivery_method_customisation",
    ],
    "data": [
        # --- security: groups, ACLs and rules load before the views that gate on them ---
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/barcode_entry_security.xml",
        "security/sales_customer_restriction_security.xml",
        # --- container's own views ---
        "views/sale_menu_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
        "views/product_template_views.xml",
        "views/res_partner_views.xml",
        # --- absorbed views ---
        "views/sale_order_views_barcode.xml",
        "views/product_catalog_search_views.xml",
        "views/product_views_catalog.xml",
        "views/sale_order_views_hide_prices.xml",
        "views/sale_order_views_customer_po.xml",
        "views/account_move_views_customer_po.xml",
        # Info Note anchors on the customer PO field, so it must load after it.
        "views/sale_order_views_info_note.xml",
        "views/account_move_views_info_note.xml",
        "views/res_users_views_customer_restriction.xml",
        "views/sale_order_views_customer_restriction.xml",
        "views/res_partner_views_sales_ytd.xml",
        "views/res_partner_views_drilldown.xml",
        "views/res_partner_views_customer_code.xml",
        # Wastage: the dialog view is referenced by the Scrap button's action,
        # so it loads before the order form that carries the button.
        "wizard/sale_order_scrap_wizard_views.xml",
        "views/sale_order_views_scrap.xml",
        # Unit Price dropdown with the customer's previous prices
        "views/sale_order_views_price_history.xml",
        # --- reports ---
        "reports/report_templates_customer_po.xml",
        "reports/report_templates_info_note.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # barcode entry
            "centric_sales_rep_customisation/static/src/js/barcode_scan_field.js",
            "centric_sales_rep_customisation/static/src/xml/barcode_scan_field.xml",
            # catalog: previously purchased
            "centric_sales_rep_customisation/static/src/js/product_catalog_previously_purchased.js",
            "centric_sales_rep_customisation/static/src/js/product_catalog_card.js",
            "centric_sales_rep_customisation/static/src/xml/product_catalog_previously_purchased.xml",
            "centric_sales_rep_customisation/static/src/xml/product_catalog_card.xml",
            "centric_sales_rep_customisation/static/src/css/product_catalog_recency.css",
            # catalog: hide prices
            "centric_sales_rep_customisation/static/src/js/product_catalog_hide_prices.js",
            "centric_sales_rep_customisation/static/src/xml/product_catalog_hide_prices.xml",
            "centric_sales_rep_customisation/static/src/scss/product_catalog_hide_prices.scss",
            # sale list auto-fit
            "centric_sales_rep_customisation/static/src/scss/sale_list_autofit.scss",
            # unit price: previous-prices dropdown
            "centric_sales_rep_customisation/static/src/js/price_history_field.js",
            "centric_sales_rep_customisation/static/src/xml/price_history_field.xml",
            "centric_sales_rep_customisation/static/src/css/price_history_field.css",
            # customer sales drilldown
            "centric_sales_rep_customisation/static/src/client_statistics/client_statistics.js",
            "centric_sales_rep_customisation/static/src/client_statistics/client_statistics.scss",
            "centric_sales_rep_customisation/static/src/client_statistics/client_statistics.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
