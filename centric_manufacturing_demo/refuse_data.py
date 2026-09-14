# -*- coding: utf-8 -*-
"""P8.1 - the refuse and waste sack range.

Why it is a range of its own
----------------------------
The plant already made one refuse sack: the heavy duty black 750x950 in
``material_data.FINISHED_BAGS``, sold by the box to trade. That one stays where
it is - it is a general purpose sack bought by a butcher or a builder, priced
off a list, and it belongs beside the carriers it is sold alongside.

What is here is a different business. A household throws away roughly as many
sacks as it carries home, and buys them the way it buys any other grocery: by
size, by colour and by what its council collection expects. Sold to a retailer
that is a shelf line with a barcode; sold to a council or a waste contractor it
is a tender, priced per thousand against three other converters. Both are the
same product off the same bag line, and neither is a carrier bag.

That last point is not a filing preference. The eco-contribution in
``ecotax_data`` attaches to carrier bags and not to this range, so the two have
to be separable by looking at the product, which is why the range gets its own
category in ``material_data.REFUSE_CATEG``.

The kilogramme-to-unit machinery
--------------------------------
Identical to the bag and industrial ranges, and seeded by the same
``hooks._create_converted``: film in by weight, counted units out, offcut back
to the granulator, cost and price out of ``pricing.py``. The keys mean exactly
what they mean in ``material_data.FINISHED_BAGS`` - see the comment above that
table for the full list - and the optional ``run_qty``, ``workcenter`` and
``operation`` do the same job here. Nothing about the conversion is
reimplemented; if the rate ever changes it changes in one place.

``grams_per_bag`` is worked from the sack's own geometry rather than typed in,
at the same 920 kg/m3 the industrial range uses:

    grammes = 2 * layflat width (m) * length (m) * gauge (m) * 920 * 1000

The factor of two is the two walls of a flat bag. A gusset is ignored, which
understates the wheelie liner by a few percent - the honest way round, since a
sack quoted light is a sack quoted under cost. Every figure can therefore be
checked against the product name it sits next to instead of being taken on
trust.

Run sizes
---------
Not a round thousand. What a run is here is set by what the plant would
actually schedule and by what the sack weighs: 1,000 wheelie liners is 175
kilogrammes of film and half a shift, and nobody makes them a thousand at a
time, so that item runs 250. The swing bin liner and the caddy liner are small
and quick and run 2,000.

The colours
-----------
DEMO ASSUMPTION, and the one figure in this file most likely to be wrong: black
for mixed waste, green for organic and grey for recyclables. Malta's kerbside
collection is separated by the colour of the bag put out, so the mapping is a
specification rather than a styling choice - but which colour carries which
stream is a matter of the national scheme in force, and it has changed before.
Confirm it against the current scheme before go-live; the sizes, gauges and
colours here are a plausible set, not the published one.

Everything else in this file - gauges, cycle times, waste percentages, margins
and the certificate numbers - is a PLAUSIBLE DEMO FIGURE for a plant of this
shape, not the customer's specification or price book.
"""

# name -> spec, in the shape material_data.FINISHED_BAGS documents.
REFUSE_SACKS = {
    # ----------------------------------------------------------------- retail
    "Swing Bin Liner 11L 300x600mm White": {
        "film": "Blown Film Reel 20um White (Jumbo)",
        "grams_per_bag": 6.6,
        # Low: a small rectangular bag off a wide web is close to nesting
        # perfectly, and the only offcut is the reel change.
        "waste_pct": 3.5,
        # Coreless rolls. A swing bin liner is wound on itself and perforated,
        # so unlike every reel product above it consumes no core - which is
        # also why the roll count, not the core count, is what the bag line
        # operator is measured on.
        "extras": [("Export Carton 600x400x400", 3.0)],
        "run_qty": 2000.0,
        "minutes": 70.0,
        "code": "TP-BAG-SWG-300",
        "certification": (
            "Swing bin liner, LDPE, 11 litre nominal. Not food contact "
            "approved. Recyclable, LDPE 04."
        ),
        "margin": 0.22,
    },
    "Drawstring Kitchen Bag 30L 480x600mm White": {
        "film": "Blown Film Reel 20um White (Jumbo)",
        "grams_per_bag": 10.6,
        # The highest conversion waste in the range. The hem is folded and
        # sealed and the tape threaded through it on the same pass, and a
        # mis-thread scraps the bag rather than the metre.
        "waste_pct": 5.0,
        # The tape is a component, not film, so it is costed here and does not
        # appear in grams_per_bag - which means the product's ``weight`` field
        # understates the finished bag by the weight of its own drawstring,
        # about 0.9 g. That is deliberate: ``weight`` exists to derive the film
        # conversion, and putting the tape into it would corrupt the BoM
        # quantity to fix a carriage estimate.
        "extras": [
            ("LDPE Drawstring Tape 8mm", 0.9),
            ("Export Carton 600x400x400", 2.0),
        ],
        "minutes": 65.0,
        "code": "TP-BAG-DRW-480",
        "certification": (
            "Drawstring kitchen bag, LDPE, 30 litre nominal, tie handles. Not "
            "food contact approved. Recyclable, LDPE 04."
        ),
        "margin": 0.26,
    },
    # -------------------------------------------------------- contract / trade
    "Wheelie Bin Liner 240L 1100x1400mm Black": {
        "film": "Blown Film Reel 60um Black Heavy (Jumbo)",
        "grams_per_bag": 170.0,
        # Low percentage on a big sack: the offcut is a fixed strip whatever
        # the bag weighs, so it is a smaller share of a heavier one.
        "waste_pct": 3.0,
        "extras": [("Export Carton 600x400x400", 2.0)],
        # 250, not 1,000. A run of a thousand is 175 kg of film and most of a
        # shift on the bag line for a product ordered by the pallet twice a
        # quarter.
        "run_qty": 250.0,
        "minutes": 90.0,
        "code": "TP-BAG-WHL-1100",
        "certification": (
            "Wheelie bin liner for a 240 litre bin, LDPE. Manufactured with a "
            "minimum 30% post-industrial recycled content, recovered on site. "
            "Not food contact approved. Recyclable, LDPE 04."
        ),
        "margin": 0.20,
    },
    # -------------------------------------------------- separated collection
    # One size, three streams, three colours. Same geometry throughout so a
    # council ordering the set gets sacks that stack and dispense the same, and
    # so the only variable between the three lines is the grade - which is what
    # makes the cost difference between them answerable.
    "Waste Sack 700x1100mm Black - Mixed Waste": {
        "film": "Blown Film Reel 40um Black (Jumbo)",
        "grams_per_bag": 56.7,
        "waste_pct": 3.0,
        "extras": [("Export Carton 600x400x400", 2.0)],
        "minutes": 55.0,
        "code": "TP-BAG-MIX-700",
        "certification": (
            "Mixed waste collection sack, LDPE. Manufactured with a minimum "
            "20% post-industrial recycled content, recovered on site. Not food "
            "contact approved."
        ),
        # The thinnest margin the plant quotes anywhere. A collection sack is
        # tendered by the million against three other converters, and the
        # tender is decided on price - which is precisely why it is made on the
        # grade carrying the most regrind.
        "margin": 0.19,
    },
    "Waste Sack 700x1100mm Green - Organic Waste": {
        "film": "Blown Film Reel 25um Green (Jumbo)",
        "grams_per_bag": 35.4,
        "waste_pct": 3.0,
        "extras": [("Export Carton 600x400x400", 2.0)],
        "minutes": 52.0,
        "code": "TP-BAG-ORG-700",
        # Deliberately NOT sold as compostable, and the wording says so rather
        # than staying silent. This is a green polyethylene sack for the
        # organic round, not a certified compostable one - the certified item
        # in this range is the caddy liner below, which is made on a different
        # grade and carries a licence number. A green sack that lets a reader
        # infer compostability is a claim the plant cannot support, and an
        # unsupported claim on a bag is a regulatory problem rather than a
        # marketing one.
        "certification": (
            "Organic waste collection sack, LDPE, colour coded green. NOT "
            "compostable and not certified to EN 13432 - for collection to an "
            "organic waste facility only, not for home or industrial "
            "composting with its contents."
        ),
        "margin": 0.21,
    },
    "Waste Sack 700x1100mm Grey - Recyclables": {
        "film": "Blown Film Reel 30um Grey (Jumbo)",
        "grams_per_bag": 42.5,
        "waste_pct": 3.0,
        "extras": [("Export Carton 600x400x400", 2.0)],
        "minutes": 55.0,
        "code": "TP-BAG-REC-700",
        "certification": (
            "Dry recyclables collection sack, LDPE, colour coded grey. "
            "Manufactured with a minimum 20% post-industrial recycled content, "
            "recovered on site. Not food contact approved."
        ),
        "margin": 0.21,
    },
    # -------------------------------------------------------------- certified
    "Compostable Caddy Liner 10L 380x480mm": {
        # The existing certified grade, not a new one. A lighter gauge would
        # suit a caddy liner better and would cost less to make - but the
        # certificate covers a stated formulation at a stated thickness, and a
        # second gauge means a second certification at a cost the volume of
        # this one line does not carry. So the liner is heavier than a caddy
        # liner needs to be, on purpose, and the margin below is what pays for
        # the licence rather than for the film.
        "film": "Blown Film Reel 45um Biodegradable (Jumbo)",
        "grams_per_bag": 15.1,
        "waste_pct": 4.5,
        "extras": [("Export Carton 600x400x400", 3.0)],
        "run_qty": 2000.0,
        "minutes": 75.0,
        "code": "TP-BAG-CAD-380",
        "certification": (
            "Compostable kitchen caddy liner, 10 litre nominal. Certified to "
            "EN 13432:2000 / ISO 17088 for industrial composting, certificate "
            "TUV-OK-C-2024-08823 (OK compost INDUSTRIAL). Not certified for "
            "home composting. Do not place in the LDPE recycling stream."
        ),
        # Printed on the bag beside the scheme's logo, as the licence requires.
        "registration": "7P0848",
        "margin": 0.34,
    },
}
