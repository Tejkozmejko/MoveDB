# Centric Gym (`centric_gym_core`)

The foundation of the Centric Gym Management suite for Odoo 19. A gym member
is an ordinary **contact**. There is no separate member table.

This module is unrelated to the older `centric_gym` addon and does not depend on
it. The two are never installed on the same database.

## What it adds

| Area | Details |
|---|---|
| Member state | *Not a member → Waiting for waiver → Member → Former member* on every contact. Only a gym manager or the system can change it, so a plain **New** in Contacts never creates a member. |
| Member PIN | A unique 4-digit PIN, handed out automatically when a contact becomes a member. Easy-to-guess PINs (0000, 1234, …) are never handed out. |
| PIN history | Every assignment (who, from, until, why released) in *Gym → Configuration → PIN History*. |
| PIN reuse | Nightly, PINs of members inactive for *N* months are released (off until enabled). A released PIN waits *M* months before it goes to someone else. A returning member gets their own PIN back if it is still free. |
| Membership card | Barcode `042` + PIN (6 digits) + card number (2 digits), e.g. `04200482101`. `042` is Odoo's standard customer prefix, so scanning the card in the Point of Sale selects the member. **Replace Lost Card** bumps the card number; the old card stops working and the PIN stays. A reused PIN carries on the previous holder's card numbers, so an old card never matches the new holder. Printable CR80 card. |
| Photo | **Take Photo** on the Gym tab uses the desk webcam (https only). |
| Personal | Date of birth, age, minor flag (adult age is a setting), parent/guardian, emergency contact. |
| Health | `gym.member.health`, readable only by **Gym Health Data**. Reception and managers see a *Health Alert* flag, never the details. Health records have no chatter, so nothing leaks into the contact's history. |
| Locations | `gym.location` with timezone, automatic check-out time (default 120 min) and capacity. |

## Check-in

- **Gym → Reception:**
  - Scan a member card, type a PIN, or search a name.
  - A member with a valid membership is checked in at once. Anyone else is refused, with the reason (not a member, waiver not signed, blocked, no/expired/suspended membership…), and the refusal is recorded.
  - Managers can **Override** a refusal; the reason is kept. **Undo** removes your own check-in from the last 5 minutes.
  - The right-hand panel shows who is inside, with a headcount against the location's capacity.
- **Automatic check-out:** after the location's time (120 minutes by default), at the planned time rather than when the job happens to run. A job runs every 5 minutes, and each check-in also schedules one at its own check-out time.
- **Gym → Inside Now** and **Gym → Reporting:**
  - **Check-Ins**
  - **Who Was Inside?**: everyone inside at any moment of a period, with phone and email, for contact tracing.
  - **Attendance Analysis**: busiest hours and days, in the location's timezone.
- **Retention:** check-ins older than **Keep Check-Ins For** (default 6 months) are deleted nightly.
- **Blocked:** a manager can block a member, with a reason. Check-in is then refused whatever the membership says.
- **Memberships:** whether a membership is valid comes from **Centric Gym Memberships** (Subscriptions). Without that module, every member is refused with "No membership".

## Access groups

| Group | Can |
|---|---|
| Gym / Reception | Gym app, reception screen, check-in and check-out, members, edit contact details (includes *Contacts → Creation*), print and replace cards |
| Gym / Manager | + override refusals, block members, reports, make members, set or release PINs, PIN history |
| Gym / Administrator | + locations, Gym settings (settings also need *Administration → Settings*) |
| Gym Health Data / Health Data | Read and edit health records. Separate on purpose; no gym level includes it. |

## Settings (*Gym → Configuration → Settings*)

- **PINs in Use**: warns when more than 90% of PINs are taken.
- **Reuse PINs**: nightly release of inactive members' PINs, after *Inactive For* months (default 12). **Leave this off until memberships and check-ins are recorded in Odoo**, otherwise every imported member looks inactive.
- **Wait Before Reuse**: default 12 months.
- **Adult From Age**: default 18.

## Importing existing members

Import contacts as a Gym **Manager** with a `Member PIN` (`gym_pin`) column.

- Any contact given a PIN becomes a member.
- PINs that a spreadsheet shortened (`427`) are padded back to `0427`.
- Duplicate PINs are refused row by row.
- The import sets the contact's barcode to the new card barcode.

## Tests

```
python -m odoo -d <db> -i centric_gym_core --test-enable --test-tags /centric_gym_core --stop-after-init
```

## Coming in later phases

- Waiver and agreements with Sign
- POS sales and renewals
- The member tablet
