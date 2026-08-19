/** @odoo-module **/

import { onMounted, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { ProductCatalogKanbanController } from "@product/product_catalog/kanban_controller";

const HIDE_PRICES_BODY_CLASS = "o_sale_catalog_hide_prices";

function storageKey(controller) {
    const resModel = controller.orderResModel || controller.props.context.product_catalog_order_model || "order";
    const orderId = controller.orderId || controller.props.context.order_id || "global";
    return `sale_catalog_hide_prices:${resModel}:${orderId}`;
}

patch(ProductCatalogKanbanController.prototype, {
    setup() {
        super.setup(...arguments);
        this.catalogHidePricesState = useState({ hide: false });
        this.catalogHidePricesStorageKey = null;

        onMounted(() => {
            this.catalogHidePricesStorageKey = storageKey(this);

            const contextValue = Boolean(this.props.context.hide_catalog_prices);
            const fieldValue = Boolean(this.orderStateInfo && this.orderStateInfo.hide_catalog_prices);
            const savedValue = window.localStorage.getItem(this.catalogHidePricesStorageKey);

            this.catalogHidePricesState.hide = Boolean(
                contextValue || fieldValue || savedValue === "1"
            );
            this._applyCatalogPriceVisibility();
        });

        onWillUnmount(() => {
            document.body.classList.remove(HIDE_PRICES_BODY_CLASS);
        });
    },

    get stateFiels() {
        if (this.orderResModel === "sale.order") {
            return ["state", "hide_catalog_prices"];
        }
        return ["state"];
    },

    get catalogHidePricesButtonLabel() {
        return this.catalogHidePricesState.hide ? _t("Show Prices") : _t("Hide Prices");
    },

    get catalogHidePricesButtonClass() {
        return this.catalogHidePricesState.hide
            ? "btn btn-warning ms-2 o_catalog_hide_prices_button"
            : "btn btn-secondary ms-2 o_catalog_hide_prices_button";
    },

    async toggleCatalogPrices() {
        this.catalogHidePricesState.hide = !this.catalogHidePricesState.hide;
        this._applyCatalogPriceVisibility();
        this._saveCatalogPricePreference();

        if (this.orderResModel === "sale.order" && this.orderId) {
            await this.orm.write("sale.order", [this.orderId], {
                hide_catalog_prices: this.catalogHidePricesState.hide,
            });
        }
    },

    _applyCatalogPriceVisibility() {
        document.body.classList.toggle(
            HIDE_PRICES_BODY_CLASS,
            Boolean(this.catalogHidePricesState.hide)
        );
    },

    _saveCatalogPricePreference() {
        this.catalogHidePricesStorageKey = this.catalogHidePricesStorageKey || storageKey(this);
        window.localStorage.setItem(
            this.catalogHidePricesStorageKey,
            this.catalogHidePricesState.hide ? "1" : "0"
        );
    },
});
