from odoo import fields, models


class CentricClaudeAuditLog(models.Model):
    _name = "centric.claude.audit.log"
    _description = "Claude Developer Audit Log"
    _order = "create_date desc, id desc"
    _rec_name = "action"

    action = fields.Selection(
        [
            ("chat", "Chat"),
            ("repo_read", "Repository Read"),
            ("code_stage", "Code Change Staged"),
            ("code_discard", "Code Change Discarded"),
            ("git_commit", "Git Commit"),
            ("pull_request", "Pull Request"),
            ("data_read", "Odoo Data Read"),
            ("data_propose", "Odoo Change Proposed"),
            ("data_apply", "Odoo Change Applied"),
            ("data_read", "Odoo Data Read"),
            ("data_propose", "Odoo Change Proposed"),
            ("data_apply", "Odoo Change Applied"),
            ("settings_test", "Connection Test"),
            ("security_denied", "Security Denied"),
        ],
        required=True,
        index=True,
    )
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, index=True)
    conversation_id = fields.Many2one("centric.claude.conversation", ondelete="set null", index=True)
    repository = fields.Char(index=True)
    branch = fields.Char(index=True)
    module_name = fields.Char(index=True)
    file_path = fields.Char(index=True)
    details = fields.Text()
    commit_sha = fields.Char(index=True)
    success = fields.Boolean(default=True, index=True)
