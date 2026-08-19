/**
 * Self-service "Create account" popup shown on the customer-facing display.
 *
 * The display has no POS models, so it POSTs the few fields (name/phone/email)
 * to our public, token-validated controller. The controller creates the partner
 * and notifies the cashier POS over the bus, which then selects the customer on
 * the live order - that selection re-broadcasts back to this screen, so the new
 * customer + loyalty panel appear automatically once the popup closes.
 */
import { Component, useState, useRef, onMounted } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { rpc } from "@web/core/network/rpc";
import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";

export class AzzCreateAccountPopup extends Component {
    static template = "centric_pos_customer_display.CreateAccountPopup";
    static components = { Dialog };
    static props = { close: Function };

    setup() {
        this.state = useState({
            name: "",
            phone: "",
            email: "",
            error: "",
            saving: false,
        });
        this.nameRef = useRef("name");
        onMounted(() => this.nameRef.el?.focus());
    }

    get canSubmit() {
        return this.state.name.trim().length > 0 && !this.state.saving;
    }

    onKeyup(ev) {
        // Bound method (OWL only auto-binds bare method-name handlers, not calls
        // made inside an inline arrow expression).
        if (ev.key === "Enter") {
            this.confirm();
        }
    }

    async confirm() {
        if (!this.canSubmit) {
            this.state.error = _t("Please enter your name.");
            return;
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            const res = await rpc("/centric_pos_customer_display/create_partner", {
                config_id: session.config_id,
                access_token: session.access_token,
                device_uuid: session.device_uuid,
                name: this.state.name,
                phone: this.state.phone,
                email: this.state.email,
            });
            if (res?.error) {
                this.state.error = this._errorText(res.error);
                this.state.saving = false;
                return;
            }
            // Success: the POS will attach the partner and the display refreshes.
            this.props.close();
        } catch {
            this.state.saving = false;
            this.state.error = _t("Could not create the account. Please ask the cashier.");
        }
    }

    cancel() {
        this.props.close();
    }

    _errorText(code) {
        const map = {
            name_required: _t("Please enter your name."),
            invalid_email: _t("Please enter a valid email address."),
            invalid_token: _t("Session error. Please ask the cashier."),
        };
        return map[code] || _t("Something went wrong. Please ask the cashier.");
    }
}
