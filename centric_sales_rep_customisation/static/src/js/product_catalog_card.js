/** @odoo-module **/

import { useSubEnv } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { formatFloat, formatMonetary } from "@web/views/fields/formatters";
import { ProductCatalogKanbanRecord } from "@product/product_catalog/kanban_record";
import { ProductCatalogOrderLine } from "@product/product_catalog/order_line/order_line";
import { ProductCatalogSaleOrderLine } from "@sale_stock/product_catalog/sale_order_line/sale_order_line";

// The server adds these keys to each card's `productCatalogData`, which the
// record template spreads as props into the order-line component. Declare them
// so OWL prop validation accepts them.
const CENTRIC_CATALOG_LINE_PROPS = {
    previouslyPurchasedQty: { type: Number, optional: true },
    previouslyPurchasedPrice: { type: Number, optional: true },
    previouslyPurchasedRecency: { type: String, optional: true },
    hasPackagings: { type: Boolean, optional: true },
};
// Both the base component AND sale_stock's subclass: the subclass copies the
// base props with a spread at class-definition time (`...ProductCatalogOrderLine.props`),
// so extending only the base misses it whenever sale_stock's module happens to
// execute first in the bundle - which is exactly the "Invalid props ...
// unknown key 'previouslyPurchasedQty'" crash on opening the Sales catalog in
// debug mode. Importing the subclass above guarantees its definition already
// ran, so these assigns always land on the final props objects.
Object.assign(ProductCatalogOrderLine.props, CENTRIC_CATALOG_LINE_PROPS);
Object.assign(ProductCatalogSaleOrderLine.props, CENTRIC_CATALOG_LINE_PROPS);

patch(ProductCatalogOrderLine.prototype, {
    setup() {
        super.setup();
        this.action = useService("action");
    },

    /**
     * Open the product's own form (as a dialog) without adding it to the order.
     * Wired to the "Card" button next to Add, which stops the card's global
     * "add" click.
     */
    openProductCard() {
        // Pass the catalog's order so the product form can show this customer's
        // previously-purchased history for the product (sale.order only).
        const context = {};
        if (this.env.orderResModel === "sale.order" && this.env.orderId) {
            context.catalog_history_order_id = this.env.orderId;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: this.props.productId,
            views: [[false, "form"]],
            target: "new",
            context,
        });
    },
});

patch(ProductCatalogKanbanRecord.prototype, {
    setup() {
        super.setup();
        this.orm = useService("orm");
        // Expose the packaging cycler to the order-line child, mirroring how the
        // native record shares addProduct/increaseQuantity through the sub-env.
        useSubEnv({ cycleProductUom: this.cycleProductUom.bind(this) });
    },

    /**
     * Tint the card by how recently this customer last bought the product
     * (red <=7d, yellow <=14d, blue <=21d, purple <= a month, green older).
     * The bucket comes from the server with the card's catalog data.
     */
    getRecordClasses() {
        let classes = super.getRecordClasses();
        const recency = this.productCatalogData?.previouslyPurchasedRecency;
        if (recency) {
            classes += ` o_catalog_recency_${recency}`;
        }
        return classes;
    },

    /**
     * Advance the line to the product's next packaging (extra UoM). The server
     * reconverts quantity and re-prices, so we refresh the card from its reply.
     */
    async cycleProductUom() {
        if (this.env.orderResModel !== "sale.order" || !this.env.orderId) {
            return;
        }
        const result = await this.orm.call(
            "sale.order",
            "catalog_cycle_product_uom",
            [[this.env.orderId], this.env.productId]
        );
        if (result?.uomDisplayName) {
            // productCatalogData is reactive - mutating it re-renders the card.
            this.productCatalogData.uomDisplayName = result.uomDisplayName;
            this.productCatalogData.price = result.price;
            this.productCatalogData.quantity = result.quantity;
        }
    },

    get hasPurchaseHistory() {
        return Boolean(this.productCatalogData?.previouslyPurchasedQty);
    },

    get purchaseHistoryQty() {
        const digits = [false, this.env.precision];
        return formatFloat(this.productCatalogData.previouslyPurchasedQty || 0, {
            digits,
        });
    },

    get purchaseHistoryUom() {
        return this.productCatalogData?.uomDisplayName || "";
    },

    get hasPurchaseHistoryPrice() {
        return Boolean(this.productCatalogData?.previouslyPurchasedPrice);
    },

    get purchaseHistoryPrice() {
        const { currencyId, digits } = this.env;
        return formatMonetary(
            this.productCatalogData.previouslyPurchasedPrice || 0,
            { currencyId, digits }
        );
    },
});
