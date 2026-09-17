import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

const POLL_MS = 2000;

/**
 * Shown while the member signs the membership agreement on the customer
 * screen. Resolves true once it is signed, false if the cashier cancels.
 */
export class GymMembershipDialog extends Component {
    static template = "centric_gym_pos.GymMembershipDialog";
    static components = { Dialog };
    static props = {
        prep: Object,
        pos: Object,
        getPayload: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ status: this.props.prep.state, error: "" });
        this.done = false;
        onMounted(() => {
            this.props.pos.setGymDisplay({
                type: "sign",
                url: this.props.prep.signing_url,
                member: this.props.prep.signer,
                at: Date.now(),
            });
            this.timer = setInterval(() => this.poll(), POLL_MS);
        });
        onWillUnmount(() => {
            clearInterval(this.timer);
            this.props.pos.setGymDisplay(
                this.done ? { type: "signed", member: this.props.prep.signer, at: Date.now() } : null
            );
        });
    }

    get title() {
        return _t("Membership agreement");
    }

    async poll() {
        if (this.polling || this.done) {
            return;
        }
        this.polling = true;
        try {
            const result = await this.props.pos.data.call("sale.order", "gym_pos_poll", [
                [this.props.prep.order_id],
            ]);
            this.state.status = result.state;
            if (result.state === "signed") {
                this.done = true;
                this.props.getPayload(true);
                this.props.close();
            } else if (result.state !== "sent") {
                clearInterval(this.timer);
                this.state.error = _t("The agreement was cancelled. Start the sale again.");
            }
        } catch {
            // Keep polling: a dropped request should not end the sale.
        } finally {
            this.polling = false;
        }
    }

    openHere() {
        window.open(this.props.prep.signing_url, "_blank");
    }

    cancel() {
        this.props.getPayload(false);
        this.props.close();
    }
}
