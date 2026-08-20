{
    "name": "Centric Claude Integration",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "Centric",
    "website": "https://www.centricmt.com",
    "summary": "Claude developer workspace for approved Odoo custom modules",
    "description": """
Centric Claude Integration
==========================

Adds a controlled Claude developer workspace inside Odoo.

* Chat with Claude from an Odoo client action.
* Let Claude inspect approved Centric modules in a configured GitHub repository.
* Browse repository files from Odoo without opening VS Code.
* Stage AI or manual code changes inside Odoo before anything is committed.
* Require both an Odoo Developer security group and a per-conversation
  Developer Mode toggle before code can be changed.
* Commit reviewed changes to a dedicated GitHub review branch.
* Optionally create a pull request after committing.
* Keep an audit trail of repository reads, staged changes, commits and PRs.

The module never edits the running Odoo filesystem. Source changes go through
GitHub, so Odoo.sh can build and validate the resulting branch normally.
""",
    "depends": ["base_setup", "web"],
    "data": [
        "security/claude_security.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/claude_audit_log_views.xml",
        "views/claude_turn_views.xml",
        "views/claude_workspace_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "centric_claude_integration/static/src/js/claude_workspace.js",
            "centric_claude_integration/static/src/xml/claude_workspace.xml",
            "centric_claude_integration/static/src/scss/claude_workspace.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
