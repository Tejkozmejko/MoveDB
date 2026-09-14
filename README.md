# Centric Odoo 19 Custom Addons

This repository contains Centric's custom Odoo 19 applications. The newest
work is a connected workforce-management suite covering employee assignments,
clients, supervisors, work locations, commercial rates, managed-service jobs,
resignations, operational reporting, reminders, and demo data.

## Repository

```bash
git clone --recurse-submodules --branch main git@github.com:centricmt/testing.git
```

The deployment branch is `main`. A pushed commit is not live until its Odoo.sh
build and database upgrade are green.

## Addons in this repository

| Application | Technical name | Version | Purpose |
|---|---|---:|---|
| Centric Employee Changes | `centric_employee_changes` | `19.0.2.4.0` | Workforce assignments, clients, supervisors, rates, movements, reminders, HR tracking, and managed-service scheduling |
| Centric Employee Resignations | `centric_employee_resignation` | `19.0.1.1.0` | Employee/HR resignation intake, departmental review, decisions, follow-up, documents, and offboarding |
| Centric Reports | `centric_reports` | `19.0.1.0.0` | Live operational reports and a daily email digest |
| Centric Workforce Portal | `centric_workforce_portal` | `19.0.3.0.0` | Employee portal: weekly roster signing, geolocated punch in/out, attendance, roster history, and client staffing requests |
| Centric Workforce Portal on the Website | `centric_workforce_portal_website` | `19.0.1.1.0` | Offers the employee and client portals on one chosen website |
| Centric Inventory & Delivery | `centric_delivery_method_customisation` | `19.0.2.11.3` | Delivery methods, lots, backorders, expiry controls, returns, and delivery reporting |
| Centric Sales | `centric_sales_rep_customisation` | `19.0.2.5.7` | Sales-representative security, barcode/catalog tools, customer PO data, price history, and customer analytics |
| Centric Gym | `centric_gym` | `19.0.1.5.0` | Membership cards, kiosk check-in/out, presence, overrides, and visit reporting |
| Centric POS | `centric_pos_customer_display` | `19.0.2.2.0` | Loyalty customer display, survey kiosk mode, and improved POS VAT receipt presentation |

All applications are explicitly installable and use `auto_install = False`.

## Workforce suite

The workforce suite is made of four applications:

```text
Centric Employee Changes
        |
        +--> Centric Employee Resignations
        |            |
        |            +--> Centric Reports
        |
        +--> Centric Workforce Portal
```

Installing `centric_reports` resolves both of its workforce dependencies, but
the recommended production rollout is to install or upgrade them in the order
shown above. `centric_workforce_portal` is independent of the resignation and
reporting branch; it only needs `Centric Employee Changes` and Odoo's
`Attendances` and `Customer Portal`.

`centric_workforce_portal_website` is an optional bridge that can add
**Employee Portal** and **Client Portal** to **one chosen** website's main menu.
It is `auto_install`, so it appears by itself once both the portal and Odoo's
**Website** app are present, and never forces the Website app on a database that
does not have it. It adds nothing to any menu until a site is picked under
Website → Configuration → Settings, so a public site running for another
audience is left alone.

### Clients and supervisors

Contacts can be enabled with Centric-specific roles:

- **Client** makes the contact selectable on employee assignments.
- **Client Service Model** classifies the client as **Full-Time Outsourced**
  or **Managed Services**.
- **Available as Supervisor** makes an OZO person contact selectable as a
  managed-service supervisor.
- A supervisor can use one shared identity across the OZO contact, internal
  user, and employee records. The switch on the administrator's user form is
  the same contact value, so changes made from either screen stay synchronized.
- A Managed Services client company has an **Assigned Supervisor** dropdown,
  limited to eligible people working under its OZO operating company.
- A client's **Assigned Employees** area shows its current employee contacts.
- **Employee History** shows current and previous placements, including the
  client's one-to-five-star employee rating and rating comment.
- **Work Locations** lets HR maintain the client's sites using Odoo's native
  `hr.work.location` model.

Role changes are protected when employees, work locations, jobs, trials,
interviews, or history still depend on the contact. Company and archive guards
prevent active operational records from being left with invalid contacts.

### Employee card and assignments

The employee card supports these assignment fields:

| Area | Behaviour |
|---|---|
| Service Model | `Full-Time Outsourced` or `Managed Services` |
| Client | Required for a current Centric assignment and must use the same service model |
| Supervisor | Required only for Managed Services and selected from supervisor-enabled contacts |
| Work Location | Selected from the current client's locations |
| Availability | Available for Work, Assigned, or Unavailable |
| Job | Uses an existing Odoo job position; demo employee job titles use the same available roles |
| Assignment dates | The current assignment start date is managed by the system |

Changing or removing a client normalises the dependent supervisor, location,
availability, dates, and rates so hidden stale assignment values are not kept.

### Rates and profit

Each employee assignment can store:

- agreed employee rate;
- agreed client rate;
- employee and client overtime rates;
- employee and client public-holiday rates; and
- rate basis: hour, day, month, or year.

The module calculates the base, overtime, and public-holiday profit amount and
margin. Internal HR views can see both sides and the margin. Client-oriented
employee lists intentionally show only the client rates.

### Company movement and ratings

Assignment history is generated automatically. A movement snapshot retains:

- employee and client;
- service model and supervisor;
- work location;
- start and end dates;
- company and currency;
- all base, overtime, and public-holiday rates;
- profit calculations; and
- the client's **Not Rated** state or one-to-five-star rating and comment.

Employees have a **Company Movement** tab and clients have an **Employee
History** tab. Historical identity and rate values are protected from manual
editing. Ratings can be submitted only from **Centric Workforce > Rate
Employees** by an authenticated user whose contact belongs to that client
company and has the **Client Rater** access right. HR users and employees
cannot rate an employee assignment; the submitting user and time are audited.

### Deadlines and reminders

On each employee, HR can enable a contract-expiration reminder, choose the
lead time, and assign the responsible HR user. HR can also create other named
employee deadlines with their own date, reminder lead time, responsible user,
notes, and status.

Daily scheduled actions create one Odoo activity per due reminder, avoid
duplicates, and clean up module-owned activities when a reminder no longer
applies or the responsible user loses the required access.

### Trials, interviews, and HR issues

The workforce application includes operational registers for:

- employee trials: Planned, In Progress, Completed, or Cancelled;
- interviews: Scheduled, Completed, or Cancelled; and
- HR issues: Open, In Progress, Waiting, Resolved, or Cancelled.

These are the live source records used by Centric Reports. Open operational
records must be handled explicitly before accepted resignation offboarding.

### Managed-service calendar and jobs

The **Managed-Service Schedule** is a Field Service-style calendar for
Managed Services clients only.

- Select a client in the search panel to switch to that client's calendar.
- Jobs store the client, supervisor, assigned employees, work location,
  planned start/end, status, and notes.
- Only Managed Services employees currently assigned to the selected client,
  supervisor, and company can be added. Full-Time Outsourced employees are
  rejected by both the screen and the server, including jobs launched from a
  client contact.
- Supervisor contacts linked to an internal user can create and update jobs
  for their own current teams.
- HR can manage all jobs in allowed companies.
- Job history cannot be casually deleted, and assignment changes are blocked
  while affected jobs are planned or in progress.

This workflow is deliberately unavailable for Full-Time Outsourced clients.

## Resignation workflow

Employees can open their own resignation through self-service, while HR can
open a case for any employee in an allowed company.

```text
Draft
  -> Submitted
  -> Information Gathering
  -> Under Review
  -> Decision Pending
  -> Follow-Up
  -> Concluded
```

Cases can also be cancelled, and HR administrators can reopen a concluded or
cancelled case with a fully audited reason, user, date, and reopen count.

### Information captured

- resignation details and dates;
- proposed and confirmed last working date;
- immutable employee, client, service, supervisor, job, department, and
  company snapshots;
- whether the client was notified, including the email address, notes, sender,
  and date;
- OZO main-office attendance status, schedule, officer, date, and notes;
- HR, Operations, Legal, and Finance reviews;
- manually entered contract-breach applicability, reason, clause, proposed
  amount, and approved amount;
- management's final decision and date;
- department-owned follow-up actions, owners, deadlines, completion stamps,
  notes, and attachments;
- original resignation correspondence;
- secured internal correspondence;
- uploaded reports; and
- final-decision documents.

### Department workflow and SLA configuration

Per company, configure the default HR, Operations, Legal, Finance, and
Management departments under:

```text
Employees -> Configuration -> Settings -> Centric Resignation Workflow
```

Each configured department's employee manager becomes its default head,
reviewer, owner, and overdue escalation contact in that company. Separate
calendar-day SLAs are available for Submitted, Information Gathering,
Department Review, Management Decision, and Follow-Up stages.

The daily escalation job creates non-duplicating overdue activities for case
owners, relevant department heads, and follow-up owners.

### Arriving from Indigo — the preview

OZO tracks resignations in Microsoft Lists today and wants them to arrive from
Indigo. **That connection is not built.** What exists is the screen it will use,
wired to a bundled sample feed:

```text
Centric Resignations -> Import from Indigo (Preview)
```

It lists leavers, matches them to real employees in the database, and opens a
draft case for the ones selected. It is written as the real thing minus one
method — `_centric_fetch_feed` is the only place that knows where rows come
from, so replacing its body with an HTTP call to Indigo turns the preview into
the integration without the wizard, the matching, the view or the tests
changing.

Two things it deliberately does not fake, because a stub that is demonstrated
is exactly the kind of thing that quietly becomes production:

* **It never claims to have reached Indigo.** The wizard carries a warning
  banner, the source field says the feed is a sample, and every case it opens is
  stamped as sample data in both its reason text and its chatter.
* **It shows the rows it cannot place.** Matching leavers to employee records is
  the part of the real integration that will need actual rules, so the feed
  includes leavers this database has no employee for. They are listed, marked
  **No matching employee** and refused for import rather than guessed at.

`centric_indigo_ref` on the case stores the reference the row carried in Indigo.
It is the external key an import needs to stay idempotent: re-reading the feed
recognises a leaver it has already opened a case for and does not offer it
again.

### Client email and offboarding

The **Notify Client by Email** action uses the included mail template. The case
is stamped as notified only after a successful send.

An accepted case can be concluded only on or after the confirmed last working
date and after blocking jobs, trials, interviews, HR issues, deadlines, and
follow-ups have been resolved. Conclusion writes Odoo's departure data, closes
the current assignment history, makes the employee unavailable, and archives
the employee. Rejected or withdrawn cases close without offboarding.

### Resignation access model

- Employees can create and maintain only their own draft intake.
- Employees can continue reading their case without seeing internal review,
  breach, internal-document, or follow-up data.
- HR Officers manage company cases.
- Operations, Legal, Finance, and Management reviewers can update only their
  server-enforced section.
- A configured department head receives company-scoped access for that
  department without being granted a global reviewer group.
- Follow-up owners can update only work assigned to them.
- HR Administrators control cancellation, reopening, and permitted deletion.
- Global multi-company rules still apply to every access route.

## Centric Workforce Portal

The portal puts the roster in the employee's hand and staffing requests in the
client's. Full detail lives in
[`centric_workforce_portal/README.md`](centric_workforce_portal/README.md).

### Getting to it

The portal lives on the company's own Odoo address:

| Address | Who |
|---|---|
| `/my/shifts` | Employees: roster, punching, attendance, history, profile |
| `/my/staffing-requests` | Clients: raising and following staffing requests |
| `/my/home` | Either: the portal home, with a card for whichever applies |

With the **Website** app installed, the portal pages render inside the site's
own header, footer and theme. `centric_workforce_portal_website` can add
**Employee Portal** and **Client Portal** to the main menu of **one chosen**
site: tick **Centric Workforce Portal** under Website → Configuration →
Settings for that site. An anonymous visitor who clicks one is sent to the
login and back again, so the menu entry doubles as the front door for staff.

### Employees on the website

Employees sign in as **portal** users, which do not consume a user licence.
**Grant Portal Access** on the employee card creates the account from the work
email, links it in **Portal Account**, and emails the employee Odoo's standard
`/web/reset_password` invitation so they set their own password. No password is
ever sent to them and none is chosen on their behalf.

Signed in, they get a five-tab portal, built as a sticky bottom bar on a phone:

- **Home** - today's shift with the punch button, tiles for hours worked, hours
  rostered and roster status, the next shift, and the week with a day-detail
  panel;
- **My Roster** - the week to enter, upload, submit and sign;
- **Attendance** - the week's punches against what was rostered;
- **Roster History** - every signed version, amendments included; and
- **My Profile** - their placement details and their own portal language.

### Weekly rosters and signatures

`centric.roster` is one employee's week. Centric can enter it from the client,
or the employee can enter the hours they were given and upload the client's own
roster document. It runs `Draft -> Awaiting Signature -> Signed`, and signing
locks the version, publishes that week's shifts and emails the signed roster to
the client.

The employee **draws** their signature on the portal rather than typing a name:
a typed name is self-asserted text, and this record travels on to the client.
The mark is stored on the roster and attached to the client's email as a PNG,
because Gmail and Outlook both strip `data:` images out of message bodies. The
signatory name is taken from the authenticated employee, never from the form.

HR can still record a signature from the backend for an employee who signed on
paper, so the image stays optional on the model; it is the portal route that
insists on a drawing.

A signed week is never edited. Amending copies it into a new version that has to
be signed again; the old one becomes Superseded and stays in Roster History.
Only one version of a week can be the signed one. A day that has already been
punched keeps its shift untouched, because the roster records what was agreed
while attendance records what happened.

### Shifts

`centric.shift` is the individual shift record shared by both service models. It carries
the employee, client, role, work location, start and end, and runs
`Draft -> Published -> Confirmed -> Done`. A shift reaches the employee's
calendar and becomes punchable at **Published**. The same employee cannot hold
two live shifts over one period, and a shift that has been punched can no
longer be cancelled or deleted.

`centric.client.job` is unchanged and still records the supervisor's
managed-service jobs.

### Punching with geolocation

Punches are ordinary `hr.attendance` records, so they feed Odoo's existing
attendance reporting. Coordinates land in Odoo's native latitude and longitude
fields; the module adds the shift link, the distance from the work location,
and an **Off Site** flag.

Location never blocks a punch. A refused permission, a missing fix or a
position far from the site are all recorded and flagged for review rather than
leaving an employee unable to start their shift. Punching a shift that is not
yours, is still a draft, or is days from its window is refused.

Work locations gain **Site Coordinates** and an **Accepted Radius (m)**,
defaulting to 250 m. A site without coordinates records punches with no
distance.

### Client timesheets and sign-off

`centric.timesheet` is one week of one employee at one client, built from what
was rostered against what was actually punched. The client reviews it at
`/my/timesheets` and either approves it with their name or disputes it with a
reason. An approved week is immutable, because it is what OZO bills from.
`/my/employees` shows the client their placed staff with role, star rating and
who is free on a given day.

Worked hours follow `hr.attendance`, which **deducts the employee's scheduled
lunch break** — an 08:00 to 16:00 punch bills seven hours, not eight. The
deduction comes from the working schedule on the employee record, so staff whose
shift has no midday break need a schedule that says so.

### Client staffing requests

Clients raise `centric.staffing.request` from `/my/staffing-requests`: position,
number of employees, start and end, work location and requirements. The desk
screens each one, and approving it creates one open published shift per
employee requested, ready to be allocated from **Portal -> Open Shifts**.
Rejection requires a reason, which the client sees on their own page.

### Portal access model

- An employee reads only their own published, confirmed and done shifts, and
  every version of their own weekly rosters.
- A client contact reads every request raised for their own company.
- HR owns both models; other internal users have no access to either.
- Punch review sits behind the Attendances officer group, which is what grants
  access to `hr.attendance` in the first place.
- Global multi-company rules apply to every access route, and the portal record
  rules match stored fields rather than traversing employee data a portal user
  cannot read.

The roster is HR-owned because a shift names a private `hr.employee`, readable
in Odoo 19 only by HR. Supervisors keep scheduling their own teams through
`centric.client.job`, which is built on the public employee model for that
reason.

## Centric Reports

Centric Reports reads the live source models; it does not copy records into a
second reporting table.

### Primary reports

The four requested instant reports are:

1. Employees currently available for work.
2. Employees undergoing trials.
3. Employees with interviews scheduled.
4. Employees with pending HR issues.

The application also provides:

- open resignation cases;
- overdue resignation follow-up actions; and
- confirmed or proposed last working dates due in the next 30 days.

Every report opens as a normal Odoo list with search, grouping, export,
drill-down, and the source model's access rules.

### Daily email digest

An HR Manager configures one digest per company under:

```text
Centric Reports -> Configuration -> Daily Email Settings
```

Configuration includes enable/disable, company, local sending hour, timezone,
internal users, extra contact recipients, and whether empty sections appear.
Empty sections are included by default so all four primary reports appear in
the daily email.

An hourly scheduler checks company-local time. A database row lock and the
last-sent date prevent duplicate daily delivery. Missed sends retry later that
day, and failed delivery is logged without falsely marking the digest sent.

## Demo workforce

With demo data enabled, `centric_employee_changes` creates 25 sample workforce
employees plus four internal supervisor identities:

- 13 Managed Services employees;
- 12 Full-Time Outsourced employees;
- six clients;
- four supervisors, each represented by one shared OZO contact, internal user,
  and employee record;
- eight client work locations; and
- seven Odoo job positions: six used consistently by the workforce employees
  and one **Managed Services Supervisor** position.

The four supervisor users are Settings administrators and HR administrators in
the main company for testing. They are not Client Raters and have no password
stored in the repository. The workforce employees are distributed between
different clients and supervisors, and all example accounts use reserved
`.test` email addresses. Odoo normally does not load demo data into a
production database.

## Installation

1. Put this repository on the Odoo 19 addons path.
2. Restart Odoo.
3. Open **Apps** and run **Update Apps List**.
4. Install or upgrade `Centric Employee Changes`.
5. Install `Centric Employee Resignations`.
6. Install `Centric Reports`.
7. Install `Centric Workforce Portal` to open the employee and client portal
   pages.
8. Configure contact roles, department heads, SLAs, reminder owners, and the
   daily digest for each company.
9. For the portal: set the coordinates and accepted radius on each work
   location, then grant portal access to the employees who need it from their
   employee card.

All four workforce modules have `auto_install = False`; a successful code
build makes them available but does not by itself install a new application.

### Upgrade from Centric Employee Changes 19.0.1

The `19.0.2.0.0` migration preserves existing assignments instead of guessing
or deleting production data. It:

- marks every legacy assigned employee for explicit HR review;
- classifies a legacy client automatically only when all its assigned
  employees use one unambiguous service model;
- marks mixed or incomplete client classifications for review;
- sets assigned availability and an initial assignment date without applying
  stricter new-record validation to old records; and
- seeds employee/client movement history, including archived employees.

Legacy rates default to zero and must be reviewed by HR. Existing native work
locations and archived contacts are preserved for deliberate correction rather
than causing the database upgrade to fail.

### Supervisor identities in 19.0.2.4.0

The `19.0.2.4.0` upgrade provisions each active, structurally valid OZO
supervisor contact as the same linked internal user and employee. Existing
linked records are reused, passwords are not created, and invitation emails are
not sent automatically. An administrator must use Odoo's normal invitation or
password-reset flow when the account is ready to use.

As requested for the initial rollout, these users temporarily receive the same
installed-application access groups as Odoo's main Administrator and access to
all active Odoo companies. The **Client Rater** group is explicitly excluded,
so a supervisor still cannot rate an employee's work. This is intentionally
broad access and should be reviewed and reduced after the operational roles are
finalized. Turning off **Available as Supervisor** does not delete the employee
or user or silently revoke independently assigned rights; active supervisor
assignments must be reassigned before Odoo permits the switch to be disabled.

## Validation

The workforce suite has automated coverage for assignment constraints,
history, rates, reminders, managed jobs, security, resignation workflow,
offboarding, reports, daily email behaviour, and demo data.

A representative clean-install gate is:

```bash
odoo-bin -d centric_test \
  -i centric_reports \
  --with-demo \
  --test-enable \
  --test-tags=/centric_employee_changes,/centric_employee_resignation,/centric_reports \
  --stop-after-init
```

Production changes also require a baseline-to-current database-upgrade test;
fresh installation alone does not exercise versioned migration scripts.

## Technical model reference

| Area | Model |
|---|---|
| Employee | `hr.employee` |
| Public operational employee fields | `hr.employee.public` |
| Client/supervisor contact | `res.partner` |
| Client work location | `hr.work.location` |
| Assignment movement | `centric.employee.assignment.history` |
| Employee deadline | `centric.employee.deadline` |
| Trial | `centric.employee.trial` |
| Interview | `centric.employee.interview` |
| HR issue | `centric.hr.issue` |
| Managed-service job | `centric.client.job` |
| Resignation case | `centric.employee.resignation` |
| Resignation follow-up | `centric.employee.resignation.followup` |
| Secured resignation document | `centric.employee.resignation.document` |
| Daily report configuration | `centric.report.digest.config` |
| Weekly roster | `centric.roster` |
| Weekly roster day | `centric.roster.line` |
| Roster shift | `centric.shift` |
| Client staffing request | `centric.staffing.request` |
| Punch in/out | `hr.attendance` |

## Detailed module documentation

- [`centric_employee_changes/README.md`](centric_employee_changes/README.md)
- [`centric_employee_resignation/README.md`](centric_employee_resignation/README.md)
- [`centric_reports/README.md`](centric_reports/README.md)
- [`centric_workforce_portal/README.md`](centric_workforce_portal/README.md)
- [`centric_workforce_portal_website/README.md`](centric_workforce_portal_website/README.md)
- [`centric_ozo_website/README.md`](centric_ozo_website/README.md)
- [`centric_pos_customer_display/README.md`](centric_pos_customer_display/README.md)
