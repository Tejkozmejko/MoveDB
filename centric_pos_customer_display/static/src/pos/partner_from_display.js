/**
 * Cashier-side receiver for the customer display's self-service account creation.
 *
 * When a customer creates an account on the second screen, our controller creates
 * the partner and fires an `AZZ_NEW_PARTNER-<device_uuid>` bus notification on the
 * pos.config access_token channel (the same channel the POS already listens on for
 * SYNCHRONISATION). We subscribe to it here, load the partner into the POS models
 * and select it on the live order - which re-broadcasts to the display.
 */
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { patch } from "@web/core/utils/patch";

patch(PosStore.prototype, {
    async setup() {
        await super.setup(...arguments);
        this._azzListenForDisplayPartner();
    },

    _azzListenForDisplayPartner() {
        const deviceUuid = localStorage.getItem("device_uuid");
        // connectWebSocket registers the channel and re-subscribes on reconnect.
        if (!deviceUuid || !this.data?.connectWebSocket) {
            return;
        }
        this.data.connectWebSocket(`AZZ_NEW_PARTNER-${deviceUuid}`, (payload) =>
            this._azzSelectDisplayPartner(payload)
        );
    },

    async _azzSelectDisplayPartner(payload) {
        const partnerId = payload?.id;
        if (!partnerId) {
            return;
        }
        let partner = this.models["res.partner"].get(partnerId);
        if (!partner) {
            await this.data.read("res.partner", [partnerId]);
            partner = this.models["res.partner"].get(partnerId);
        }
        const order = this.getOrder();
        if (partner && order && !order.finalized) {
            order.setPartner(partner);
            // Recompute loyalty rewards/points now that we have a customer.
            await this.updateRewards?.();
        }
    },
});
