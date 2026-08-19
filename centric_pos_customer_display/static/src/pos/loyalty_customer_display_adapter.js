/**
 * Farm Meats POS Customer Display - loyalty data adapter.
 *
 * This runs in the *cashier* POS window. `CustomerDisplayPosAdapter.formatOrderData`
 * is what builds the plain-JSON payload that is broadcast to the customer-facing
 * second screen (via BroadcastChannel + the bus). The customer display window has
 * no access to the POS models, so every loyalty value has to be computed here,
 * on the live order, and shipped across as primitives.
 *
 * All numbers come from the actual configured loyalty programme(s): we reuse
 * pos_loyalty's own `order.getLoyaltyPoints()` (which reads the order's
 * couponPointChanges + reward lines against the installed loyalty.program /
 * loyalty.card records). Nothing about earning rates or programme ids is
 * hardcoded here.
 */
import { CustomerDisplayPosAdapter } from "@point_of_sale/app/customer_display/customer_display_adapter";
import { patch } from "@web/core/utils/patch";

patch(CustomerDisplayPosAdapter.prototype, {
    formatOrderData(order) {
        super.formatOrderData(...arguments);
        // Attach loyalty data to the payload broadcast to the customer display.
        this.data.loyalty = this._azzComputeLoyaltyData(order);
    },

    _azzLoyaltyDefault() {
        return {
            hasPartner: false,
            partnerName: "",
            // hasLoyalty: a loyalty programme actually applies to this customer.
            hasLoyalty: false,
            pointsName: "Points",
            balance: 0, // points currently on the card (before this order)
            won: 0, // points earned from the current order
            spent: 0, // points spent on rewards in the current order
            projected: 0, // projected balance = balance + won - spent
        };
    },

    _azzComputeLoyaltyData(order) {
        const data = this._azzLoyaltyDefault();
        const partner = order?.getPartner?.();
        if (!partner) {
            // No customer -> the display shows the "ask the cashier" invite.
            return data;
        }
        data.hasPartner = true;
        data.partnerName = partner.name || "";

        // 1) Preferred source: pos_loyalty's live per-order statistics. This is
        //    filtered to program_type === "loyalty" and gives us, per programme:
        //    { won, spent, total (projected), balance, name }.
        let stats = [];
        try {
            stats = order.getLoyaltyPoints?.() || [];
        } catch {
            stats = [];
        }
        // Take the primary loyalty programme (prefer one already showing activity).
        const stat =
            stats.find((s) => s?.points && (s.points.balance || s.points.won || s.points.spent)) ||
            stats.find((s) => s?.points) ||
            null;
        if (stat) {
            const p = stat.points;
            data.hasLoyalty = true;
            data.pointsName = p.name || "Points";
            data.balance = this._azzNum(p.balance);
            data.won = this._azzNum(p.won);
            data.spent = this._azzNum(p.spent);
            data.projected = this._azzNum(
                p.total ?? data.balance + data.won - data.spent
            );
            return data;
        }

        // 2) Fallback: the customer has a loyalty card but there is no point change
        //    yet (e.g. an empty cart). Read the balance straight off the card so we
        //    can still greet them with their current points.
        const cards =
            order.models?.["loyalty.card"]?.filter?.(
                (c) =>
                    c.partner_id?.id === partner.id &&
                    c.program_id?.program_type === "loyalty"
            ) || [];
        if (cards.length) {
            const card = cards[0];
            const program = card.program_id;
            data.hasLoyalty = true;
            data.pointsName =
                program?.portal_visible && program?.portal_point_name
                    ? program.portal_point_name
                    : "Points";
            data.balance = this._azzNum(card.points);
            data.projected = data.balance;
        }
        // If we get here with hasLoyalty still false, the customer simply has no
        // loyalty account - the display handles that case cleanly (zero balance).
        return data;
    },

    _azzNum(value) {
        const n = Number(value || 0);
        return Number.isFinite(n) ? n : 0;
    },
});
