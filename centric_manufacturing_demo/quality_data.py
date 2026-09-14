# -*- coding: utf-8 -*-
"""P7.1 - quality control checkpoints.

The checks below are the ones the plant already does and writes on a
clipboard: gauge on the extruder, colour against the approved proof on the
press, seal strength off the bag line, and an incoming check on resin before it
is tipped into a silo. Putting them on ``quality.point`` is what turns them
from a clipboard into a record attached to the works order, so a customer
complaint six months later can be traced to the shift that made the reel.

Two more came with the waste sack range (P8.1): a gauge and colour check on the
four sack grades, and a drop test on the filled sack. The drop test is the one
that earns its place - those grades carry up to 30% recovered material, and a
drop test is where too much of it, or a bale of the wrong history, actually
shows itself. Everything else about regrind is an argument on paper.

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
            # P8.1 - the waste sack range joins the existing seal check rather
            # than getting one of its own. It is the same test on the same
            # machine, and the tolerance band already spans the range: 9 N/15mm
            # is set by what the heaviest sack has to carry when full, so a
            # swing bin liner passing it has a comfortable margin and a wheelie
            # liner failing it is the failure the band was drawn for.
            "Swing Bin Liner 11L 300x600mm White",
            "Drawstring Kitchen Bag 30L 480x600mm White",
            "Wheelie Bin Liner 240L 1100x1400mm Black",
            "Waste Sack 700x1100mm Black - Mixed Waste",
            "Waste Sack 700x1100mm Green - Organic Waste",
            "Waste Sack 700x1100mm Grey - Recyclables",
            "Compostable Caddy Liner 10L 380x480mm",
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
    # ---------------------------------------------------------------- P8.1
    "Extrusion - waste sack grade gauge and colour": {
        "products": [
            "Blown Film Reel 60um Black Heavy (Jumbo)",
            "Blown Film Reel 30um Grey (Jumbo)",
            "Blown Film Reel 25um Green (Jumbo)",
            "Blown Film Reel 20um White (Jumbo)",
        ],
        "picking_type": None,
        "operation": "Extrude and wind jumbo reel",
        # Deliberately passfail and not measure, unlike the gauge check above
        # it. A ``measure`` point carries ONE norm and ONE tolerance band, and
        # these four grades run at four nominal gauges from 20 to 60 micron -
        # so a single band either passes everything or fails everything. The
        # honest answer is to check each reel against the gauge on its own
        # works order, which is a judgement against a written instruction.
        # Splitting this into four measure points, one per grade, is the better
        # answer the day somebody wants the readings trended.
        "test_type": "passfail",
        "note": (
            "Check the gauge against the nominal on the works order, not "
            "against a fixed figure - these grades run from 20 to 60 micron. "
            "Five readings across the layflat, mean within plus or minus 8% of "
            "nominal. Then check the colour against the retained sample for "
            "the grade: on a collection sack the colour IS the specification, "
            "because the householder sorts by it and a sack read as the wrong "
            "stream is contamination at the transfer station."
        ),
    },
    "Bag line - waste sack drop test": {
        "products": [
            "Wheelie Bin Liner 240L 1100x1400mm Black",
            "Waste Sack 700x1100mm Black - Mixed Waste",
            "Waste Sack 700x1100mm Green - Organic Waste",
            "Waste Sack 700x1100mm Grey - Recyclables",
        ],
        "picking_type": None,
        "operation": "Convert, seal and cut to bags",
        "test_type": "measure",
        # Drops survived out of ten, not a pass/fail on one drop. A sack that
        # fails one drop in ten is a different product from one that fails
        # eight, and averaging the complaint over a season loses that.
        "norm": 10.0,
        "tolerance_min": 9.0,
        "tolerance_max": 10.0,
        "norm_unit": "drops passed of 10",
        "note": (
            "Once per run on the collection grades: fill a sack to its rated "
            "volume with the test medium, tie it, and drop it from 1.2 m onto "
            "concrete ten times. Record how many drops it survives intact. "
            "This is the test the whole regrind argument rests on - these are "
            "the grades carrying up to 30% recovered material, and this is "
            "where too much of it, or a bale of the wrong history, shows up. "
            "A sack that splits on the round is picked up by hand by somebody, "
            "and that is how a council contract is lost."
        ),
    },
}
