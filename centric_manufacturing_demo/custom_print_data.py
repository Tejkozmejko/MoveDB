# -*- coding: utf-8 -*-
"""P3.8 - custom printed bags, made to order, one variant per customer artwork.

The problem
-----------
A printed carrier bag is not a stock item. The plant does not hold "printed
carrier bags"; it holds clear film, and it holds a set of photopolymer plates
per customer. When the bakery orders 50,000 bags, the plant mounts *that
bakery's* plates and runs *that bakery's* job. Two customers ordering the same
380x450mm carrier are ordering two different products that share everything
except the artwork.

Modelling that as one product per customer gives a product list that grows by
one line per customer won and never shrinks, with no way to ask what the plant
sells. Modelling it as one product with a free-text note on the order line
means the artwork is not a thing Odoo knows about: it cannot be reserved,
costed, reordered or reported on, and the press operator finds out which plates
to mount by reading a comment.

The model
---------
One product template - the bag - with a ``Customer Artwork`` attribute whose
values are the live artworks. Odoo generates a variant per artwork, so:

* the sales order line names the artwork, not a comment;
* each artwork has its own bill of materials, so a four colour job consumes
  four colours of ink and books the extra press time a fourth deck costs;
* forecast, cost and margin are answerable per artwork;
* retiring an artwork is archiving one attribute value.

Made to order
-------------
The template carries the **Make To Order** and **Manufacture** routes together.
Confirming a sales order for a custom printed bag therefore raises a
manufacturing order for exactly the quantity ordered, rather than trying to
reserve stock that by definition does not exist. This is the whole point: the
plant never wants a forecast of printed carrier bags, it wants a works order
the moment the customer commits.

The plates are deliberately **not** a BoM component. A plate set is tooling: it
is cut once, kept in the plate store, and mounted for every repeat of that job.
Consuming one per run would charge every order 240 euro for a plate that
already exists and would drive a reordering rule to buy plates nobody needs.
What the run does cost is the *mounting and make-ready* - proportional to the
number of colours - and that is in the operation time below. When the plant
wants a plate charged to a customer, that is a one-off tooling line on the
first order, not a line in the recipe.

The artworks, customers, colour counts and plate references below are
PLAUSIBLE DEMO FIGURES. The real plate register is in the plate store.
"""

# The template every custom artwork is a variant of.
CUSTOM_PRINT_PRODUCT = "Custom Printed Carrier Bag 380x450mm"
CUSTOM_PRINT_CODE = "TP-BAG-CUSTOM"

# The attribute whose values are the artworks.
ARTWORK_ATTRIBUTE = "Customer Artwork"

# The film the custom bag is converted from. Unprinted clear jumbo: the print
# is what the artwork adds, so it cannot start from film that is already
# printed - which is what separates this from the fixed carrier bag in
# FINISHED_BAGS, whose two colour design is baked into its film.
CUSTOM_PRINT_FILM = "Blown Film Reel 50um Clear (Jumbo)"

# Finished bag weight and conversion offcut, as in FINISHED_BAGS.
CUSTOM_GRAMS_PER_BAG = 12.0
CUSTOM_WASTE_PCT = 4.0

# A run is 50,000 bags, not the 1,000 the stock ranges use, because that is the
# plant's minimum order on custom print and the BoM has to be sized at
# something the plant would actually schedule. It matters to the cost: the
# make-ready below is the same 40 minutes whether the job is a thousand bags or
# a hundred thousand, so a BoM written at 1,000 charges every bag a full press
# set-up and prices the range about two and a half times over. That is the
# arithmetic the minimum order quantity exists to protect, and it is the reason
# a short custom run is quoted separately rather than off this price.
CUSTOM_RUN_QTY = 50000.0
CUSTOM_MARGIN = 0.34

# Ink per colour per run, and the extender that thins it. Two parts: what the
# artwork actually lays down on 620-odd kilogrammes of film, and the fixed
# amount left in the duct and the anilox that goes down the drain at washup -
# which is why a colour is not free even on a light coverage job.
INK_KG_PER_COLOUR = 1.1
EXTENDER_KG_PER_RUN = 0.6

# Cores and cartons for a run: about four printed reels' worth of cores, and a
# carton per thousand bags.
CORES_PER_RUN = 12.0
CARTONS_PER_RUN = 50.0

# Which ink deck each colour position draws from, in the order the press runs
# them. An artwork of N colours uses the first N.
COLOUR_SEQUENCE = (
    "Flexo Ink - Black",
    "Flexo Ink - Cyan",
    "Flexo Ink - Magenta",
    "Flexo Ink - Yellow",
)

# Press time, in three parts: a fixed make-ready, an extra make-ready per deck
# - mounting the plate, inking up and reaching register on that colour - and
# then the run itself, which is the film through the press and does not care
# how many colours it is. Set-up is a fixed cost on a variable order, which is
# why quoting a short custom run off the run rate alone loses money.
PRESS_SETUP_MINUTES = 40.0
PRESS_MINUTES_PER_COLOUR = 25.0
PRESS_RUN_MINUTES = 560.0

# The slitter and the bag line are pure run time at the rates the fixed ranges
# already use: 100 kg an hour through the slitter, 1,000 bags every 45 minutes
# off the bag line.
SLIT_MINUTES = 375.0
BAG_LINE_MINUTES = 2250.0

# Artwork value name -> {
#   "customer": the partner it belongs to, matched by name against the
#       customers in transaction_data. An artwork whose customer is not on the
#       database is still created - the artwork is the plant's record, and the
#       customer may be added later.
#   "colours": how many decks the job runs, which drives ink and press time.
#   "plate_ref": the plate store reference, so the press operator can find the
#       physical plates. This is the number written on the plate box.
#   "note": what the operator needs to know before running it.
# }
ARTWORKS = {
    "Mediterranean Bakeries - Bread Carrier v3": {
        "customer": "Mediterranean Bakeries Ltd",
        "colours": 3,
        "plate_ref": "PLT-MBL-0031",
        "note": (
            "Three colour process. Brand red is a spot match to Pantone 186 C "
            "and is signed off against the 2024 proof - do not build it from "
            "process."
        ),
    },
    "Valletta Foods - Retail Carrier": {
        "customer": "Valletta Foods Distribution Ltd",
        "colours": 2,
        "plate_ref": "PLT-VFD-0018",
        "note": (
            "Two colour reverse print. The white deck runs last as a backing "
            "so the artwork reads through the film."
        ),
    },
    "Gozo Farm Produce - Produce Bag": {
        "customer": "Gozo Farm Produce Co-operative",
        "colours": 1,
        "plate_ref": "PLT-GFP-0006",
        "note": (
            "Single colour line work. Carries the co-operative's EU organic "
            "certification mark - the mark and its certifier number may not be "
            "altered, resized out of proportion or reproduced in another "
            "colour."
        ),
    },
    "Unprinted - Plain Clear": {
        "customer": None,
        "colours": 0,
        "plate_ref": None,
        "note": (
            "No artwork. Kept as a variant so a plain bag can be quoted and "
            "run through the same made-to-order route as a printed one."
        ),
    },
}


def press_minutes(colours):
    """Press time for one run of an artwork with ``colours`` decks.

    Zero colours means the press is not used at all - the plain variant goes
    straight from reel to bag line - and returning zero is what lets the BoM
    builder leave the print operation off it entirely.
    """
    if not colours:
        return 0.0
    return (
        PRESS_SETUP_MINUTES + PRESS_MINUTES_PER_COLOUR * colours + PRESS_RUN_MINUTES
    )


def artwork_inks(colours):
    """Return [(ink product name, kg per run), ...] for ``colours`` decks."""
    if not colours:
        return []
    if colours > len(COLOUR_SEQUENCE):
        raise ValueError(
            "The press has %s decks configured here, artwork asks for %s"
            % (len(COLOUR_SEQUENCE), colours)
        )
    inks = [(name, INK_KG_PER_COLOUR) for name in COLOUR_SEQUENCE[:colours]]
    inks.append(("Solvent-Based Ink Extender", EXTENDER_KG_PER_RUN))
    return inks


def artwork_description(name, spec):
    """The sale description that travels onto the quotation and works order."""
    parts = []
    if spec["customer"]:
        parts.append("Artwork %s, held for %s." % (name, spec["customer"]))
    else:
        parts.append("%s." % name)
    if spec["colours"]:
        parts.append(
            "%s colour flexo, plate set %s." % (spec["colours"], spec["plate_ref"])
        )
    parts.append(spec["note"])
    parts.append(
        "Made to order: confirming an order for this artwork raises a works "
        "order. No finished stock is held."
    )
    return " ".join(parts)
