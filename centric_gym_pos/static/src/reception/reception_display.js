import { GymReception } from "@centric_gym_core/reception/reception";
import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";

patch(GymReception.prototype, {
    showCard(card) {
        super.showCard(card);
        if (card?.display) {
            this.gymSendToDisplay(card.display);
        }
    },

    /**
     * Show the result on the customer screen: directly when it runs in this
     * browser, through the server when it runs on another device.
     */
    gymSendToDisplay(display) {
        const payload = { ...display, at: Date.now() };
        try {
            const channel = new BroadcastChannel("UPDATE_CUSTOMER_DISPLAY");
            channel.postMessage({ gym_welcome: payload });
            channel.close();
        } catch {
            // No BroadcastChannel: the server path below still works.
        }
        const deviceUuid = browser.localStorage.getItem("device_uuid");
        if (deviceUuid) {
            this.orm
                .call("pos.config", "gym_notify_display", [this.state.locationId, payload, deviceUuid])
                .catch(() => {});
        }
    },
});
