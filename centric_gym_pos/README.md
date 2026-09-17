# Centric Gym POS (`centric_gym_pos`)

Sell and renew gym memberships in the **Point of Sale**, with the membership
agreement signed on the **customer screen**. Members also check in there with
their **PIN**.

Needs Centric Gym Memberships and Centric Gym Agreements (Odoo Enterprise).

## Setup

1. **Gym → Configuration → Agreement Templates:** an active template with **Used For = Membership agreement**.
2. **Gym → Configuration → Membership Products:** each product is available in POS, with a recurring price on the plan matching its length.
3. **Point of Sale → Configuration → Settings → PoS Interface → Gym Location:** the gym this POS (and its customer screen) belongs to.
4. **Customer screen:** open it from the POS menu, either on a second screen of the reception PC or on a tablet by scanning the QR code.

## Selling or renewing a membership

1. Tap the membership product. The POS asks for a customer if there is none.
   - The customer must already be a member with a signed waiver (**Gym → New Member**).
2. Odoo creates the subscription quotation and sends the membership agreement.
   - **Start:** today, or for a renewal, the day after the current membership ends.
   - **End:** start + the product's plan − 1 day.
3. The agreement appears full screen on the **customer screen**. The member (or a minor's guardian) signs it there. The cashier can also use **Open Signing Page Here**.
4. Once it is signed, the subscription is confirmed and added to the order. **Payment** is refused while any membership in the order is unsigned.
5. After payment, the POS order is linked to the agreement, and the membership is active for its period.

**If the sale goes wrong:**
- **Cancel Sale** (or 12 hours without payment) cancels the quotation and voids its agreement. An unpaid membership never counts as active.
- A **refund** of a membership creates a to-do on the subscription for a manager to close it.

## Customer screen

| Situation | Screen |
|---|---|
| Agreement to sign | The Sign page, full screen |
| Just signed | "Thank you!" |
| Check-in at reception or by PIN | Name, photo, "Membership: Active / Expired / …", "Welcome!" or "Please speak to reception" (6 s) |
| Nothing going on | A **Check in** button that opens a PIN pad |

- **What members see:** never health information, block reasons or notes.
- **Wrong PINs:** after 8 wrong PINs in 5 minutes, the pad asks the member to go to reception.
- **Screen on another device:** reception check-ins reach it through the server. A screen in the same browser gets them directly.

## Verified behaviour (live Odoo 19 Enterprise, 2026-09-17)

- **No double billing:** paying a confirmed subscription through `pos_sale` counts as invoiced for the period, and no second invoice is created later.
- **Embedding:** the Sign page can be shown inside the customer screen (no frame-blocking headers).
