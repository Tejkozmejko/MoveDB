# Container's own (sales representative customisation):
from . import res_partner
from . import res_users
# Absorbed from centric_customer_code:
from . import res_partner_customer_code
# Absorbed from centric_customer_sales_ytd:
from . import res_partner_sales_ytd
# Absorbed from centric_customer_sales_drilldown:
from . import res_partner_drilldown
# Absorbed from centric_sales_customer_restriction:
from . import res_users_customer_restriction
from . import sale_order_customer_restriction
# Absorbed from centric_sale_barcode_entry:
from . import sale_order_barcode
# Absorbed from centric_sale_catalog_previously_purchased:
from . import product_product_catalog
from . import sale_order_catalog
from . import sale_order_line_catalog
# Absorbed from sale_catalog_hide_prices:
from . import sale_order_hide_prices
from . import sale_order_line_hide_prices
# Absorbed from centric_sale_customer_po:
from . import sale_order_customer_po
from . import account_move_customer_po
# Info Note (customer-facing) + keeping product-line notes internal:
from . import sale_order_info_note
from . import account_move_info_note
from . import sale_order_line_internal_note
# Wastage recorded against an order line (Scrap button, next to Catalog):
from . import sale_order_line_scrap
from . import sale_order_scrap
# Unit Price dropdown: the customer's previous prices for the product:
from . import sale_order_line_price_history
