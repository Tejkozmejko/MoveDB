import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { deserializeDate, deserializeDateTime, formatDate } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

const LOCATION_KEY = "centric_gym_core.reception_location";
const REFRESH_MS = 30000;
const CARD_MS = 30000;
// A PIN or a card barcode: only digits, typed or scanned into the search box.
const CODE_PATTERN = /^\d{4,}$/;

/**
 * The reception desk: scan a card (or search a name), see straight away whether
 * the member may come in, and keep an eye on who is inside.
 */
export class GymReception extends Component {
    static template = "centric_gym_core.Reception";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.searchRef = useRef("search");
        this.state = useState({
            locations: [],
            locationId: false,
            term: "",
            results: [],
            card: null,
            inside: [],
            capacity: 0,
            canOverride: false,
            busy: false,
            overriding: false,
            overrideReason: "",
        });
        this.search = useDebounced(this.searchMembers.bind(this), 250);

        const barcode = useService("barcode");
        useBus(barcode.bus, "barcode_scanned", (ev) => this.checkInCode(ev.detail.barcode, "barcode"));

        onWillStart(async () => {
            this.state.locations = await this.orm.searchRead("gym.location", [], ["name", "capacity"]);
            const saved = Number(browser.localStorage.getItem(LOCATION_KEY));
            const known = this.state.locations.find((location) => location.id === saved);
            this.state.locationId = (known || this.state.locations[0] || {}).id || false;
            await this.refresh();
        });
        onMounted(() => this.focusSearch());
        this.refreshTimer = browser.setInterval(() => this.refresh(), REFRESH_MS);
        onWillUnmount(() => {
            browser.clearInterval(this.refreshTimer);
            browser.clearTimeout(this.cardTimer);
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    async refresh() {
        if (!this.state.locationId) {
            return;
        }
        const data = await this.orm.call("gym.checkin", "gym_reception_data", [this.state.locationId]);
        this.state.inside = data.inside;
        this.state.capacity = data.capacity;
        this.state.canOverride = data.can_override;
    }

    async searchMembers() {
        const term = this.state.term.trim();
        if (term.length < 2 || CODE_PATTERN.test(term)) {
            this.state.results = [];
            return;
        }
        this.state.results = await this.orm.call("gym.checkin", "gym_search_members", [term]);
    }

    onLocationChange(ev) {
        this.state.locationId = Number(ev.target.value);
        browser.localStorage.setItem(LOCATION_KEY, String(this.state.locationId));
        this.state.card = null;
        this.refresh();
    }

    onInput() {
        this.search();
    }

    onKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const term = this.state.term.trim();
        if (CODE_PATTERN.test(term)) {
            this.checkInCode(term, term.length === 4 ? "pin" : "barcode");
        } else if (this.state.results.length === 1) {
            this.checkInMember(this.state.results[0].id);
        }
    }

    // ------------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------------

    checkInCode(code, identifiedBy) {
        return this.checkIn({ code }, identifiedBy);
    }

    checkInMember(partnerId) {
        return this.checkIn({ partner_id: partnerId }, "search");
    }

    async checkIn(target, identifiedBy) {
        if (this.state.busy) {
            return;
        }
        if (!this.state.locationId) {
            this.notification.add(_t("Create a gym location first (Gym → Configuration → Locations)."), {
                type: "warning",
            });
            return;
        }
        this.state.busy = true;
        try {
            const card = await this.orm.call("gym.checkin", "gym_check_in", [this.state.locationId], {
                ...target,
                identified_by: identifiedBy,
            });
            this.showCard(card);
        } finally {
            this.state.busy = false;
            this.state.term = "";
            this.state.results = [];
            this.focusSearch();
        }
        await this.refresh();
    }

    showCard(card) {
        this.state.card = card;
        this.state.overriding = false;
        this.state.overrideReason = "";
        browser.clearTimeout(this.cardTimer);
        this.cardTimer = browser.setTimeout(() => {
            if (!this.state.overriding) {
                this.state.card = null;
            }
        }, CARD_MS);
    }

    startOverride() {
        this.state.overriding = true;
    }

    async confirmOverride() {
        const card = await this.orm.call("gym.checkin", "gym_override", [this.state.card.checkin_id], {
            reason: this.state.overrideReason,
        });
        this.showCard(card);
        await this.refresh();
    }

    async undo() {
        await this.orm.call("gym.checkin", "gym_undo", [this.state.card.checkin_id]);
        this.state.card = null;
        this.notification.add(_t("Check-in undone."), { type: "info" });
        await this.refresh();
        this.focusSearch();
    }

    async checkOut(checkinId) {
        await this.orm.call("gym.checkin", "gym_check_out", [checkinId]);
        if (this.state.card && this.state.card.checkin_id === checkinId) {
            this.state.card = null;
        }
        await this.refresh();
        this.focusSearch();
    }

    openMember(partnerId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
        });
    }

    focusSearch() {
        this.searchRef.el?.focus();
    }

    // ------------------------------------------------------------------
    // Display helpers
    // ------------------------------------------------------------------

    photo(partnerId, writeDate) {
        return `/web/image/res.partner/${partnerId}/avatar_512?unique=${encodeURIComponent(writeDate || "")}`;
    }

    time(value) {
        return value ? deserializeDateTime(value).toFormat("HH:mm") : "";
    }

    date(value) {
        return value ? formatDate(deserializeDate(value)) : "";
    }

    get cardTone() {
        const result = this.state.card?.result;
        if (result === "allowed") {
            return "success";
        }
        if (result === "override" || result === "already_inside") {
            return "warning";
        }
        return "danger";
    }

    get cardTitle() {
        const card = this.state.card;
        switch (card?.result) {
            case "allowed":
                return _t("Checked in");
            case "override":
                return _t("Let in by override");
            case "already_inside":
                return _t("Already inside since %s", this.time(card.check_in));
            default:
                return _t("Refused");
        }
    }

    get canUndo() {
        return ["allowed", "override"].includes(this.state.card?.result);
    }

    get canOverride() {
        const card = this.state.card;
        return (
            this.state.canOverride &&
            card?.result === "denied" &&
            card.member &&
            !["unknown_code", "already_inside"].includes(card.reason)
        );
    }

    get capacityLabel() {
        const count = this.state.inside.length;
        return this.state.capacity ? `${count} / ${this.state.capacity}` : String(count);
    }

    get overCapacity() {
        return this.state.capacity && this.state.inside.length >= this.state.capacity;
    }
}

registry.category("actions").add("centric_gym_core.reception", GymReception);
