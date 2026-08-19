/** @odoo-module */

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { formatCurrency } from "@web/core/currency";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { useSetupAction } from "@web/search/action_hook";

const REPORT = "account.invoice.report";
const AGGREGATES = ["price_subtotal:sum", "quantity:sum"];
const STASH_KEY = "centric_client_statistics_last";

/**
 * "Client Statistics" drill-down: cascading Year -> Month -> Day -> Invoice
 * columns over the customer's posted invoices/credit notes, with a
 * products-sold panel that always reflects the deepest selected period.
 * Replicates the legacy system's screen.
 *
 * Navigation resilience:
 * - Breadcrumb back-navigation restores the full drill-down state via
 *   useSetupAction/getLocalState (props.state on restore).
 * - Browser back / URL reload loses the action params, so the partner is
 *   re-resolved from saved state, action context or a sessionStorage stash,
 *   and the partner name/currency are re-fetched when missing.
 */
export class ClientStatistics extends Component {
    static template = "centric_customer_sales_drilldown.ClientStatistics";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.partnerId = false;
        this.currencyId = false;
        this.state = useState({
            ready: false,
            partnerName: "",
            years: [],
            months: [],
            days: [],
            invoices: [],
            selYear: null,
            selMonth: null,
            selDay: null,
            selInvoice: null,
            products: [],
            productsTitle: "",
            productFilter: "",
            loading: false,
        });
        useSetupAction({
            getLocalState: () => this.snapshot(),
        });
        onWillStart(() => this.init());
    }

    get partnerName() {
        return this.state.partnerName;
    }

    snapshot() {
        const s = this.state;
        return {
            partnerId: this.partnerId,
            currencyId: this.currencyId,
            partnerName: s.partnerName,
            years: s.years,
            months: s.months,
            days: s.days,
            invoices: s.invoices,
            selYear: s.selYear,
            selMonth: s.selMonth,
            selDay: s.selDay,
            selInvoice: s.selInvoice,
            products: s.products,
            productsTitle: s.productsTitle,
            productFilter: s.productFilter,
        };
    }

    readStash() {
        try {
            return JSON.parse(browser.sessionStorage.getItem(STASH_KEY)) || {};
        } catch {
            return {};
        }
    }

    async init() {
        const params = this.props.action?.params || {};
        const context = this.props.action?.context || {};
        const saved = this.props.state;
        const stash = this.readStash();

        this.partnerId =
            params.partner_id || saved?.partnerId || context.active_id || stash.partnerId || false;
        if (!this.partnerId) {
            return; // state.ready stays false -> hint message
        }

        // Breadcrumb restore: reuse the saved object graph so the current
        // selections (identity-compared in the template) survive intact.
        if (saved && saved.partnerId === this.partnerId) {
            this.currencyId = saved.currencyId;
            Object.assign(this.state, {
                partnerName: saved.partnerName,
                years: saved.years,
                months: saved.months,
                days: saved.days,
                invoices: saved.invoices,
                selYear: saved.selYear,
                selMonth: saved.selMonth,
                selDay: saved.selDay,
                selInvoice: saved.selInvoice,
                products: saved.products,
                productsTitle: saved.productsTitle,
                productFilter: saved.productFilter,
                ready: true,
            });
            return;
        }

        this.state.partnerName =
            params.partner_name || (stash.partnerId === this.partnerId && stash.partnerName) || "";
        this.currencyId =
            params.currency_id ||
            (stash.partnerId === this.partnerId && stash.currencyId) ||
            false;

        if (!this.state.partnerName) {
            const partners = await this.orm.read("res.partner", [this.partnerId], ["display_name"]);
            this.state.partnerName = partners[0]?.display_name || "";
        }
        if (!this.currencyId) {
            const companyId = user.activeCompany?.id;
            if (companyId) {
                const companies = await this.orm.read("res.company", [companyId], ["currency_id"]);
                const currency = companies[0]?.currency_id;
                this.currencyId = Array.isArray(currency) ? currency[0] : currency;
            }
        }

        try {
            browser.sessionStorage.setItem(
                STASH_KEY,
                JSON.stringify({
                    partnerId: this.partnerId,
                    partnerName: this.state.partnerName,
                    currencyId: this.currencyId,
                })
            );
        } catch {
            // Session storage unavailable: back-navigation fallback degrades only.
        }

        this.state.ready = true;
        await this.loadYears();
    }

    get baseDomain() {
        return [
            ["move_type", "in", ["out_invoice", "out_refund"]],
            ["state", "=", "posted"],
            ["commercial_partner_id", "child_of", this.partnerId],
        ];
    }

    // ------------------------------------------------------------------
    // Formatting helpers
    // ------------------------------------------------------------------
    fmt(amount) {
        return formatCurrency(amount || 0, this.currencyId);
    }

    fmtQty(qty) {
        return (qty || 0).toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    labelOf(group, spec) {
        const value = group[spec];
        if (Array.isArray(value)) {
            return value[1] || "";
        }
        return value === false || value === null || value === undefined
            ? "None"
            : String(value);
    }

    amountOf(group) {
        return group["price_subtotal:sum"] || 0;
    }

    qtyOf(group) {
        return group["quantity:sum"] || 0;
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------
    async groups(domain, spec) {
        return this.orm.formattedReadGroup(REPORT, domain, [spec], AGGREGATES);
    }

    async loadYears() {
        if (!this.partnerId) {
            return;
        }
        this.state.years = await this.groups(this.baseDomain, "invoice_date:year");
        this.state.months = [];
        this.state.days = [];
        this.state.invoices = [];
        this.state.selYear = null;
        this.state.selMonth = null;
        this.state.selDay = null;
        this.state.selInvoice = null;
        await this.loadProducts(this.baseDomain, "All time");
    }

    async selectYear(group) {
        this.state.selYear = group;
        this.state.selMonth = null;
        this.state.selDay = null;
        this.state.selInvoice = null;
        this.state.days = [];
        this.state.invoices = [];
        this.state.months = await this.groups(group.__domain, "invoice_date:month");
        await this.loadProducts(group.__domain, this.labelOf(group, "invoice_date:year"));
    }

    async selectMonth(group) {
        this.state.selMonth = group;
        this.state.selDay = null;
        this.state.selInvoice = null;
        this.state.invoices = [];
        this.state.days = await this.groups(group.__domain, "invoice_date:day");
        await this.loadProducts(group.__domain, this.labelOf(group, "invoice_date:month"));
    }

    async selectDay(group) {
        this.state.selDay = group;
        this.state.selInvoice = null;
        this.state.invoices = await this.groups(group.__domain, "move_id");
        await this.loadProducts(group.__domain, this.labelOf(group, "invoice_date:day"));
    }

    async selectInvoice(group) {
        this.state.selInvoice = group;
        await this.loadProducts(group.__domain, this.labelOf(group, "move_id"));
    }

    async loadProducts(domain, title) {
        this.state.loading = true;
        try {
            const groups = await this.orm.formattedReadGroup(
                REPORT,
                domain,
                ["product_id"],
                AGGREGATES
            );
            groups.sort((a, b) => this.amountOf(b) - this.amountOf(a));
            this.state.products = groups;
            this.state.productsTitle = title;
        } finally {
            this.state.loading = false;
        }
    }

    get filteredProducts() {
        const needle = (this.state.productFilter || "").toLowerCase();
        if (!needle) {
            return this.state.products;
        }
        return this.state.products.filter((group) =>
            this.labelOf(group, "product_id").toLowerCase().includes(needle)
        );
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------
    openInvoice(group, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        const value = group["move_id"];
        const moveId = Array.isArray(value) ? value[0] : value;
        if (!moveId) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "account.move",
            res_id: moveId,
            views: [[false, "form"]],
        });
    }

    openPivot() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: this.state.partnerName,
            res_model: REPORT,
            views: [
                [false, "pivot"],
                [false, "graph"],
            ],
            domain: this.baseDomain,
            context: {
                pivot_row_groupby: [
                    "invoice_date:year",
                    "invoice_date:month",
                    "invoice_date:day",
                    "product_id",
                ],
                pivot_column_groupby: [],
                pivot_measures: ["price_subtotal", "quantity"],
            },
        });
    }
}

registry.category("actions").add("centric_client_statistics", ClientStatistics);
