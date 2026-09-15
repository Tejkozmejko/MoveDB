{
    "name": "Centric Timesheet Rounding",
    "summary": "Separate timer rounding for Field Service, configurable in Timesheets settings.",
    "description": "The native Time Rounding setting (minimal duration and round up) is a "
                   "single database-wide pair shared by every app that uses the timesheet "
                   "timer -- it is not scoped per company, per project or per team. This "
                   "module adds a second pair that applies only to Field Service timesheet "
                   "lines, so Field Service can bill a 30 minute minimum while Helpdesk and "
                   "Project keep the global 15 minutes.\n\n"
                   "Both pairs are editable under Timesheets > Configuration > Settings. "
                   "Leaving a Field Service value at 0 falls back to the global setting.\n\n"
                   "Unlike the native setting, which only applies to the timer, this is "
                   "applied on create and write, so a Field Service line reaches the "
                   "minimum however it was entered -- timer or typed in by hand. Lines that "
                   "are already validated or invoiced are never touched.\n\n"
                   "The Confirm Time Spent dialog shown when a timer is stopped is also "
                   "corrected, so the duration it offers is the duration that will be "
                   "stored rather than the global one.",
    "version": "19.0.1.3.2",
    "category": "Services/Timesheets",
    "author": "Centric",
    "license": "LGPL-3",
    "depends": [
        "timesheet_grid",
        "industry_fsm",
    ],
    "data": [
        "data/ir_config_parameter.xml",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
