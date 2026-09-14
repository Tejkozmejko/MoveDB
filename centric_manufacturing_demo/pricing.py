# -*- coding: utf-8 -*-
"""P6.4 - the bag pricing calculator.

What the plant actually needs to answer, several times a day, is: a customer
wants 50,000 printed carrier bags at 380x450mm, what do we quote? Today that is
a spreadsheet on somebody's desktop, which is why two salespeople quote two
different numbers for the same bag.

The arithmetic is not complicated, and it is worth writing down rather than
leaving in the spreadsheet:

    bag weight (kg)   = grams_per_bag / 1000
    film needed (kg)  = bag weight * (1 + waste / 100)
    material cost     = film needed * film cost per kg
    conversion cost   = bag line rate per hour * run minutes / 60 / run bags
    extras            = cartons and consumables, per bag
    cost per bag      = material + conversion + extras
    price per bag     = cost per bag / (1 - margin)

Two things are worth being explicit about, because they are where hand-built
quotes go wrong:

* **Waste is added to the film, not taken off the bag.** A 12 g bag run at 4%
  offcut does not consume 12 g of film, it consumes 12.5. Costing the bag at
  its finished weight quietly gives the whole range away at a few percent under
  cost.
* **Margin is a divisor, not a multiplier.** A 32% margin is
  ``cost / 0.68``, not ``cost * 1.32``. The second is a 32% *mark-up*, which is
  a different and smaller number - 24% margin, in that case. Quoting mark-up as
  though it were margin is the single most common way a converter loses money
  on a job it thought was fine.

The film cost this reads is the rolled-up standard cost the BoMs computed, so a
price recomputed after resin moves follows the resin. The margins live beside
the range in ``material_data.FINISHED_BAGS`` because they are a commercial
decision, not a formula.

The figures here are DEMO FIGURES. The margins in particular are plausible
converter margins, not the customer's price book.
"""

from .material_data import BAG_RUN_QTY


def film_kg_per_bag(grams_per_bag, waste_pct):
    """Kilogrammes of film consumed per finished bag, offcut included."""
    return grams_per_bag / 1000.0 * (1.0 + waste_pct / 100.0)


def bag_cost(spec, film_cost_per_kg, extras_cost_per_run, workcenter_rate, run_qty=None):
    """Return the fully absorbed cost of one bag, or one converted unit.

    ``extras_cost_per_run`` is the cartons and consumables for a whole run;
    everything else is per unit. ``run_qty`` is how many units that run makes -
    it defaults to ``BAG_RUN_QTY`` for the bag range, and the industrial items
    pass their own, because a run of pallet wrap is 200 rolls and a run of
    shrink hoods is 500. Getting this wrong divides the machine time and the
    cartons across the wrong number of units, which is the same error as
    quoting a run rate for a sample order.
    """
    run_qty = run_qty or BAG_RUN_QTY
    material = film_kg_per_bag(spec["grams_per_bag"], spec["waste_pct"]) * film_cost_per_kg
    conversion = workcenter_rate * spec["minutes"] / 60.0 / run_qty
    extras = extras_cost_per_run / run_qty
    return material + conversion + extras


def bag_price(cost_per_bag, margin):
    """Apply a gross margin to a cost. See the module docstring on the divisor."""
    if not 0.0 <= margin < 1.0:
        raise ValueError("Margin must be a fraction below 1, got %r" % (margin,))
    return cost_per_bag / (1.0 - margin)


def with_margin(cost, margin):
    """Same calculation, named for the per-kilogramme film case."""
    return bag_price(cost, margin)
