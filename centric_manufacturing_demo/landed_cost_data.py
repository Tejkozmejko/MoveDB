# -*- coding: utf-8 -*-
"""P5.4 - landed costs on inbound resin.

Resin arrives by sea in containers from Rotterdam, Trieste and Antwerp, and the
invoice from the trader is not what the material costs to have on the floor.
Freight, duty, port handling and the inland leg add materially to a container
of LDPE, and if they are posted straight to an expense account then every BoM
underneath quietly under-costs the film.

Odoo's answer is ``stock.landed.cost``: a service product flagged
``landed_cost_ok``, allocated across the receipt it belongs to, which revalues
the quants rather than expensing the charge. The split method decides how:

* ``by_weight`` for freight and handling - a sea container is charged by what
  is in it, and resin is heavy;
* ``by_current_cost_value`` for duty and insurance - both are levied on the
  value of the goods, not their weight;
* ``equal`` for the flat per-entry charges, such as the customs broker's fee,
  which is the same whether the container holds resin or ink.

These products are seeded, not the historical landed cost entries: applying a
landed cost to the receipts the trading history already posted would revalue
stock that the seeded bills and invoices were costed against, and the demo's
accounting would stop tying out. The products give Purchasing something to
choose from on the next real receipt.

This only runs when ``stock_landed_costs`` is installed. The module is not a
dependency - it is a separate app, and a data module has no business installing
one on every database that takes this seed.
"""

# name -> (split method, plausible cost, description)
LANDED_COSTS = {
    "Inbound Sea Freight": (
        "by_weight",
        1850.00,
        "Container freight, load port to Malta Freeport. Charged per "
        "container; allocate across the receipt by weight.",
    ),
    "Customs Duty & Import VAT": (
        "by_current_cost_value",
        0.00,
        "Duty and import VAT, levied on the customs value of the goods. "
        "Enter the amount from the C88 / import declaration.",
    ),
    "Marine Insurance": (
        "by_current_cost_value",
        0.00,
        "Cargo insurance premium for the shipment, allocated on value.",
    ),
    "Port Handling & Haulage": (
        "by_weight",
        420.00,
        "Terminal handling, lift-on/lift-off and the inland leg from the "
        "Freeport to the plant.",
    ),
    "Customs Clearance Fee": (
        "equal",
        95.00,
        "Broker's fee per entry. Flat, so it splits equally across the lines "
        "on the receipt rather than by weight or value.",
    ),
}
