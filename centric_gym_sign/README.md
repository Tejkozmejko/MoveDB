# Centric Gym Agreements (`centric_gym_sign`)

New members sign the gym waiver with **Odoo Sign** before they become members.
Needs Odoo Enterprise (`sign`).

## Setup

1. **Sign → New**: upload the gym's waiver PDF, add the fields to fill (e.g. Name, Signature, Date) for **one** signer role (e.g. "Customer"), and save the template.
2. **Gym → Configuration → Agreement Templates → New**: name it, choose **Used For = Waiver**, set a version (e.g. `1`) and pick the Sign template.
3. Do the same with **Used For = Membership agreement** for the POS membership sale.
4. **Existing members** who signed on paper: import or set **Paper Waiver Version** (e.g. `1`) on them. Only a gym manager can set it.

## New member

**Gym → New Member**, or **New Gym Member** on the Members list:

1. **Details:** name, email, phone, date of birth, address, emergency contact, and photo (webcam). A minor needs a parent or guardian.
2. **Send Waiver:** Odoo creates the contact as *Waiting for waiver* and creates the Sign request (Odoo emails it).
   - **Open Signing Page** shows it on this screen, or drag it to the customer screen.
   - The member signs, then reception clicks **Check Signature**.
3. **Done:** the contact becomes a member and gets a PIN. **Print Card**.

A waiver signed later from the email is picked up within 5 minutes.

## Rules

- **Check-in** is refused ("Waiver not signed") until the member has signed the **current** waiver template, or has a matching Paper Waiver Version.
- **New wording:** duplicate the template with a new version and archive the old one. Check-in then says "New waiver version not signed" until the member signs again (**Send Waiver** on the contact).
- **Changing a template:** once documents have been signed with it, its version, Sign template and type can't be changed.
- **Signer:** Odoo Sign requires a signer email address. A minor's waiver is signed by their parent or guardian.
- **Agreements** (Gym → Agreements, managers) keep the member, the signer, the version and the signing time. Managers can **Download Signed PDF** (without needing Sign rights) and **Void** an agreement.

## Verified behaviour (live Odoo 19 Enterprise, 2026-09-17)

- **Emails:** creating a Sign request emails the signer, and needs a valid email address.
- **Signing link:** `/sign/document/<request>/<signer token>` opens without a login and can be shown inside another page (no frame-blocking headers).
- **After signing:** the request becomes `signed` and the signer `completed`. The signed PDF and certificate are attached, and the signing time is logged.
