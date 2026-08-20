import hmac
import logging

from odoo import _, fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CentricClaudeAgentController(http.Controller):
    """HTTPS endpoints for the local Claude Code bridge.

    The bridge runs on the developer's machine and calls *out* to Odoo, so this
    works from behind NAT and needs no inbound port, no CORS and no browser
    permission for local network access.
    """

    _MAX_FILE_BYTES = 512000
    _MAX_FILES_PER_TURN = 40

    # -- authentication ---------------------------------------------------
    def _agent_check(self):
        """Resolve the bearer token to the Odoo user the bridge acts as.

        Returns (user, None) or (None, reason). The reasons are deliberately
        specific: a single "invalid token" for every cause is unusable when
        setting the bridge up, and each of these is an administrator-side
        configuration fact, not a secret. The token itself is compared with
        `compare_digest` so it cannot be recovered by timing the response.
        """
        params = request.env["ir.config_parameter"].sudo()
        expected = params.get_param("centric_claude.agent_token")
        if not expected:
            return None, ("No agent token is configured in Odoo. Go to Settings > "
                          "Centric Claude and click Generate Agent Token.")
        header = request.httprequest.headers.get("Authorization") or ""
        if not header.startswith("Bearer "):
            return None, "Request carried no 'Authorization: Bearer <token>' header."
        presented = header[len("Bearer "):].strip()
        if not presented or not hmac.compare_digest(presented, expected):
            return None, ("The token this bridge sent does not match the one stored in "
                          "Odoo. Generate a new token in Settings, Save, and restart the "
                          "bridge with that value.")
        uid = params.get_param("centric_claude.agent_uid")
        if not uid:
            return None, ("'Agent Runs As' is not set in Odoo. Settings > Centric Claude "
                          "> pick a user holding the Claude Developer group, then Save.")
        user = request.env["res.users"].sudo().browse(int(uid)).exists()
        if not user:
            return None, "The configured 'Agent Runs As' user no longer exists."
        return user, None

    def _agent_user(self):
        """Backwards-compatible accessor returning just the user, or None."""
        user, _reason = self._agent_check()
        return user

    def _denied(self, reason="Invalid or missing agent token."):
        _logger.warning("Centric Claude agent request rejected: %s", reason)
        return {"error": reason}

    # -- endpoints --------------------------------------------------------
    @http.route(
        "/centric_claude/agent/claim",
        type="json", auth="public", methods=["POST"], csrf=False,
    )
    def claim(self, agent_name=None, **kwargs):
        """Hand the oldest pending turn to the calling bridge."""
        user, reason = self._agent_check()
        if not user:
            return self._denied(reason)
        env = request.env(user=user.id)
        Turn = env["centric.claude.turn"].sudo()
        Turn._reclaim_stale()
        turn = Turn.search([("state", "=", "pending")], order="id asc", limit=1)
        if not turn:
            return {"turn": None}
        turn.write({
            "state": "running",
            "agent_name": (agent_name or "bridge")[:120],
            "claimed_at": fields.Datetime.now(),
        })
        return {"turn": turn._payload_for_agent()}

    @http.route(
        "/centric_claude/agent/complete",
        type="json", auth="public", methods=["POST"], csrf=False,
    )
    def complete(self, turn_id=None, assistant_text=None, changes=None, **kwargs):
        """Store the agent's reply and stage whatever files it changed."""
        user, reason = self._agent_check()
        if not user:
            return self._denied(reason)
        env = request.env(user=user.id)
        turn = env["centric.claude.turn"].sudo().browse(int(turn_id or 0)).exists()
        if not turn:
            return {"error": "Unknown turn."}
        if turn.state != "running":
            return {"error": "Turn %s is %s, not running." % (turn.id, turn.state)}

        conversation = turn.conversation_id
        changes = changes or []
        if len(changes) > self._MAX_FILES_PER_TURN:
            turn._fail(_("The agent returned %s changed files, over the limit of %s.")
                       % (len(changes), self._MAX_FILES_PER_TURN))
            return {"error": "Too many changed files."}

        staged, rejected = [], []
        if changes and turn.developer_mode:
            for change in changes:
                module_name = (change or {}).get("module")
                file_path = (change or {}).get("path")
                new_content = (change or {}).get("new_content")
                if not module_name or not file_path or new_content is None:
                    rejected.append({"path": file_path or "?", "reason": "Incomplete change."})
                    continue
                if len(new_content) > self._MAX_FILE_BYTES:
                    rejected.append({"path": file_path, "reason": "Over the 500 KB limit."})
                    continue
                try:
                    result = conversation.sudo(False)._stage_change(
                        module_name,
                        file_path,
                        new_content,
                        (change.get("summary") or "Changed by the local Claude agent"),
                    )
                except Exception as exc:  # noqa: BLE001 - one bad file must not lose the turn.
                    rejected.append({"path": file_path, "reason": str(exc)[:300]})
                    continue
                if result.get("staged"):
                    staged.append(file_path)
        elif changes and not turn.developer_mode:
            rejected = [{"path": (c or {}).get("path", "?"),
                         "reason": "Developer Mode was off for this turn."}
                        for c in changes]

        text = (assistant_text or "").strip() or _("The agent returned no text.")
        notes = []
        if staged:
            notes.append(_("Staged %s file(s) for review: %s")
                         % (len(staged), ", ".join(staged)))
        for item in rejected:
            notes.append(_("Not staged - %(path)s: %(reason)s") % item)
        if notes:
            text = text + "\n\n" + "\n".join(notes)

        env["centric.claude.message"].sudo().create({
            "conversation_id": conversation.id,
            "role": "assistant",
            "content": text,
        })
        turn.write({
            "state": "done",
            "assistant_text": text,
            "changed_file_count": len(staged),
            "finished_at": fields.Datetime.now(),
        })
        conversation.sudo()._audit(
            "chat",
            details=_("Local Claude agent turn completed (%s file(s) staged).") % len(staged),
            success=not rejected,
        )
        return {"ok": True, "staged": staged, "rejected": rejected}

    @http.route(
        "/centric_claude/agent/fail",
        type="json", auth="public", methods=["POST"], csrf=False,
    )
    def fail(self, turn_id=None, error=None, **kwargs):
        """Record that the agent could not complete a turn."""
        user, reason = self._agent_check()
        if not user:
            return self._denied(reason)
        env = request.env(user=user.id)
        turn = env["centric.claude.turn"].sudo().browse(int(turn_id or 0)).exists()
        if not turn:
            return {"error": "Unknown turn."}
        message = (error or "").strip() or _("The local Claude agent failed.")
        turn._fail(message)
        env["centric.claude.message"].sudo().create({
            "conversation_id": turn.conversation_id.id,
            "role": "assistant",
            "content": _("The local Claude agent could not complete this request:\n\n%s")
            % message[:2000],
        })
        turn.conversation_id.sudo()._audit(
            "chat", details=message[:500], success=False
        )
        return {"ok": True}

    @http.route(
        "/centric_claude/agent/ping",
        type="json", auth="public", methods=["POST"], csrf=False,
    )
    def ping(self, **kwargs):
        """Let the bridge verify its token and URL before it starts polling."""
        user, reason = self._agent_check()
        if not user:
            return self._denied(reason)
        env = request.env(user=user.id)
        params = env["ir.config_parameter"].sudo()
        # Surface the config faults that otherwise only show up as a silently
        # rejected change, long after the bridge said it was connected.
        warnings = []
        if not user.has_group("centric_claude_integration.group_claude_developer"):
            warnings.append(
                "'%s' does not hold the Claude Developer group, so any change this "
                "agent sends back will be refused." % user.name
            )
        conversation = env["centric.claude.conversation"]
        if not conversation._bool_param("centric_claude.code_write_enabled", False):
            warnings.append(
                "'Allow Code Modifications' is off in Settings, so Developer Mode "
                "cannot be enabled and no change can be staged."
            )
        if not params.get_param("centric_claude.github_token"):
            warnings.append(
                "No GitHub token is set, so committing reviewed changes will fail."
            )
        return {
            "ok": True,
            "user": user.name,
            "repository": "%s/%s" % (
                params.get_param("centric_claude.github_owner") or "?",
                params.get_param("centric_claude.github_repo") or "?",
            ),
            "branch": params.get_param("centric_claude.default_branch") or "?",
            "warnings": warnings,
            "pending": env["centric.claude.turn"].sudo().search_count(
                [("state", "=", "pending")]
            ),
        }
