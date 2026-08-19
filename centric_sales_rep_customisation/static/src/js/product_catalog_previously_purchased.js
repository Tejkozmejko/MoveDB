/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { ProductCatalogKanbanController } from "@product/product_catalog/kanban_controller";

const FILTER_NAME = "previously_purchased";
const RECOMMENDED_FILTER_NAME = "recommended";

patch(ProductCatalogKanbanController.prototype, {
    /**
     * The "Previously Purchased" search item defined in our catalog search
     * view, or null when the catalog was not opened from a sale order.
     */
    get previouslyPurchasedFilter() {
        const items = this.env.searchModel.getSearchItems(
            (item) => item.type === "filter" && item.name === FILTER_NAME
        );
        return items.length ? items[0] : null;
    },

    get showPreviouslyPurchasedButton() {
        return this.orderResModel === "sale.order" && Boolean(this.previouslyPurchasedFilter);
    },

    get previouslyPurchasedActive() {
        return Boolean(this.previouslyPurchasedFilter?.isActive);
    },

    get previouslyPurchasedButtonLabel() {
        return _t("Previously Purchased");
    },

    get previouslyPurchasedButtonClass() {
        return this.previouslyPurchasedActive
            ? "btn btn-sm btn-primary w-100 mb-1 o_catalog_previously_purchased_button"
            : "btn btn-sm btn-secondary w-100 mb-1 o_catalog_previously_purchased_button";
    },

    togglePreviouslyPurchased() {
        const filter = this.previouslyPurchasedFilter;
        if (filter) {
            this.env.searchModel.toggleSearchItem(filter.id);
        }
    },

    /**
     * "Recommended" mirrors "Previously Purchased" but filters to the products
     * the customer usually orders (see sale.order._get_recommended_product_ids).
     */
    get recommendedFilter() {
        const items = this.env.searchModel.getSearchItems(
            (item) => item.type === "filter" && item.name === RECOMMENDED_FILTER_NAME
        );
        return items.length ? items[0] : null;
    },

    get showRecommendedButton() {
        return this.orderResModel === "sale.order" && Boolean(this.recommendedFilter);
    },

    get recommendedActive() {
        return Boolean(this.recommendedFilter?.isActive);
    },

    get recommendedButtonLabel() {
        return _t("Recommended");
    },

    get recommendedButtonClass() {
        return this.recommendedActive
            ? "btn btn-sm btn-primary w-100 o_catalog_recommended_button"
            : "btn btn-sm btn-secondary w-100 o_catalog_recommended_button";
    },

    toggleRecommended() {
        const filter = this.recommendedFilter;
        if (filter) {
            this.env.searchModel.toggleSearchItem(filter.id);
        }
    },
});
