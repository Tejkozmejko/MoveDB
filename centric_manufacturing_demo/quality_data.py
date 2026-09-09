# -*- coding: utf-8 -*-
"""P7.1 - quality control checkpoints.

The four checks below are the ones the plant already does and writes on a
clipboard: gauge on the extruder, colour against the approved proof on the
press, seal strength off the bag line, and an incoming check on resin before it
is tipped into a silo. Putting them on ``quality.point`` is what turns them
from a clipboard into a record attached to the works order, so a customer
complaint six months later can be traced to the shift that made the reel.

Each checkpoint is one of three test types:

* ``passfail`` - an inspector's judgement against a written instruction, used
  where the answer is "matches the proof" or "it does not";
* ``measure`` - a reading with a tolerance band, which is what makes the gauge
  and seal strength checks worth having: an out-of-tolerance value fails the
  point rather than being written down and ignored;
* ``instructions`` - a step to be carried out and confirmed.

Checkpoints are seeded only when ``quality_control`` is installed, and the ones
attached to a manufacturing operation additionally need ``quality_mrp``.
Neither is a dependency of this module: they are separate apps, and this is a
data module. Install them from Apps and upgrade
``centric_manufacturing_demo``, and the points below appear.

The tolerances are PLAUSIBLE DEMO FIGURES for the gauges and grades in this
seed - a 50 micron film held to plus or minus 3, a seal that has to carry the
sack's own filled weight - not the customer's control plan. They should be
replaced with the real ones, which is a conversation with whoever signs off the
first article, not a decision for a seed script.
"""

# The incoming check sits on receipts; the rest sit on the operation named.
# Each entry is:
#   title: {
#       "products": product names the point applies to, empty for all,
#       "picking_type": "incoming" to attach to goods-in, else None,
#       "operation": the BoM operation name to attach to, else None,
#       "test_type": passfail | measure | instructions,
#       "norm", "tolerance_min", "tolerance_max", "norm_unit": measure only,
#       "note": the instruction the operator reads,
#   }
QUALITY_POINTS = {
    "Incoming resin - melt flow index and moisture": {
        "products": [
            "LDPE Film Grade Resin",
            "LLDPE Octene Resin",
            "HDPE Blown Film Resin",
        ],
        "picking_type": "incoming",
        "operation": None,
        "test_type": "passfail",
        "note": (
            "Before tipping to silo: check the batch certificate against the "
            "grade ordered, confirm the MFI is within the datasheet range and "
            "that the bags are dry and undamaged. Reject the pallet and hold "
            "it in quarantine if the certificate is missing - an off-grade "
            "resin is not visible until it is already in the extruder."
        ),
    },
    "Extrusion - film gauge across the web": {
        "products": [
            "Blown Film Reel 50um Clear (Jumbo)",
            "Blown Film Reel 50um White (Jumbo)",
        ],
        "picking_type": None,
        "operation": "Extrude and wind jumbo reel",
        "test_type": "measure",
        "norm": 50.0,
        "tolerance_min": 47.0,
        "tolerance_max": 53.0,
        "norm_unit": "um",
        "note": (
            "Take five readings across the layflat with the hand gauge, one "
            "at each edge, one at centre and one either side. Record the mean. "
            "Drifting thick wastes resin on every metre; drifting thin fails "
            "the seal test downstream."
        ),
    },
    "Flexo print - colour match to approved proof": {
        "products": [
            "Printed Bread Bag Film 40um - 3 Colour",
            "Printed Shrink Wrap 50um - 2 Colour",
            "Printed Carrier Bag Film 30um - 2 Colour",
            "Printed Biodegradable Film 45um - 2 Colour",
        ],
        "picking_type": None,
        "operation": "Flexo print 2 colours",
        "test_type": "passfail",
        "note": (
            "Pull a sheet at colour and compare against the signed customer "
            "proof under the light booth, not under the press lights. Check "
            "registration, the barcode scans, and that the artwork revision on "
            "the plate matches the works order. Do not run the job on a proof "
            "that has not been signed."
        ),
    },
    "Bag line - seal strength and dimensions": {
        "products": [
            "Carrier Bag 380x450mm - 2 Colour Printed",
            "Refuse Sack 750x950mm Black Heavy Duty",
            "Biodegradable Carrier Bag 300x400mm",
        ],
        "picking_type": None,
        "operation": "Convert, seal and cut to bags",
        "test_type": "measure",
        "norm": 12.0,
        "tolerance_min": 9.0,
        "tolerance_max": 25.0,
        "norm_unit": "N/15mm",
        "note": (
            "Every hour and at every reel change: peel test five seals off the "
            "run and record the lowest reading. Check the layflat and the cut "
            "length against the works order at the same time. A seal under "
            "tolerance is a sack that fails full, which is the complaint that "
            "costs the account."
        ),
    },
}
