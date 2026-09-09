# -*- coding: utf-8 -*-
"""Work centres for the plant, keyed by the code the BoM operations reference.

Three of these - the flexo press, the slitter and the granulator - already
exist in the live database; they were created by hand during setup. The hook
matches on ``code`` and leaves an existing work centre completely alone, so
installing this module will not overwrite the rates or OEE targets someone has
since tuned. Only a missing work centre is created, which is what makes a
rebuilt or freshly seeded database line up with the live one.
"""

# code -> mrp.workcenter values
WORKCENTERS = {
    "TP-EXTRUDE": {
        "name": "Blown Film Extrusion Line",
        "costs_hour": 48.00,
        "time_efficiency": 90.0,
        "time_start": 60.0,
        "time_stop": 30.0,
        "oee_target": 85.0,
    },
    "TP-FLEXO6": {
        "name": "Flexo Printing Press (6 Colour)",
        "costs_hour": 65.00,
        "time_efficiency": 88.0,
        "time_start": 45.0,
        "time_stop": 30.0,
        "oee_target": 80.0,
    },
    "TP-SLIT": {
        "name": "Slitting & Rewinding",
        "costs_hour": 22.00,
        "time_efficiency": 92.0,
        "time_start": 20.0,
        "time_stop": 10.0,
        "oee_target": 85.0,
    },
    # The bag line is where the plant stops weighing and starts counting: film
    # goes in by the reel, bags come off in thousands. Its rate is quoted per
    # hour like the rest, but the BoMs that use it are sized in bags, so the
    # cost it contributes is divided across a run of BAG_RUN_QTY.
    "TP-BAGLINE": {
        "name": "Bag Making & Sealing Line",
        "costs_hour": 26.00,
        "time_efficiency": 87.0,
        "time_start": 30.0,
        "time_stop": 20.0,
        "oee_target": 82.0,
    },
    "TP-REGRIND": {
        "name": "Regrind / Granulator",
        "costs_hour": 18.00,
        "time_efficiency": 90.0,
        "time_start": 15.0,
        "time_stop": 10.0,
        "oee_target": 85.0,
    },
}
