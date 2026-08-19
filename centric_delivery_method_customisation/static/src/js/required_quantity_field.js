/** @odoo-module **/

import { registry } from "@web/core/registry";
import { FloatField, floatField } from "@web/views/fields/float/float_field";

/**
 * Quantity field for the "Items" popup (the pack/pick quantity wizard) that
 * starts BLANK and forces the operator to type a value - 0 included - instead of
 * silently accepting a pre-filled 0.
 *
 * How "not entered" is represented: an Odoo Float can never be null in the ORM
 * (an unset Float reads back as 0.0), and 0 is a legitimate quantity (out of
 * stock / short-ship), so we cannot use 0 to mean "blank". Instead the wizard
 * writes a NEGATIVE sentinel (see _QTY_NOT_ENTERED in the Python model) on a
 * line whose quantity has not been entered yet - packed/picked quantities are
 * always >= 0, so a negative value is never a real entry.
 *
 * This widget extends the standard FloatField so it keeps normal editable-list
 * behaviour (reliable click-to-type, focus, keyboard nav). It only overrides the
 * DISPLAY: a not-entered line renders an empty cell. As soon as the operator
 * types a number the value becomes >= 0 and renders normally.
 *
 * `isEmpty` reports the sentinel as empty, which drives the empty-cell styling
 * (and the required-field asterisk). Note: Odoo core skips required-field
 * validation for float/monetary fields in the browser, so the hard "you must
 * enter a value" rule is enforced SERVER-SIDE by the Python guard in
 * action_save_quantities, which rejects any line still holding the sentinel on
 * Save. The blank cell here is the visual cue for that rule, not the gate.
 */
export class CentricRequiredQuantityField extends FloatField {
    get centricNotEntered() {
        const value = this.props.record.data[this.props.name];
        return typeof value === "number" && value < 0;
    }

    get formattedValue() {
        return this.centricNotEntered ? "" : super.formattedValue;
    }
}

export const centricRequiredQuantityField = {
    ...floatField,
    component: CentricRequiredQuantityField,
    isEmpty: (record, fieldName) => {
        const value = record.data[fieldName];
        return value === false || (typeof value === "number" && value < 0);
    },
};

registry.category("fields").add("centric_required_quantity", centricRequiredQuantityField);
