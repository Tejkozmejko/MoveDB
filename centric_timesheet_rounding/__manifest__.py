{
    "name": "Centric Timesheet Rounding",
    "summary": "Separate timer rounding for Field Service, configurable in Timesheets settings.",
    "description": "The native Time Rounding setting (minimal duration and round up) is a "
                   "single database-wide pair shared by every app that uses the timesheet "
                   "timer -- it is not scoped per company, per project or per team. This "
                   "module adds a second pair that applies only to timers started on Field "
                   "Service tasks, so Field Service can bill a 30 minute minimum while "
                   "Helpdesk and Project keep the global 15 minutes.\n\n"
                   "Both pairs are editable under Timesheets > Configuration > Settings. "
                   "Leaving a Field Service value at 0 falls back to the global setting.\n\n"
                   "Like the native setting, this affects the timer only: timesheet lines "
                   "typed in by hand are left exactly as entered.",
    "version": "19.0.1.0.0",
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
