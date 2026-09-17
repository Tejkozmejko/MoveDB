# Centric Gym Memberships (`centric_gym_membership`)

Gym memberships are Odoo **Subscriptions**. This module connects them to
Centric Gym (`centric_gym_core`); a membership's status is never stored twice.

## Setup

1. **Subscriptions → Configuration → Recurring Plans:** one plan per membership length, e.g. 1 month, 3 months, 6 months, 1 year.
2. **Gym → Configuration → Membership Products → New**, e.g. "1 Month Membership":
   - a service product with **Subscriptions** and **Gym Membership** ticked
   - a recurring price on the matching plan
3. Sell one subscription per paid period, with an **End Date**, so it never bills again. The POS module does this for you.

## Membership status

Computed from the member's confirmed gym subscriptions every time it is read:

| Subscriptions say | Status | Check-in |
|---|---|---|
| In progress, or renewed, and today is between start and end | Active | ✔ |
| Paused, and today is between start and end | Suspended | ✖ |
| Only future subscriptions | Not started yet | ✖ |
| Last one ended | Expired | ✖ |
| Closed before its end date, or cancelled | Cancelled | ✖ |
| None | No membership | ✖ |

**Membership Ends** includes renewals that start the day after the current membership ends.

## What it adds

- **Contact form:** the member's Gym tab shows the status, the end date, and the current and next membership (current and next are visible to sales users only). A **Memberships** smart button lists them.
- **Members list:** a status column and filters (Active Membership, Expired, Suspended, No Membership).
- **Check-ins:** each check-in keeps the subscription that was running.
- **PIN reuse:** the membership end date counts as activity.
- **Menus:**
  - **Gym → Memberships:** Subscriptions' own list, gym memberships only.
  - **Gym → Configuration → Membership Products**

## Verified behaviour (live Odoo 19 Enterprise, 2026-09-17)

- A subscription paid through POS (via `pos_sale`) counts as invoiced for its period. Its next invoice date moves past the end date.
- The recurring-invoice job then creates **no second invoice**, and closes the subscription (Churned) after the end date.

## Tests

This module needs Odoo Enterprise (`sale_subscription`), so it can't be tested
on the local Community sandbox. It was checked on the trial database instead.
