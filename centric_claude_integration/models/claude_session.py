import base64
import binascii
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CentricClaudeSessionConversation(models.Model):
    """Claude Code's own saved session for a conversation, kept in Odoo.

    Claude Code writes every session to a `.jsonl` file and can pick it up
    again with `--resume`, which gives the next turn everything the last one
    had: the messages, and also the files it read and what its tools
    returned. The bridge would otherwise start from nothing each turn and
    replay the last ten messages as text.

    The file lives here rather than only on the bridge machine so that it
    survives that machine being cleaned or replaced, another developer's
    bridge picking the conversation up, and a database restore. The bridge
    keeps a working copy and treats this one as the truth: it downloads when
    its copy is missing or differs, and uploads after every successful turn.

    The bytes are gzip-compressed and stored with `attachment=True`, so they
    sit in the filestore like the chat images do, and the database row only
    holds a reference. The session holds everything Claude read, database
    records included, so the data field is not readable over ordinary RPC -
    only the agent controller, working for the turn's own conversation,
    reaches it.
    """

    _inherit = "centric.claude.conversation"

    DEFAULT_SESSION_RETENTION_DAYS = 30
    DEFAULT_SESSION_MAX_MB = 5.0
    _SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    _SHA256 = re.compile(r"^[0-9a-f]{64}$")

    agent_session_id = fields.Char(copy=False, readonly=True)
    agent_session_data = fields.Binary(
        attachment=True, copy=False, readonly=True, groups="base.group_system",
    )
    # Of the uncompressed file, which is what the bridge can hash cheaply to
    # tell whether its own copy is still the current one.
    agent_session_sha = fields.Char(copy=False, readonly=True)
    agent_session_size = fields.Integer(
        copy=False, readonly=True, help="Compressed size of the saved session, in bytes.",
    )
    agent_session_updated = fields.Datetime(copy=False, readonly=True, index=True)

    # ---------------------------------------------------------------- settings
    @api.model
    def _session_retention_days(self):
        raw = self._param(
            "centric_claude.session_retention_days", str(self.DEFAULT_SESSION_RETENTION_DAYS)
        )
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return self.DEFAULT_SESSION_RETENTION_DAYS

    @api.model
    def _session_max_bytes(self):
        raw = self._param("centric_claude.session_max_mb", str(self.DEFAULT_SESSION_MAX_MB))
        try:
            megabytes = float(raw)
        except (TypeError, ValueError):
            megabytes = self.DEFAULT_SESSION_MAX_MB
        return int(max(0.0, megabytes) * 1024 * 1024)

    # ------------------------------------------------------------------- store
    def _store_agent_session(self, session_id, data, sha):
        """Keep the bridge's session file for this conversation.

        Returns {"stored": bool, "reason": str}. A session over the size cap is
        not kept, and any older one is dropped with it: resuming the previous
        version would silently lose the turn that made the file grow, which is
        worse than the next turn starting afresh from the transcript.
        """
        self.ensure_one()
        session_id = (session_id or "").strip().lower()
        sha = (sha or "").strip().lower()
        if not self._SESSION_ID.match(session_id):
            raise UserError(_("That is not a Claude Code session id."))
        if not self._SHA256.match(sha):
            raise UserError(_("The session checksum is malformed."))
        try:
            raw = base64.b64decode(data or "", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise UserError(_("The session file is not valid base64.")) from exc
        # gzip's magic bytes: refuse anything the bridge did not compress,
        # rather than store an arbitrary blob under a session's name.
        if raw[:2] != b"\x1f\x8b":
            raise UserError(_("The session file is not gzip-compressed."))

        limit = self._session_max_bytes()
        if limit and len(raw) > limit:
            self._clear_agent_session()
            return {"stored": False, "reason": "too_large"}

        self.sudo().write({
            "agent_session_id": session_id,
            "agent_session_data": base64.b64encode(raw),
            "agent_session_sha": sha,
            "agent_session_size": len(raw),
            "agent_session_updated": fields.Datetime.now(),
        })
        return {"stored": True, "reason": ""}

    def _agent_session_payload(self):
        """The saved session for the bridge to download, or an empty result."""
        self.ensure_one()
        record = self.sudo()
        if not record.agent_session_id or not record.agent_session_data:
            return {"session_id": False}
        data = record.agent_session_data
        return {
            "session_id": record.agent_session_id,
            "sha": record.agent_session_sha or "",
            "data": data.decode() if isinstance(data, bytes) else data,
        }

    def _clear_agent_session(self):
        self.sudo().write({
            "agent_session_id": False,
            "agent_session_data": False,
            "agent_session_sha": False,
            "agent_session_size": 0,
            "agent_session_updated": False,
        })

    # --------------------------------------------------------------------- gc
    @api.model
    def _gc_agent_sessions(self):
        """Drop saved sessions untouched for longer than the retention setting.

        Only the session goes. The messages stay, and a later turn on the same
        conversation starts a fresh session from them - the session is most of
        the storage and all of the part that can be rebuilt.
        """
        days = self._session_retention_days()
        if days <= 0:
            return 0
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        stale = self.sudo().search([
            ("agent_session_id", "!=", False),
            ("agent_session_updated", "<", cutoff),
        ])
        if stale:
            stale._clear_agent_session()
        return len(stale)
