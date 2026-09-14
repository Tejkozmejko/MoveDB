# -*- coding: utf-8 -*-
"""P4.8 - lot traceability, resin batch through to delivered pallet.

Why the plant needs it
----------------------
Two questions have to be answerable, and today they are answered by hand from
the extrusion log book:

* **Forwards.** A resin batch is recalled by the supplier, or a batch
  certificate turns out to be wrong. Which reels did it go into, which jobs
  were printed on those reels, and which customers took the bags? Every one of
  those deliveries has to be identified, today, not next week.
* **Backwards.** A customer returns a pallet of bags that split. Which reel,
  which extrusion run, which resin batch, which shift? Without that the plant
  cannot tell a bad batch from a bad setting, and the same fault comes back.

Lot, not serial
---------------
Everything here is tracked by **lot**, not serial number. A lot is a batch: one
resin delivery, one extrusion run, one print job, one bag run. Serial numbers
would mean a unique number per bag, which is meaningless for a product made a
million at a time and would make every transfer unworkable.

What is tracked and what is not
-------------------------------
Anything that can carry a defect forward into a delivered product is tracked:
resin, masterbatch, additive, ink, and every made reel, film and finished bag.
Cores and cartons are not - a paper core is not a food contact material and
nobody has ever recalled one - and tracking them would put a lot number prompt
on every receipt for no return.

Recovered scrap is deliberately untracked. It is baled from every line and
every grade at once, so a lot number on it would claim a precision the bale
does not have. This is also the honest limit of the traceability chain: the
regrind loop is where a strict forwards trace stops, which is exactly why the
biodegradable grade in ``material_data`` takes no regrind at all. That grade's
certificate depends on a formulation, and film built from a bale of unknown
history cannot be declared against it.

Lot numbers
-----------
``TP/<prefix>/<nnnnn>`` - the site, what it is, and a running number. Readable
off a label at arm's length on the shop floor, which a UUID is not.
"""

# Lot name prefix per tracked bought-in material. Short and specific: the
# operator booking in a delivery reads the prefix to check they are labelling
# the right thing.
MATERIAL_LOT_PREFIX = {
    "LDPE Film Grade Resin": "LDPE",
    "LLDPE Octene Resin": "LLD",
    "HDPE Blown Film Resin": "HDPE",
    "White Masterbatch (TiO2)": "MB-W",
    "Black Masterbatch": "MB-K",
    "Blue Masterbatch": "MB-B",
    "Green Masterbatch": "MB-G",
    "Slip / Antiblock Additive": "ADD-S",
    "Oxo-Biodegradable Additive": "ADD-O",
    "Polyisobutylene Tackifier": "ADD-T",
    "Flexo Ink - Cyan": "INK-C",
    "Flexo Ink - Magenta": "INK-M",
    "Flexo Ink - Yellow": "INK-Y",
    "Flexo Ink - Black": "INK-K",
    "Flexo Ink - White": "INK-W",
    "Solvent-Based Ink Extender": "INK-EX",
}

# Made products get a prefix by what they are rather than by name, because the
# name of a grade changes and its place in the chain does not.
WIP_LOT_PREFIX = "REEL"
FINISHED_LOT_PREFIX = "JOB"

# Materials that are counted rather than weighed and carry no defect forward.
# Listed explicitly rather than inferred from the unit of measure, so adding a
# counted material that *does* matter - a printed label, say - is a decision
# somebody makes here rather than one the code makes for them.
UNTRACKED_MATERIALS = (
    "Photopolymer Printing Plate Set",
    # Drawstring tape sits with the cores and cartons rather than with the
    # compound, and the test is the same one: could a bad batch of it reach a
    # customer as a defect in the bag? A tape that breaks is a bag that will
    # not tie, which is a complaint and a credit note - not a recall, and not
    # something anyone would trace to a resin batch. Tracking it would put a
    # lot prompt on every receipt to buy nothing.
    "LDPE Drawstring Tape 8mm",
    'Paper Core 76mm (3")',
    'Paper Core 152mm (6")',
    "Export Carton 600x400x400",
)


def lot_name(prefix, sequence):
    """Return the lot number for ``sequence`` under ``prefix``."""
    return "TP/%s/%05d" % (prefix, sequence)


def lot_prefix(product):
    """The prefix a product's lots carry.

    A bought-in material has one of its own; anything the plant made is a reel
    if it is still work in progress and a job if it is finished, which is the
    distinction the shop floor already draws.
    """
    name = product.product_tmpl_id.name
    if name in MATERIAL_LOT_PREFIX:
        return MATERIAL_LOT_PREFIX[name]
    categ = product.categ_id.complete_name or ""
    return WIP_LOT_PREFIX if "Semi-Finished" in categ else FINISHED_LOT_PREFIX


def create_lot(env, product, company):
    """Create and return the next ``stock.lot`` for ``product``.

    The running number is taken from how many lots already carry the prefix, so
    re-running the seed continues the series rather than colliding with it.
    Shared by the master data hook, which labels the opening stock, and the
    trading history, which labels receipts and production runs - one
    implementation, so a lot minted by either is the same shape.
    """
    Lot = env["stock.lot"]
    prefix = lot_prefix(product)
    sequence = Lot.with_context(active_test=False).search_count(
        [("name", "=like", "TP/%s/%%" % prefix)]
    )
    # Collisions are possible if somebody has numbered by hand, so walk on
    # until the name is free rather than failing the whole seed over a label.
    while True:
        sequence += 1
        name = lot_name(prefix, sequence)
        if not Lot.with_context(active_test=False).search_count(
            [("name", "=", name), ("product_id", "=", product.id)]
        ):
            return Lot.create(
                {"name": name, "product_id": product.id, "company_id": company.id}
            )
