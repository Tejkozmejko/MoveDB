/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * A write-only "scan product" input for the sales order. A barcode scanner acts
 * as a keyboard: it types the code then sends Enter. We commit the code to the
 * (non-stored) field, which triggers the server onchange that adds / increments
 * the product line, then we clear the box and keep focus for the next scan.
 *
 * The logic lives in the onchange, so it still works if this widget is absent
 * (falls back to committing on blur) - that is the "widely compatible" part.
 */
export class CentricBarcodeScanField extends Component {
    static template = "centric_sale_barcode_entry.BarcodeScanField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
    };

    async onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        // Keep Enter local: commit the scan, don't let it bubble up and save the form.
        ev.preventDefault();
        ev.stopPropagation();
        const input = ev.target;
        const code = (input.value || "").trim();
        if (!code) {
            return;
        }
        try {
            // Fires the onchange, which adds/increments the line and clears the field.
            await this.props.record.update({ [this.props.name]: code });
        } finally {
            input.value = "";
            input.focus();
        }
    }
}

export const centricBarcodeScanField = {
    component: CentricBarcodeScanField,
    displayName: _t("Barcode Scan"),
    supportedTypes: ["char"],
    extractProps: ({ attrs }) => ({
        placeholder: (attrs && attrs.placeholder) || "",
    }),
};

registry.category("fields").add("centric_barcode_scan", centricBarcodeScanField);
