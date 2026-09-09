# -*- coding: utf-8 -*-
"""Re-run the seed on upgrade, not just on a fresh install.

Odoo only calls ``post_init_hook`` when a module is *installed*, so a database
that already has ``centric_manufacturing_demo`` would otherwise never pick up
data added in a later version. The hook is idempotent - it matches on name or
code and skips anything that already exists - so calling it again from a
migration is safe and is what brings an existing database up to date.

Adding data in a future version means bumping ``version`` in the manifest and
copying this file into the matching ``migrations/<version>/`` folder; Odoo only
runs scripts for versions it is crossing.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.centric_manufacturing_demo.hooks import post_init_hook

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install: post_init_hook has already run (or is about to).
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info(
        "centric_manufacturing_demo: upgrading from %s, re-running the seed", version
    )
    post_init_hook(env)
