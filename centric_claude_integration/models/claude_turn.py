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
    effort = fields.Char(
        help="Snapshot of the conversation's effort level when the turn was queued.",
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

    # How recently a bridge must have polled to count as connected. It polls
    # every few seconds while busy and every 15 while idle, so a minute is
    # comfortably longer than a healthy gap.
    HEARTBEAT_SECONDS = 60

    @api.model
    def _claim_next(self, agent_name=None, logins=None):
        """Take the oldest pending turn, atomically. Empty recordset if none.

        Reading a pending row and then writing "running" is two steps, and two
        bridges polling at the same moment both pass the read before either
        writes - so the same question gets answered twice, on two machines,
        from two checkouts. SKIP LOCKED is the standard queue primitive: each
        caller takes a row nobody else has locked, instead of colliding on the
        same one.

        `logins` restricts a bridge to particular people, so a team can run one
        bridge each without answering each other's questions.
        """
        domain = [("state", "=", "pending")]
        if logins:
            domain.append(("user_id.login", "in", list(logins)))
        # Narrow with the ORM first, so record rules and the login filter apply,
        # then lock within that set.
        candidates = self.search(domain, order="id asc", limit=50)
        if not candidates:
            return self.browse(())

        turn = self.browse(())
        try:
            self.env.cr.execute(
                "SELECT id FROM centric_claude_turn "
                "WHERE id IN %s AND state = 'pending' "
                "ORDER BY id ASC FOR UPDATE SKIP LOCKED LIMIT 1",
                (tuple(candidates.ids),),
            )
            row = self.env.cr.fetchone()
            if row:
                turn = self.browse(row[0])
        except Exception:  # noqa: BLE001
            # No SQL cursor (or a database without SKIP LOCKED): fall back to
            # the plain read. Still correct for a single bridge, which is the
            # common case; only concurrent bridges need the lock.
            turn = candidates[:1]

        if not turn:
            return self.browse(())
        turn.write({
            "state": "running",
            "agent_name": (agent_name or "bridge")[:120],
            "claimed_at": fields.Datetime.now(),
        })
        return turn

    @api.model
    def _queue_position(self, turn):
        """How many pending turns are ahead of this one."""
        if not turn or turn.state != "pending":
            return 0
        return self.sudo().search_count([
            ("state", "=", "pending"), ("id", "<", turn.id),
        ])

    @api.model
    def _record_heartbeat(self, agent_name=None):
        """Note that a bridge just polled.

        Written at most every 20 seconds: a poll happens every few seconds and
        this would otherwise be a database write per poll, all day.
        """
        params = self.env["ir.config_parameter"].sudo()
        now = fields.Datetime.now()
        last = params.get_param("centric_claude.agent_last_seen")
        if last:
            try:
                previous = fields.Datetime.from_string(last)
                if previous and (now - previous).total_seconds() < 20:
                    return
            except (TypeError, ValueError):
                pass
        params.set_param("centric_claude.agent_last_seen",
                         fields.Datetime.to_string(now))
        if agent_name:
            params.set_param("centric_claude.agent_name", agent_name[:120])

    @api.model
    def _agent_online(self):
        """(online, last_seen, name) for the local bridge."""
        params = self.env["ir.config_parameter"].sudo()
        raw = params.get_param("centric_claude.agent_last_seen")
        name = params.get_param("centric_claude.agent_name") or ""
        if not raw:
            return False, "", name
        try:
            last = fields.Datetime.from_string(raw)
        except (TypeError, ValueError):
            return False, "", name
        if not last:
            return False, "", name
        age = (fields.Datetime.now() - last).total_seconds()
        return age <= self.HEARTBEAT_SECONDS, raw, name

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
            "effort": self.effort or "high",
            "data_level": level["level"],
            "can_read_data": level["can_read"],
            "can_propose_data": level["can_propose"],
            "turn_id": self.id,
            "conversation_id": conversation.id,
            "conversation_name": conversation.name,
            # A project's standing instructions belong to every turn in it, so
            # the local agent gets the same context the hosted backend does.
            "project_name": conversation.project_id.name or "",
            "project_instructions": (conversation.project_id.instructions or "")[
                : self.env["centric.claude.project"].MAX_INSTRUCTIONS
            ],
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
