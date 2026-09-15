{
    "name": "Centric Helpdesk Timesheet Rounding",
    "summary": "Minimum time and round-up per Helpdesk team, separate from Field Service.",
    "description": "Odoo's Time Rounding setting is one database-wide pair. Centric "
                   "Timesheet Rounding already gives Field Service its own pair; this "
                   "module gives every Helpdesk team its own Minimum Time and Round Up, "
                   "set on the team form under its Timesheets option.\n\n"
                   "The team's values apply to every timesheet line logged on one of its "
                   "tickets - timer or typed in by hand - when the line is created or "
                   "changed. A team left at 0 / 0 keeps the database-wide setting. Lines "
                   "that are validated or invoiced are never touched.",
    "version": "19.0.1.0.0",
    "category": "Services/Helpdesk",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "helpdesk_timesheet",
        "centric_timesheet_rounding",
    ],
    "data": [
        "views/helpdesk_team_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
