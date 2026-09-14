import base64
import binascii

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class CentricClaudeAttachment(models.Model):
    """An image a user attached to one chat message.

    Images only, on purpose: a screenshot of an error is what people actually
    want to send, and it is the one format both backends handle well. Documents
    would mean a second delivery path for a much smaller gain.

    The bytes end up on a developer's workstation - the local agent can only
    read a file that is really on its disk - so the claimed content type is
    never trusted. `_sniff` decides what a file is from its own leading bytes,
    and anything that is not a recognised image is refused outright.
    """

    _name = "centric.claude.attachment"
    _description = "Claude Chat Attachment"
    _order = "id asc"

    # Leading bytes -> (mimetype, extension). WebP needs a second check because
    # every RIFF container starts the same way.
    _SIGNATURES = (
        (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
        (b"\xff\xd8\xff", "image/jpeg", "jpg"),
        (b"GIF87a", "image/gif", "gif"),
        (b"GIF89a", "image/gif", "gif"),
    )

    DEFAULT_MAX_MB = 5
    MAX_PER_MESSAGE = 5
    DEFAULT_RETENTION_DAYS = 30
    # How many images from earlier in a conversation Claude still gets to see.
    # Enough that "the screenshot I sent before" works, bounded so a long thread
    # does not re-send a gallery on every single turn.
    HISTORY_IMAGE_LIMIT = 8
    MAX_NAME = 200

    conversation_id = fields.Many2one(
        "centric.claude.conversation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    # Null between upload and send: the composer uploads first, then the message
    # that owns them is created.
    message_id = fields.Many2one(
        "centric.claude.message",
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )
    name = fields.Char(required=True)
    mimetype = fields.Char(required=True, readonly=True)
    # attachment=True keeps the bytes in the filestore rather than the database.
    datas = fields.Binary(attachment=True, required=True)
    file_size = fields.Integer(readonly=True)

    # ------------------------------------------------------------- settings
    @api.model
    def _enabled(self):
        return self.env["centric.claude.conversation"]._bool_param(
            "centric_claude.attachments_enabled", True
        )

    @api.model
    def _max_bytes(self):
        raw = self.env["centric.claude.conversation"]._param(
            "centric_claude.attachment_max_mb", str(self.DEFAULT_MAX_MB)
        )
        try:
            megabytes = float(raw)
        except (TypeError, ValueError):
            megabytes = self.DEFAULT_MAX_MB
        megabytes = min(max(megabytes, 0.1), 32)
        return int(megabytes * 1024 * 1024)

    @api.model
    def _retention_days(self):
        raw = self.env["centric.claude.conversation"]._param(
            "centric_claude.attachment_retention_days", str(self.DEFAULT_RETENTION_DAYS)
        )
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return self.DEFAULT_RETENTION_DAYS

    # -------------------------------------------------------------- helpers
    @api.model
    def _sniff(self, raw):
        """(mimetype, extension) from the bytes themselves, or (False, False).

        The uploader's claimed type is ignored entirely. These bytes are written
        to a developer's disk with an extension derived from this answer, so a
        script announcing itself as a PNG must not be able to land as one.
        """
        for signature, mimetype, extension in self._SIGNATURES:
            if raw.startswith(signature):
                return mimetype, extension
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            return "image/webp", "webp"
        return False, False

    def _check_owner(self):
        self.ensure_one()
        if self.user_id != self.env.user and not self.env.user.has_group(
            "centric_claude_integration.group_claude_admin"
        ):
            raise AccessError(_("You can only use your own attachments."))

    def _summary(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "mimetype": self.mimetype,
            "file_size": self.file_size,
            # Odoo's own binary route, so the record rules decide who sees it.
            "url": "/web/image/centric.claude.attachment/%s/datas" % self.id,
        }

    def _image_block(self):
        """One Anthropic image content block, for the hosted API backend."""
        self.ensure_one()
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self.mimetype,
                "data": (self.datas or b"").decode() if isinstance(self.datas, bytes)
                        else (self.datas or ""),
            },
        }

    def _agent_summary(self):
        """What the bridge needs to decide whether to download this one."""
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "mimetype": self.mimetype,
            "file_size": self.file_size,
        }

    # ------------------------------------------------------------ workspace
    @api.model
    def upload_workspace_attachment(self, conversation_id, name, data):
        """Store one pasted or picked image, unattached to a message yet."""
        conversation = self.env["centric.claude.conversation"].browse(
            int(conversation_id)
        ).exists()
        if not conversation:
            raise UserError(_("Claude conversation not found."))
        conversation._check_owner()
        if not self._enabled():
            raise UserError(_("Attachments are switched off in the Claude settings."))

        try:
            raw = base64.b64decode(data or "", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError(_("That file could not be read.")) from exc
        if not raw:
            raise ValidationError(_("That file is empty."))

        limit = self._max_bytes()
        if len(raw) > limit:
            raise ValidationError(_(
                "Images are limited to %(limit)s MB. That one is %(size)s MB."
            ) % {
                "limit": round(limit / 1024 / 1024, 1),
                "size": round(len(raw) / 1024 / 1024, 1),
            })

        mimetype, extension = self._sniff(raw)
        if not mimetype:
            raise ValidationError(_(
                "Only PNG, JPEG, GIF and WebP images can be attached."
            ))

        # Already waiting to be sent, plus this one.
        pending = self.search_count([
            ("conversation_id", "=", conversation.id),
            ("message_id", "=", False),
            ("user_id", "=", self.env.user.id),
        ])
        if pending >= self.MAX_PER_MESSAGE:
            raise ValidationError(_(
                "Up to %s images can be sent with one message."
            ) % self.MAX_PER_MESSAGE)

        clean_name = (name or "").strip()[:self.MAX_NAME] or _("pasted image")
        if "." not in clean_name.rsplit("/", 1)[-1]:
            clean_name = "%s.%s" % (clean_name, extension)

        attachment = self.create({
            "conversation_id": conversation.id,
            "user_id": self.env.user.id,
            "name": clean_name,
            "mimetype": mimetype,
            "datas": base64.b64encode(raw).decode(),
            "file_size": len(raw),
        })
        return attachment._summary()

    @api.model
    def discard_workspace_attachment(self, attachment_id):
        """Remove one image that has not been sent yet."""
        attachment = self.browse(int(attachment_id)).exists()
        if not attachment:
            return True
        attachment._check_owner()
        if attachment.message_id:
            raise UserError(_(
                "That image has already been sent and cannot be removed."
            ))
        attachment.unlink()
        return True

    @api.model
    def _pending_for(self, conversation, attachment_ids=None):
        """The unsent images of `conversation` belonging to the current user.

        Restricted to unsent ones so a replayed request cannot re-attach an
        image from an older message to a new one.
        """
        domain = [
            ("conversation_id", "=", conversation.id),
            ("message_id", "=", False),
            ("user_id", "=", self.env.user.id),
        ]
        # `None` means "whatever is waiting", which is what a caller that knows
        # nothing about attachments wants. An empty list is a caller that does
        # know and is saying none - it must not quietly pick up a leftover.
        if attachment_ids is not None:
            domain.append(("id", "in", [int(item) for item in attachment_ids]))
        return self.search(domain, order="id asc", limit=self.MAX_PER_MESSAGE)

    # -------------------------------------------------------------- cleanup
    @api.model
    def _gc_workspace_attachments(self):
        """Delete images older than the retention setting. Run by ir.cron.

        Deliberately independent of the conversation: a transcript is cheap to
        keep, a year of screenshots is not.
        """
        days = self._retention_days()
        if days <= 0:
            return 0
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        stale = self.sudo().search([("create_date", "<", cutoff)])
        count = len(stale)
        if stale:
            stale.unlink()
        return count
