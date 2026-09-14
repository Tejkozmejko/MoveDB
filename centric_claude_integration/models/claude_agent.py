from odoo import fields, models


class CentricClaudeAgent(models.Model):
    """One row per bridge, recording when it was last heard from.

    Deliberately not an ``ir.config_parameter``. ``get_param`` is ormcached, so
    every write to a parameter clears the registry cache and signals every
    worker in the instance to do the same. The heartbeat is written every
    twenty seconds, which meant the whole instance threw away its caches three
    times a minute, all day, for a value whose only purpose is an online badge:

        Caches invalidated, signaling through the database: ['stable']
        Caches invalidated, signaling through the database: ['stable']
        Caches invalidated, signaling through the database: ['stable']

    Writing an ordinary model row invalidates nothing. It also stops the
    heartbeat sharing one row with every other setting in the database, which
    is what made it the hottest write in the module.

    Nothing needs migrating into this table. A heartbeat is stale after sixty
    seconds by definition, so carrying the old value across would preserve
    something that expires before anyone could read it; the first ping writes a
    row, and until then liveness comes from the most recently claimed turn.
    """

    _name = "centric.claude.agent"
    _description = "Claude Bridge"
    _order = "last_seen desc"

    name = fields.Char(required=True, index=True, help="The bridge's own name.")
    last_seen = fields.Datetime(required=True, index=True)
