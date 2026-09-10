# -*- coding: utf-8 -*-
"""P8.2 - the eco-contribution on carrier bags.

READ THIS FIRST
---------------
Nothing in this file is a statement of law. Every rate, date and rule below is
a DEMO FIGURE chosen to make the Odoo mechanism demonstrable, and the whole lot
sits in one block - ``ECO_CONTRIBUTION`` - precisely so that whoever checks it
against the legislation actually in force has one place to look and one place
to correct. Do not read the numbers here as the current Maltese rate, do not
quote them to a customer, and do not go live on them.

What the mechanism is for
-------------------------
A levy on single-use carrier bags is a fixed amount per bag, and that one word
- fixed - is the whole reason this is not simply another tax line. A
percentage tax rides on the price, so a cheap bag pays less than a dear one and
the levy falls hardest on exactly the product it is meant to discourage least.
A fixed amount per bag lands identically on every bag, which is the point of
it: the charge is for the bag existing, not for what it cost.

In Odoo that is ``account.tax`` with ``amount_type = 'fixed'``, and the
distinction matters at seeding time because a fixed tax is the one shape people
get wrong - a 0.15 percentage tax and a 0.15 fixed tax are both accepted by the
form and differ by two orders of magnitude on the invoice.

The two collection models
-------------------------
The trade argument this models is not about the rate, it is about who hands the
money over, and the two answers produce visibly different accounts. Both are
seeded - see ``transaction_data.SALES_ORDERS`` - on the same product at the
same quantity, so they can be put side by side in Accounting:

* ``COLLECTION_INVOICED`` - the manufacturer adds the levy to its invoice to
  the retailer. The manufacturer collects it and remits it, which means it is
  out of pocket for the levy on every bag between despatch and the retailer
  paying - at 60 day terms on a lorry-load of bags, real working capital - and
  a bag that never reaches a till has still been charged.

* ``COLLECTION_POINT_OF_SALE`` - the manufacturer invoices the retailer without
  the levy, and the levy is charged to the customer at the till on the bag they
  actually take. This is the model the converters argued for, on two grounds:
  the manufacturer stops financing a tax it does not owe, and a bag that
  arrived outside the normal channels is charged at the till the same as any
  other, because the till does not know or care where the bag came from.

Which of the two is in force is not this module's business; both are seeded so
the difference can be seen rather than described.

What attracts it and what does not
----------------------------------
``LEVIED_PRODUCTS`` is deliberately a list of product names and not a rule
inferred from the category, so that adding a product to the range is not
silently adding it to the tax. What is on the list is the carrier bag range:
the bag a shop hands a customer at the point of sale, which is the thing a
carrier bag levy exists to discourage.

What is deliberately NOT on it, and why:

* **the refuse and waste sack range** (``refuse_data``) - a refuse sack is not
  dispensed at a till, it is a product somebody went to a shop to buy. Whatever
  the environmental argument, a levy written for carrier bags does not reach
  it, and the plant is not going to invent a tax on itself;
* **industrial packaging** (``material_data.INDUSTRIAL_PACKAGING``) - pallet
  wrap and box liners never meet a consumer at all;
* **film sold on the reel** - sold by the kilogramme to a converter or a
  packer, so there is no bag to count and nothing to charge per bag;
* **the compostable carrier** - it IS on the list. That is a deliberate choice
  and an arguable one: the plant's own position is that a certified compostable
  bag should not be levied at the same rate as an uncertified one, and the
  argument has been made in public more than once. But the plant does not get
  to grant itself an exemption, so the seed charges it and leaves the
  disagreement where it belongs. If an exemption exists in the scheme in force,
  take the product off this list.

A note on the certified range
-----------------------------
A compostable bag is certified as a *product*, not as a material, and the
licence obliges the maker to print the scheme's logo and the product's own
registration number on the bag. That number lives on the product in
``material_data`` and ``refuse_data`` as ``registration`` and travels onto the
quotation and the delivery note, because a claim a customer can read is a claim
that has to be checkable - and because the number on the paperwork and the
number on the plate had better be the same string.
"""

# ---------------------------------------------------------------------------
# THE ONE BLOCK OF FIGURES TO CHECK
# ---------------------------------------------------------------------------
# DEMO FIGURES. Confirm every one of these against the Maltese legislation in
# force before go-live, and correct them HERE - nothing below or outside this
# file hard-codes a rate or a date.
#
# ``amount`` is the rate the seed charges. ``introduced_*`` are carried purely
# so the demo can show the levy as something with a history rather than a
# number that appeared from nowhere; nothing computes from them.
ECO_CONTRIBUTION = {
    "name": "Eco-Contribution - Plastic Carrier Bag",
    # Per bag, in the company's currency. A fixed amount, NOT a percentage.
    "amount": 0.15,
    # What it started at, and roughly when. At the original rate the charge was
    # small enough that few shoppers noticed paying it, which is the reason a
    # later rate is a different conversation rather than the same one scaled.
    "introduced_year": 2005,
    "introduced_amount": 0.02,
    # Shown on the tax itself, so anyone opening it in Accounting reads the
    # caveat rather than trusting the number.
    "description": (
        "Fixed per-bag environmental contribution on plastic carrier bags. "
        "DEMO RATE - confirm against the legislation in force before go-live."
    ),
}

# The two collection models the seeded sales orders contrast. See the module
# docstring; these are the values ``transaction_data`` puts on an order's
# ``eco_collection`` key.
COLLECTION_INVOICED = "invoiced"
COLLECTION_POINT_OF_SALE = "point_of_sale"

# Product names that attract the levy. Named individually and on purpose - see
# the module docstring on why this is not inferred from the product category.
LEVIED_PRODUCTS = (
    "Carrier Bag 380x450mm - 2 Colour Printed",
    "Biodegradable Carrier Bag 300x400mm",
)

# The made-to-order printed carrier is a carrier bag like any other, so it is
# levied too - but it is a product *template* carrying one variant per customer
# artwork rather than a product with a name of its own, which is why it cannot
# just be listed above. ``hooks`` resolves it through ``custom_print_data``.
LEVY_CUSTOM_PRINT = True
