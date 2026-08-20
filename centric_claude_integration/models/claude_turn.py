from odoo import _, api, fields, models


class CentricClaudeTurn(models.Model):
    """One queued request for the local Claude Code agent.

    Odoo.sh cannot run the Claude Code CLI itself, so the developer's machine
    runs a small bridge that claims pending turns over HTTPS, executes them with
    `claude -p` against the local checkout, and posts the result back. This model
    is the queue: the browser creates a row, the bridge claims and completes it.
    """

    _name = "centric.claude.turn"
    _description = "Claude Agent Turn"
    _order = "id desc"

    conversation_id = fields.Many2one(
        "centric.claude.conversation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )
    prompt = fields.Text(required=True)
    state = fields.Selection(
        [
            ("pending", "Waiting for the agent"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    developer_mode = fields.Boolean(
        help="Snapshot of the conversation's Developer Mode when the turn was queued.",
    )
    base_branch = fields.Char()
    review_branch = fields.Char()
    agent_name = fields.Char(help="Identifies the bridge that claimed this turn.")
    claimed_at = fields.Datetime()
    finished_at = fields.Datetime()
    assistant_text = fields.Text()
    error = fields.Text()
    changed_file_count = fields.Integer(default=0)

    # A turn left running longer than this is assumed dead and can be re-claimed.
    CLAIM_TIMEOUT_MINUTES = 30

    @api.model
    def _reclaim_stale(self):
        """Return abandoned turns to the queue so a restarted bridge picks them up."""
        cutoff = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=self.CLAIM_TIMEOUT_MINUTES
        )
        stale = self.sudo().search([
            ("state", "=", "running"),
            ("claimed_at", "<", cutoff),
        ])
        if stale:
            stale.write({"state": "pending", "agent_name": False, "claimed_at": False})
        return stale

    def _payload_for_agent(self):
        """Everything the bridge needs to run this turn, and nothing more.

        Deliberately excludes every credential: the bridge authenticates with its
        own token and uses its own Claude Code login.
        """
        self.ensure_one()
        conversation = self.conversation_id
        history = conversation.message_ids.filtered(
            lambda msg: msg.role in {"user", "assistant"}
        ).sorted("id")[-30:]
        # The level travels with the turn: the tools the local agent may use
        # depend on the person who asked, not on the bridge.
        level = self.env['centric.claude.data'].with_user(
            self.user_id or self.env.user
        )._data_access()
        return {
            "data_level": level["level"],
            "can_read_data": level["can_read"],
            "can_propose_data": level["can_propose"],
            "turn_id": self.id,
            "conversation_id": conversation.id,
            "conversation_name": conversation.name,
            "prompt": self.prompt,
            "developer_mode": self.developer_mode,
            "base_branch": self.base_branch or "",
            "review_branch": self.review_branch or "",
            "allowed_module_prefix": conversation._param(
                "centric_claude.allowed_module_prefix", "centric_"
            ),
            "history": [
                {"role": message.role, "content": message.content}
                for message in history
            ],
        }

    def _fail(self, message):
        self.ensure_one()
        self.write({
            "state": "failed",
            "error": (message or _("The local Claude agent reported no detail."))[:4000],
            "finished_at": fields.Datetime.now(),
        })
