import { toRaw } from "@odoo/owl";
import { CustomerDisplayPosAdapter } from "@point_of_sale/app/customer_display/customer_display_adapter";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { GymMembershipDialog } from "./gym_membership_dialog";

function isGymMembership(template) {
    return Boolean(template?.gym_membership);
}

patch(PosStore.prototype, {
    async setup() {
        this.gymDisplay = null;
        await super.setup(...arguments);
    },

    async addLineToCurrentOrder(vals, opts = {}, configure = true) {
        const template =
            typeof vals.product_tmpl_id === "number"
                ? this.data.models["product.template"].get(vals.product_tmpl_id)
                : vals.product_tmpl_id;
        // Lines coming from the signed subscription carry sale_order_origin_id.
        if (isGymMembership(template) && !vals.sale_order_origin_id) {
            await this.gymSellMembership(template);
            return;
        }
        return super.addLineToCurrentOrder(vals, opts, configure);
    },

    async gymSellMembership(template) {
        let order = this.getOrder();
        if (!order) {
            order = this.addNewOrder();
        }
        if (!order.getPartner()) {
            await this.selectPartner(order);
        }
        const partner = order.getPartner();
        if (!partner) {
            return;
        }
        const product = template.product_variant_ids[0];
        const prep = await this.data.call("sale.order", "gym_pos_prepare", [
            partner.id,
            product.id,
            this.config.id,
        ]);
        const signed = await makeAwaitable(this.dialog, GymMembershipDialog, { prep, pos: this });
        if (!signed) {
            await this.data.call("sale.order", "gym_pos_cancel", [[prep.order_id]]);
            return;
        }
        await this.gymSettleMembership(prep.order_id);
    },

    async gymSettleMembership(saleOrderId) {
        const saleOrder = await this._getSaleOrder(saleOrderId);
        const order = this.getOrder();
        if (saleOrder.partner_id) {
            order.setPartner(saleOrder.partner_id);
        }
        order.update({ fiscal_position_id: saleOrder.fiscal_position_id });
        await this.settleSO(saleOrder, saleOrder.fiscal_position_id);
    },

    setGymDisplay(value) {
        this.gymDisplay = value;
        const order = this.getOrder();
        if (order) {
            const adapter = new CustomerDisplayPosAdapter();
            adapter.formatOrderData(order);
            adapter.dispatch(this);
        }
    },

    async pay() {
        const order = this.getOrder();
        const saleOrderIds = [
            ...new Set(
                (order?.lines || [])
                    .filter(
                        (line) =>
                            line.sale_order_origin_id &&
                            isGymMembership(line.product_id?.product_tmpl_id)
                    )
                    .map((line) => line.sale_order_origin_id.id)
            ),
        ];
        if (saleOrderIds.length) {
            const check = await this.data.call("sale.order", "gym_pos_check_payable", [saleOrderIds]);
            if (!check.ok) {
                this.dialog.add(AlertDialog, {
                    title: _t("Membership agreement"),
                    body: check.message,
                });
                return;
            }
        }
        return super.pay(...arguments);
    },
});

patch(CustomerDisplayPosAdapter.prototype, {
    dispatch(pos) {
        // Only the signing state: check-in results travel as "gym_welcome".
        this.data.gym = toRaw(pos).gymDisplay || null;
        return super.dispatch(pos);
    },
});
