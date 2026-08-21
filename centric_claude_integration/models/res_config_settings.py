import secrets

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    centric_claude_enabled = fields.Boolean(
        string="Enable Claude",
        config_parameter="centric_claude.enabled",
    )
    centric_claude_backend = fields.Selection(
        [
            ("agent", "Local Claude Code agent"),
            ("api", "Anthropic API"),
        ],
        string="Claude Backend",
        default="agent",
        required=True,
        config_parameter="centric_claude.backend",
        help=(
            "Local Claude Code agent: a bridge on a developer machine runs the "
            "request with the Claude Code CLI, using that developer's Claude "
            "subscription. Odoo needs no Anthropic API key.\n"
            "Anthropic API: Odoo calls api.anthropic.com directly, billed per token."
        ),
    )
    centric_claude_agent_token = fields.Char(
        string="Agent Token",
        config_parameter="centric_claude.agent_token",
        help="Shared secret the local bridge presents as a Bearer token.",
    )
    centric_claude_agent_uid = fields.Many2one(
        "res.users",
        string="Agent Runs As",
        config_parameter="centric_claude.agent_uid",
        help="Odoo user the bridge acts as. Must hold the Claude Developer group.",
    )
    centric_claude_api_key = fields.Char(
        string="Anthropic API Key",
        config_parameter="centric_claude.api_key",
    )
    centric_claude_model = fields.Char(
        string="Claude Model",
        default="claude-opus-5",
        config_parameter="centric_claude.model",
    )
    centric_claude_max_tokens = fields.Integer(
        string="Maximum Output Tokens",
        default=16000,
        config_parameter="centric_claude.max_tokens",
    )
    centric_claude_max_tool_rounds = fields.Integer(
        string="Maximum Tool Rounds",
        default=8,
        config_parameter="centric_claude.max_tool_rounds",
    )

    centric_claude_github_owner = fields.Char(
        string="GitHub Owner",
        config_parameter="centric_claude.github_owner",
    )
    centric_claude_github_repo = fields.Char(
        string="GitHub Repository",
        config_parameter="centric_claude.github_repo",
    )
    centric_claude_github_token = fields.Char(
        string="GitHub Token",
        config_parameter="centric_claude.github_token",
    )
    centric_claude_default_branch = fields.Char(
        string="Default Base Branch",
        default="testing",
        config_parameter="centric_claude.default_branch",
    )
    centric_claude_allowed_module_prefix = fields.Char(
        string="Allowed Module Prefix",
        default="centric_",
        config_parameter="centric_claude.allowed_module_prefix",
    )
    centric_claude_code_read_enabled = fields.Boolean(
        string="Allow Source Code Reading",
        default=True,
        config_parameter="centric_claude.code_read_enabled",
    )
    centric_claude_default_effort = fields.Selection(
        [
            ("low", "Low - quick lookups"),
            ("medium", "Medium - routine work"),
            ("high", "High - balanced (default)"),
            ("xhigh", "Very high - deep code work"),
            ("max", "Maximum - correctness over cost"),
        ],
        string="Default Effort",
        default="high",
        config_parameter="centric_claude.default_effort",
        help="Where new conversations start. Each person can change it per "
             "conversation. Lower levels use less of the Claude subscription.",
    )
    centric_claude_data_enabled = fields.Boolean(
        string="Allow Odoo Data Access",
        default=True,
        config_parameter="centric_claude.data_enabled",
        help="Master switch for reading and changing Odoo records. Each user "
             "still needs a Centric Claude Data level, and every query runs "
             "with that user's own Odoo permissions.",
    )
    centric_claude_attachments_enabled = fields.Boolean(
        string="Allow Image Attachments",
        default=True,
        config_parameter="centric_claude.attachments_enabled",
        help="Let users paste or attach images in the chat. With the local "
             "agent backend the image is copied to the machine running the "
             "bridge for the length of one question, then deleted.",
    )
    centric_claude_attachment_max_mb = fields.Float(
        string="Maximum Image Size (MB)",
        default=5.0,
        config_parameter="centric_claude.attachment_max_mb",
        help="Largest single image a user may attach.",
    )
    centric_claude_attachment_retention_days = fields.Integer(
        string="Delete Images After (days)",
        default=30,
        config_parameter="centric_claude.attachment_retention_days",
        help="Attached images are deleted once they reach this age, so the "
             "filestore does not grow forever. Transcripts are kept. Set 0 to "
             "keep images indefinitely.",
    )
    centric_claude_code_write_enabled = fields.Boolean(
        string="Allow Code Modifications",
        default=False,
        config_parameter="centric_claude.code_write_enabled",
    )
    centric_claude_pull_request_enabled = fields.Boolean(
        string="Allow Pull Request Creation",
        default=True,
        config_parameter="centric_claude.pull_request_enabled",
    )

    # Booleans whose Odoo default is True. `ir.config_parameter.set_param` deletes
    # the row for a False value, which would make "explicitly off" indistinguishable
    # from "never configured" and silently re-enable them. Store them as strings.
    _CLAUDE_EXPLICIT_BOOL_PARAMS = {
        "centric_claude_enabled": "centric_claude.enabled",
        "centric_claude_code_read_enabled": "centric_claude.code_read_enabled",
        "centric_claude_code_write_enabled": "centric_claude.code_write_enabled",
        "centric_claude_data_enabled": "centric_claude.data_enabled",
        "centric_claude_attachments_enabled": "centric_claude.attachments_enabled",
        "centric_claude_pull_request_enabled": "centric_claude.pull_request_enabled",
    }

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        for field_name, key in self._CLAUDE_EXPLICIT_BOOL_PARAMS.items():
            params.set_param(key, "True" if self[field_name] else "False")

    def action_generate_agent_token(self):
        """Mint a fresh bridge token. Shown once; the developer copies it out."""
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        self.centric_claude_agent_token = token
        self.env["ir.config_parameter"].sudo().set_param(
            "centric_claude.agent_token", token
        )
        # Sticky: the field itself is masked, so this popup is the only chance to
        # copy the token. Losing it means generating a new one.
        return self._notification(
            _("Agent Token Generated"),
            _("Copy this now - it is not shown again:\n\n%s") % token,
            sticky=True,
        )

    def action_test_claude_connection(self):
        self.ensure_one()
        client = self.env["centric.claude.client"]
        result = client._test_connection(
            api_key=self.centric_claude_api_key,
            model=self.centric_claude_model,
        )
        self.env["centric.claude.audit.log"].sudo().create({
            "action": "settings_test",
            "repository": self._repository_label(),
            "details": _("Anthropic connection test succeeded."),
            "success": True,
        })
        return self._notification(_("Claude Connection Successful"), result)

    def action_test_github_connection(self):
        self.ensure_one()
        if not self.centric_claude_github_owner or not self.centric_claude_github_repo:
            raise UserError(_("Set the GitHub owner and repository first."))
        result = self.env["centric.claude.github.client"]._test_connection(
            owner=self.centric_claude_github_owner,
            repo=self.centric_claude_github_repo,
            token=self.centric_claude_github_token,
            branch=self.centric_claude_default_branch,
        )
        self.env["centric.claude.audit.log"].sudo().create({
            "action": "settings_test",
            "repository": self._repository_label(),
            "details": _("GitHub connection test succeeded."),
            "success": True,
        })
        return self._notification(_("GitHub Connection Successful"), result)

    def _repository_label(self):
        if self.centric_claude_github_owner and self.centric_claude_github_repo:
            return f"{self.centric_claude_github_owner}/{self.centric_claude_github_repo}"
        return False

    def _notification(self, title, message, sticky=False):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": "success",
                "sticky": sticky,
            },
        }
