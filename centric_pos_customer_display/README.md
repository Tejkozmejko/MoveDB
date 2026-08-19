# Farm Meats POS Customer Display (Loyalty)

A small, isolated Odoo 19 module that turns the Point of Sale **customer-facing
second screen** (the 7", 1024×600 HDMI display) into a clean, loyalty-focused
display.

It does **not** replace or fork `point_of_sale`. It patches the standard
customer-display bundle and the POS customer-display data adapter using OWL
patches and QWeb template inheritance, so the cashier interface is completely
untouched.

## What it shows

| Situation | Display |
|-----------|---------|
| No customer selected | *"Want to earn loyalty points? Ask the cashier to add or select your account."* |
| Customer selected (loyalty account) | Customer name, **current points in very large text**, points *earning now* (+won), points *redeeming* (−spent) if any, and the **projected new balance** |
| Customer selected, no loyalty account / zero points | Name + a clean `0` and a gentle prompt to join |
| After payment | *"Thank you!"* with the **updated points balance** kept on screen |

A small company logo sits in the top-left; the order total is shown small at the
bottom so loyalty stays the focus.

## Where the numbers come from (nothing hardcoded)

All values are read from the **actual configured loyalty programme(s)**. The
POS-side adapter reuses `pos_loyalty`'s own `order.getLoyaltyPoints()`, which
computes points from the order's `couponPointChanges` and reward lines against
the installed `loyalty.program` / `loyalty.rule` / `loyalty.card` records:

- **Current points (`balance`)** – points on the customer's `loyalty.card` before this order.
- **Earning now (`won`)** – points the current order earns, per the programme's rules (per-order / per-unit / per-money).
- **Redeeming (`spent`)** – points consumed by reward lines in the order.
- **Projected new balance (`total`)** – `balance + won − spent`.

If the customer has a card but no point change yet (e.g. empty cart), the balance
is read straight off the `loyalty.card`. No programme ids, earning rates or point
values are hardcoded anywhere.

## Self-service account creation (on the display)

When no customer is selected, the display shows a **Create an account** button.
Because the display has no POS models or write access, tapping it opens a small
popup (Name / Phone / Email) that POSTs to a public, token-validated controller:

```
Display popup ──POST /centric_pos_customer_display/create_partner──►  controller
  (name/phone/email + config_id, access_token, device_uuid)               │
                                                                          │ validates access_token
                                                                          │ creates res.partner (sudo, whitelisted fields)
                                                                          │ config._notify("AZZ_NEW_PARTNER-<device_uuid>")
                                                                          ▼
Cashier POS  ◄──────────── bus (pos.config access_token channel) ─────────┘
  loads the partner, setPartner() on the live order, updateRewards()
  → re-broadcasts → the display now shows the customer + loyalty panel
```

The controller re-checks the `pos.config.access_token` (the same secret the
display page itself is trusted with) and only ever writes `name`, `phone` and
`email`. No POS/ORM access is exposed to the public display page directly.

## Architecture

The POS runs in two windows that share data over a `BroadcastChannel` + the bus:

```
Cashier POS window                         Customer display window (2nd screen)
------------------                         ------------------------------------
CustomerDisplayPosAdapter.formatOrderData  CustomerDisplay (OWL component)
  + _azzComputeLoyaltyData(order)   ─────►    reads order.loyalty from payload
  (reads getLoyaltyPoints, tracked            renders the loyalty layout
   by the reactive dispatch effect)
```

Because the loyalty state is read inside the POS's reactive dispatch effect, the
screen refreshes **immediately** whenever the customer changes, products/quantities
change, the reward calculation changes, or the order is paid.

### Files

| File | Bundle | Role |
|------|--------|------|
| `static/src/pos/loyalty_customer_display_adapter.js` | `point_of_sale._assets_pos` | Patches `formatOrderData` to compute + attach the loyalty payload |
| `static/src/customer_display/customer_display.js` | `point_of_sale.customer_display_assets` | Adds `loyalty` accessor + `formatPoints` helper |
| `static/src/customer_display/customer_display.xml` | `point_of_sale.customer_display_assets` | Replaces the `.o_customer_display` layout (extension inherit) |
| `static/src/customer_display/customer_display.scss` | `point_of_sale.customer_display_assets` | Styling tuned for 1024×600 landscape |

## Install & test

1. **Prerequisites:** `point_of_sale` and `pos_loyalty` installed, plus at least
   one **Loyalty** programme configured (Point of Sale → Products → Loyalty
   Programs, program type *Loyalty Cards*) with an earning rule.
2. Copy this module into the addons path (it already lives in this repo) and
   restart Odoo, then **Apps → Update Apps List → install “Farm Meats POS
   Customer Display (Loyalty)”**.
3. In the POS config, enable the **Customer Display** (the second-screen option)
   so the display route is available.
4. Open a POS session, then open the customer display (the local second-screen
   window / the "Customer Display" link).
5. Verify:
   - Empty, no customer → invite message.
   - Select a customer with a loyalty card → name + big current balance.
   - Add products → "Earning now" and "New balance" update live.
   - Add a reward that spends points → "Redeeming" appears and the projection drops.
   - Pay the order → "Thank you!" with the updated balance.
   - Select a customer with no loyalty card → clean `0` state.

## Notes

- Assets-only module: no Python models, no new access rules or data files.
- If multiple *loyalty*-type programmes apply, the primary one (the one already
  showing activity, else the first) is displayed.
