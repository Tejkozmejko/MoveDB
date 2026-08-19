/** @odoo-module **/

import { registry } from "@web/core/registry";
import { usePosition } from "@web/core/position/position_hook";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";
import { FloatField, floatField } from "@web/views/fields/float/float_field";

/**
 * Unit Price field for sale order lines that, while being edited, drops down
 * the prices this customer previously paid for the product (most recent
 * first, one entry per distinct price - see sale.order.line
 * centric_price_history). Clicking an entry fills it in; any other price can
 * still be typed as usual, so this stays a plain FloatField otherwise.
 *
 * The menu lives in the cell's DOM (like the many2one autocomplete), so
 * clicks on it never count as "outside the row" for the editable list, and
 * the mousedown.prevent on the entries keeps the input focused - no focusout,
 * no premature save - the click then commits the chosen price. It is however
 * POSITIONED with usePosition (fixed coordinates, exactly like the
 * autocomplete dropdown): a list cell clips absolutely-positioned children,
 * so an in-flow menu would show as a one-pixel sliver under the row.
 */
export class CentricPriceHistoryField extends FloatField {
    static template = "centric_sales_rep_customisation.PriceHistoryField";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.ph = useState({ open: false, entries: [], loadedKey: null, loading: false });
        usePosition("phMenu", () => this.inputRef.el, { position: "bottom-end" });
    }

    /** The sale.order form this line is edited in, if that is where we are. */
    get phOrder() {
        const root = this.props.record.model.root;
        return root && root.resModel === "sale.order" ? root : null;
    }

    get phProductId() {
        const product = this.props.record.data.product_id;
        return (product && product.id) || false;
    }

    get phPartnerId() {
        const order = this.phOrder;
        const partner = order
            ? order.data.partner_id
            : this.props.record.data.order_partner_id;
        return (partner && partner.id) || false;
    }

    /** True once the entries match the product/customer currently edited. */
    get phReady() {
        return (
            !this.ph.loading &&
            this.ph.loadedKey === `${this.phProductId}|${this.phPartnerId}`
        );
    }

    onFocusIn() {
        super.onFocusIn();
        this.phOpen();
    }

    onFocusOut() {
        super.onFocusOut();
        this.ph.open = false;
    }

    phOnKeydown(ev) {
        // Close only the menu, not the row being edited.
        if (ev.key === "Escape" && this.ph.open) {
            this.ph.open = false;
            ev.stopPropagation();
        }
    }

    async phOpen() {
        const productId = this.phProductId;
        const partnerId = this.phPartnerId;
        if (!productId || !partnerId || this.props.readonly) {
            return;
        }
        this.ph.open = true;
        const key = `${productId}|${partnerId}`;
        if (this.ph.loadedKey === key) {
            return; // already fetched for this product + customer
        }
        this.ph.entries = [];
        this.ph.loading = true;
        const order = this.phOrder;
        let entries = [];
        try {
            entries = await this.orm.call("sale.order.line", "centric_price_history", [productId, partnerId], {
                exclude_order_id: (order && typeof order.resId === "number" && order.resId) || false,
            });
        } catch {
            entries = []; // no history is a silent no-op, never an error popup
        } finally {
            this.ph.loading = false;
        }
        this.ph.loadedKey = key;
        this.ph.entries = entries;
    }

    async phSelect(entry) {
        this.ph.open = false;
        await this.props.record.update({ [this.props.name]: entry.price });
        // The input keeps focus (mousedown was prevented); reflect the picked
        // value even if something had been typed in it before.
        if (this.inputRef.el) {
            this.inputRef.el.value = this.formattedValue;
        }
    }
}

export const centricPriceHistoryField = {
    ...floatField,
    component: CentricPriceHistoryField,
};

registry.category("fields").add("centric_price_history", centricPriceHistoryField);
