import { Component, onWillUnmount, useState } from "@odoo/owl";
import { CustomerDisplay } from "@point_of_sale/customer_display/customer_display";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";

const SIGNED_MS = 4000;
const WELCOME_MS = 6000;
const PIN_IDLE_MS = 30000;

/**
 * Gym layers over the customer screen:
 * - the membership agreement to sign (sent by the Point of Sale),
 * - the check-in result (from reception or the PIN pad),
 * - the PIN pad members use to check in.
 */
export class GymDisplayOverlay extends Component {
    static template = "centric_gym_pos.GymDisplayOverlay";
    static props = { data: Object };

    setup() {
        // The standard screen reads order.lines.length as soon as it holds any
        // key, so a check-in arriving before the first order would crash it.
        if (!Array.isArray(this.props.data.lines)) {
            this.props.data.lines = [];
        }
        this.state = useState({ now: Date.now(), pinOpen: false, pin: "", busy: false, error: "" });
        this.ticker = setInterval(() => {
            this.state.now = Date.now();
            if (this.state.pinOpen && this.state.now - this.pinTouched > PIN_IDLE_MS) {
                this.closePin();
            }
        }, 1000);
        onWillUnmount(() => clearInterval(this.ticker));
    }

    get sign() {
        const gym = this.props.data.gym;
        if (!gym) {
            return null;
        }
        if (gym.type === "sign" || (gym.type === "signed" && this.state.now - gym.at < SIGNED_MS)) {
            return gym;
        }
        return null;
    }

    get welcome() {
        const welcome = this.props.data.gym_welcome;
        return welcome && this.state.now - (welcome.at || 0) < WELCOME_MS ? welcome : null;
    }

    get idle() {
        return !this.sign && !this.welcome && !(this.props.data.lines || []).length;
    }

    get keys() {
        return ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "ok"];
    }

    photoSrc(welcome) {
        return welcome.photo ? `data:image/png;base64,${welcome.photo}` : "";
    }

    openPin() {
        Object.assign(this.state, { pinOpen: true, pin: "", error: "" });
        this.pinTouched = Date.now();
    }

    closePin() {
        Object.assign(this.state, { pinOpen: false, pin: "", error: "" });
    }

    async press(key) {
        this.pinTouched = Date.now();
        this.state.error = "";
        if (key === "clear") {
            this.state.pin = "";
        } else if (key === "ok") {
            await this.submit();
        } else if (this.state.pin.length < 4) {
            this.state.pin += key;
            if (this.state.pin.length === 4) {
                await this.submit();
            }
        }
    }

    async submit() {
        if (this.state.busy || this.state.pin.length !== 4) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await rpc("/centric_gym_pos/display/checkin", {
                config_id: session.config_id,
                access_token: session.access_token,
                pin: this.state.pin,
            });
            if (result.error) {
                this.state.error = result.error;
                this.state.pin = "";
                return;
            }
            this.closePin();
            this.props.data.gym_welcome = { ...result.display, at: Date.now() };
        } catch {
            this.state.error = _t("Something went wrong. Please ask reception.");
        } finally {
            this.state.busy = false;
        }
    }
}

patch(CustomerDisplay, {
    components: { ...CustomerDisplay.components, GymDisplayOverlay },
});
