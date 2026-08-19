/** @odoo-module **/

import { onMounted, onWillDestroy, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

const CENTRIC_PICKING_ROW_HIGHLIGHT_EVENT = "centric-stock-picking-row-highlight";

function getRecordResId(record) {
    return record?.resId || record?.data?.id || record?.id || false;
}

registry.category("actions").add("centric_highlight_stock_picking", (env, action) => {
    const pickingId = parseInt(action?.params?.picking_id, 10);
    if (pickingId) {
        setTimeout(() => {
            window.dispatchEvent(new CustomEvent(CENTRIC_PICKING_ROW_HIGHLIGHT_EVENT, {
                detail: { pickingId },
            }));
        }, 0);
    }
    return { type: "ir.actions.act_window_close" };
});

// Open the pick-list auto-print page in a new tab AND close the calling dialog.
// Returned by the backorder-confirmation wizard on the PICK "Print & Validate"
// flow: a bare act_url would open the print tab but leave the "Create Backorder?"
// popup on screen, so the picks never appear to proceed. Closing the dialog here
// lets the list behind it reload, exactly like the in-stock (no popup) path.
registry.category("actions").add("centric_open_picking_print", (env, action) => {
    const url = action?.params?.url;
    if (url) {
        window.open(url, "_blank");
    }
    return { type: "ir.actions.act_window_close" };
});

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this._centricPickingRowHighlightState = useState({ version: 0 });
        this._centricHighlightedPickingIds = new Set();

        if (!this._centricIsStockPickingList()) {
            return;
        }

        this._centricHandlePickingRowHighlight = (event) => {
            const pickingId = parseInt(event.detail?.pickingId, 10);
            if (!pickingId) {
                return;
            }
            this._centricHighlightedPickingIds.add(pickingId);
            this._centricPickingRowHighlightState.version++;
        };

        onMounted(() => {
            window.addEventListener(
                CENTRIC_PICKING_ROW_HIGHLIGHT_EVENT,
                this._centricHandlePickingRowHighlight
            );
        });
        onWillDestroy(() => {
            window.removeEventListener(
                CENTRIC_PICKING_ROW_HIGHLIGHT_EVENT,
                this._centricHandlePickingRowHighlight
            );
            this._centricHighlightedPickingIds.clear();
        });
    },

    getRowClass(record) {
        let rowClass = super.getRowClass(...arguments) || "";
        if (this._centricIsHighlightedPickingRow(record)) {
            rowClass = `${rowClass} o_centric_saved_picking_row`;
        }
        return rowClass.trim();
    },

    _centricIsStockPickingList() {
        return this.props.list?.resModel === "stock.picking";
    },

    _centricIsHighlightedPickingRow(record) {
        this._centricPickingRowHighlightState.version;
        return (
            this._centricIsStockPickingList()
            && (
                Boolean(record?.data?.centric_quantity_verified)
                || this._centricHighlightedPickingIds.has(getRecordResId(record))
            )
        );
    },
});
