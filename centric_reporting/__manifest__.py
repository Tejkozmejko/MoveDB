{
    "name": "Centric Reporting",
    "summary": "Menu engineering and margin-per-product reporting, a manager reporting menu, and a scheduled daily trading summary email.",
    "description": """
Point of Sale reporting and dashboards:

* **Menu Performance** - a SQL-view report over POS order lines exposing
  quantity sold, net revenue, cost and margin per product, with pivot, graph
  and list views. Cost comes from ``pos.order.line.total_cost``, the standard
  price snapshotted at sale time, so margin is recipe-driven wherever the
  product carries a BoM-derived cost.
* **Menu engineering favourites** - saved filters for today, this week and last
  month, plus the classic stars / dogs split by volume and margin.
* **Wastage** - a pivot and graph on stock scrap, grouped by product, category
  and scrap reason.
* **Daily trading summary** - a scheduled job that emails the previous day's
  covers, net sales, cost, margin, top sellers and worst margins to the POS
  managers.

The cron is shipped **inactive**. Nothing is emailed until someone switches it
on in Settings > Technical > Scheduled Actions, which keeps installing the
module from sending mail to real people.
""",
    "version": "19.0.1.0.0",
    "category": "Sales/Point of Sale",
    "author": "Centric",
    "license": "LGPL-3",
    # point_of_sale: the order lines the report reads.
    # stock: the scrap records behind the wastage report.
    # mail: the daily summary email.
    "depends": ["point_of_sale", "stock", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/menu_report_views.xml",
        "views/wastage_views.xml",
        "views/menus.xml",
        "data/menu_report_filters.xml",
        "data/daily_summary_templates.xml",
        "data/ir_cron.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
