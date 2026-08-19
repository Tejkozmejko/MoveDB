/** @odoo-module */

import { patch } from "@web/core/utils/patch";
import { formatCurrency } from "@web/core/currency";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { Orderline } from "@point_of_sale/app/components/orderline/orderline";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

/**
 * 18 -> "18%", 7.5 -> "7.5%", 0 -> "0%".
 */
function formatTaxPercent(amount) {
    return `${parseFloat((Math.round(amount * 100) / 100).toFixed(2))}%`;
}

patch(PosOrderline.prototype, {
    /**
     * The percentage tax rates that apply to this line, after fiscal position
     * mapping. Same source as the native `taxGroupLabels`, but the rates
     * themselves rather than the tax group's letter code.
     */
    get taxPercentRates() {
        let taxes = this.tax_ids;
        if (this.order_id?.fiscal_position_id) {
            taxes = this.order_id.fiscal_position_id.getTaxesAfterFiscalPosition(this.tax_ids);
        }
        return [
            ...new Set(
                (taxes || []).filter((tax) => tax.amount_type === "percent").map((t) => t.amount)
            ),
        ];
    },

    /**
     * The tax detail printed under the line on the receipt, e.g.
     * "F: +0.27 EUR (18%)" - tax group code, the VAT this line carries, rate.
     */
    get taxDetailLabel() {
        const rates = this.taxPercentRates;
        if (!rates.length) {
            return "";
        }
        const amount = this.currency.round(this.priceIncl - this.priceExcl);
        const money = formatCurrency(amount, this.currency.id);
        const code = this.taxGroupLabels;
        return `${code ? code + ": " : ""}${amount >= 0 ? "+" : ""}${money} (${rates
            .map(formatTaxPercent)
            .join(" ")})`;
    },
});

patch(PosOrder.prototype, {
    /**
     * Total VAT of the order. Derived as Total - Subtotal on purpose, so the
     * three amounts printed at the foot of the receipt always add up.
     */
    get taxAmountForReceipt() {
        return this.currency.round(this.priceIncl - this.priceExcl);
    },

    /**
     * "VAT 18%" when the whole order sits on a single rate (the common case),
     * plain "Tax" when it mixes rates - the receipt prints one combined
     * amount either way, so naming a rate there would be wrong.
     */
    get taxLabelForReceipt() {
        const rates = new Set();
        for (const line of this.lines || []) {
            if (line.is_hidden) {
                continue;
            }
            for (const rate of line.taxPercentRates) {
                rates.add(rate);
            }
        }
        return rates.size === 1 ? `VAT ${formatTaxPercent([...rates][0])}` : "Tax";
    },
});

patch(Orderline.prototype, {
    get lineScreenValues() {
        const vals = super.lineScreenValues;
        // showTaxGroup is only set by the receipt; the cashier order list and
        // the customer display keep the native rendering.
        if (this.props.showTaxGroup && this.line.order_id) {
            // The letter code moves into the tax detail line below the price,
            // so drop the narrow column that used to hold it on its own.
            vals.taxGroup = false;
            vals.taxDetail = this.line.taxDetailLabel;
        }
        return vals;
    },
});

patch(OrderReceipt.prototype, {
    /**
     * Native only turns the per-line tax display on when a tax group has a
     * receipt label set. We also want it whenever a line carries a percentage
     * tax, since we now print the rate and the amount too.
     */
    doesAnyOrderlineHaveTaxLabel() {
        return (
            super.doesAnyOrderlineHaveTaxLabel() ||
            Boolean(this.order.lines?.some((line) => line.taxPercentRates.length))
        );
    },
});
