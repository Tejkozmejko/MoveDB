"""Move users from the old four-level ladder onto the new three-level one.

The old ladder was User > Code Reader > Developer > Administrator. The new one
is User > Intermediate > Administrator, and the two middle groups have been
dropped out of the privilege so they no longer show in the user-form dropdown.

Without this script the dropdown would lie: an old Developer keeps code-write
access through the legacy group while the form renders them as plain "User".
Mapping them explicitly is what makes the displayed level the real level.

    Developer    -> Administrator   (they could already write code)
    Code Reader  -> Intermediate    (they could already read, not write)

Only ever adds groups. Nothing here can take access away from a user.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    def group(xml_id):
        return env.ref("centric_claude_integration.%s" % xml_id, raise_if_not_found=False)

    legacy_developer = group("group_claude_developer")
    legacy_reader = group("group_claude_code_reader")
    admin = group("group_claude_admin")
    intermediate = group("group_claude_intermediate")
    if not admin or not intermediate:
        _logger.warning("Centric Claude: new access groups are missing, skipping the level migration.")
        return

    # Administrator implies Developer, so by the time this runs `developer.users`
    # is "everyone who could write code", old admins included. Promoting the whole
    # set is a no-op for the ones already there.
    promote_to_admin = (legacy_developer.users - admin.users) if legacy_developer else env["res.users"]
    if promote_to_admin:
        admin.sudo().write({"users": [(4, user.id) for user in promote_to_admin]})
        _logger.info(
            "Centric Claude: promoted %s legacy Developer user(s) to Administrator: %s",
            len(promote_to_admin), ", ".join(promote_to_admin.mapped("login")),
        )

    # Whoever is left holding Code Reader could read source but not write it.
    # Intermediate is the closest new rung: still no code, but real Odoo access.
    promote_to_intermediate = (
        (legacy_reader.users - admin.users - intermediate.users)
        if legacy_reader else env["res.users"]
    )
    if promote_to_intermediate:
        intermediate.sudo().write({"users": [(4, user.id) for user in promote_to_intermediate]})
        _logger.info(
            "Centric Claude: moved %s legacy Code Reader user(s) to Intermediate: %s",
            len(promote_to_intermediate), ", ".join(promote_to_intermediate.mapped("login")),
        )

    # The bridge service account must land on Administrator too: every endpoint
    # runs as it, and code staging is now an Administrator capability.
    agent_uid = env["ir.config_parameter"].sudo().get_param("centric_claude.agent_uid")
    if agent_uid:
        agent = env["res.users"].sudo().browse(int(agent_uid)).exists()
        if agent and agent not in admin.users:
            _logger.warning(
                "Centric Claude: 'Agent Runs As' user %s does not hold the Claude "
                "Administrator group. Staged code changes from the bridge will be "
                "refused until an administrator grants it.", agent.login,
            )
