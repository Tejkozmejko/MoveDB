/**
 * Farm Meats POS Customer Display - component patch (runs on the second screen).
 *
 * The native `CustomerDisplay` component reads a reactive `order` object that is
 * fed by the broadcast payload (see the POS-side adapter). We add:
 *   - `loyalty`  : safe accessor for the loyalty block we attached to the payload.
 *   - `formatPoints` : tidy display of point values (integers without decimals,
 *                      fractional values rounded to 2dp).
 * The template (customer_display.xml) uses both.
 */
import { CustomerDisplay } from "@point_of_sale/customer_display/customer_display";
import { patch } from "@web/core/utils/patch";
import { AzzCreateAccountPopup } from "./azz_create_account_popup";

patch(CustomerDisplay.prototype, {
    get loyalty() {
        // `this.order` is the reactive customer_display_data service object.
        return this.order?.loyalty || {};
    },

    azzCreateAccount() {
        // `this.dialog` is set by the native CustomerDisplay setup.
        this.dialog.add(AzzCreateAccountPopup, {});
    },

    formatPoints(value) {
        const n = Number(value || 0);
        if (!Number.isFinite(n)) {
            return "0";
        }
        if (Number.isInteger(n)) {
            return n.toLocaleString();
        }
        const rounded = Math.round(n * 100) / 100;
        return rounded.toLocaleString(undefined, { maximumFractionDigits: 2 });
    },
});
