import ast
import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class CentricClaudeData(models.AbstractModel):
    """Read and change ordinary Odoo records on behalf of a Claude conversation.

    Two independent gates apply to everything here, and neither is allowed to
    stand in for the other:

    1. The Claude data level (none / user / intermediate / admin) decides which
       *kinds* of operation are offered at all.
    2. Odoo's own access rights and record rules decide what the *requesting
       user* may actually see or touch.

    Nothing in this file uses sudo() for business records. That is deliberate:
    an assistant that reads with elevated rights would happily show a warehouse
    clerk the payroll, and no amount of prompt wording prevents that. The one
    place sudo appears is reading schema metadata from ir.model, which every
    user can already see through the ORM anyway.
    """

    _name = "centric.claude.data"
    _description = "Centric Claude Odoo Data Access"

    # -- limits -----------------------------------------------------------
    DEFAULT_LIMIT = 40
    MAX_LIMIT = 200
    MAX_FIELDS = 40
    MAX_AUTO_FIELDS = 14
    MAX_VALUE_CHARS = 2000
    MAX_WRITE_RECORDS = 50

    # -- what is never readable, at any level -----------------------------
    # These hold credentials outright. ir.config_parameter is the sharpest of
    # them: this module keeps its own Anthropic key, GitHub token and agent
    # token there, so exposing it would hand over the keys to the integration.
    SECRET_MODELS = frozenset({
        "ir.config_parameter",
        "ir.mail_server",
        "fetchmail.server",
        "res.users.apikeys",
        "res.users.apikeys.description",
        "auth_totp.device",
        "iap.account",
        "ir.logging",
    })

    # Substrings that mark a field as a credential whatever model it sits on,
    # including custom modules this code has never seen.
    SECRET_FIELD_HINTS = (
        "password", "passwd", "secret", "token", "api_key", "apikey",
        "private_key", "privatekey", "credential", "totp", "otp_", "_otp",
        "signature_key", "webhook_key", "access_token",
    )

    # -- what may be changed ----------------------------------------------
    # Intermediate is blocked from configuration, security and technical
    # models. Everything else - the ordinary business documents people work
    # with all day, accounting entries included - is allowed. A blocklist beats
    # an allowlist here because an Odoo database always carries custom models
    # this module cannot know about, and those are exactly the business objects
    # the assistant is meant to help with.
    CONFIG_WRITE_PREFIXES = (
        "ir.", "base_automation", "res.config", "res.groups", "res.users",
        "res.company", "res.currency", "res.lang", "mail.template",
        "account.account", "account.journal", "account.tax",
        "account.fiscal.position", "account.reconcile.model",
        "account.report", "account.root", "account.group",
        "product.pricelist", "stock.warehouse", "stock.location",
        "uom.", "digest.", "iap.",
    )

    # Never writable, even for an administrator. Claude must not be able to
    # rewrite the rules that constrain Claude.
    NEVER_WRITE_PREFIXES = ("centric.claude.", "ir.config_parameter", "ir.rule",
                            "ir.model.access")

    # ------------------------------------------------------------------ level
    @api.model
    def _level(self, user=None):
        """The calling user's Claude data level."""
        user = user or self.env.user
        if user.has_group("centric_claude_integration.group_data_admin"):
            return "admin"
        if user.has_group("centric_claude_integration.group_data_intermediate"):
            return "intermediate"
        if user.has_group("centric_claude_integration.group_data_user"):
            return "user"
        return "none"

    @api.model
    def _level_label(self, level=None):
        return {
            "none": _("No database access"),
            "user": _("User - read only"),
            "intermediate": _("Intermediate - business documents"),
            "admin": _("Administrator - full access"),
        }.get(level or self._level(), _("No database access"))

    @api.model
    def _data_access(self):
        level = self._level()
        enabled = self.env["centric.claude.conversation"]._bool_param(
            "centric_claude.data_enabled", True
        )
        return {
            "level": level if enabled else "none",
            "level_label": self._level_label(level if enabled else "none"),
            "can_read": enabled and level in ("user", "intermediate", "admin"),
            "can_propose": enabled and level in ("intermediate", "admin"),
            "can_propose_anything": enabled and level == "admin",
        }

    # ------------------------------------------------------------- guards
    @api.model
    def _require_read(self, model_name):
        access = self._data_access()
        if not access["can_read"]:
            raise AccessError(_(
                "You do not have a Claude data level, so Claude cannot look at "
                "Odoo records for you. An administrator sets this on your user "
                "under Centric Claude Data."
            ))
        model_name = (model_name or "").strip()
        if not model_name:
            raise UserError(_("No model was given."))
        if model_name in self.SECRET_MODELS:
            raise AccessError(_(
                "'%s' holds credentials and is never readable through Claude."
            ) % model_name)
        if model_name not in self.env:
            raise UserError(_("There is no model called '%s' in this database.") % model_name)
        # The ORM raises on the first read otherwise; failing here gives a
        # message that says which model and why.
        if not self.env[model_name].has_access("read"):
            raise AccessError(_(
                "Your Odoo account cannot read '%s', so Claude cannot either."
            ) % model_name)
        return self.env[model_name]

    @api.model
    def _require_write(self, model_name, operation="write"):
        access = self._data_access()
        if not access["can_propose"]:
            raise AccessError(_(
                "Your Claude data level is read-only. Changing Odoo records "
                "needs the Intermediate or Administrator level."
            ))
        if (model_name or "").startswith(self.NEVER_WRITE_PREFIXES):
            raise AccessError(_(
                "'%s' controls how Claude itself is permitted to act, so Claude "
                "is never allowed to change it."
            ) % model_name)
        if not access["can_propose_anything"] and (model_name or "").startswith(
            self.CONFIG_WRITE_PREFIXES
        ):
            raise AccessError(_(
                "'%(model)s' is configuration or security, which the "
                "Intermediate level cannot change. This needs the Administrator "
                "level."
            ) % {"model": model_name})
        record_model = self._require_read(model_name)
        if not record_model.has_access(operation):
            raise AccessError(_(
                "Your Odoo account cannot %(op)s '%(model)s', so Claude cannot "
                "propose it."
            ) % {"op": operation, "model": model_name})
        return record_model

    # -------------------------------------------------------------- fields
    @api.model
    def _is_secret_field(self, name, field):
        lowered = name.lower()
        if any(hint in lowered for hint in self.SECRET_FIELD_HINTS):
            return True
        # A field restricted to groups this user is not in. Odoo would raise on
        # read; excluding it here turns that into a quietly narrower answer
        # rather than a failed query.
        restricted = getattr(field, "groups", None)
        if restricted:
            wanted = [part.strip() for part in str(restricted).split(",") if part.strip()]
            return not any(self.env.user.has_group(group) for group in wanted)
        return False

    @api.model
    def _readable_fields(self, record_model):
        """Field names this user may see, minus credentials and binary blobs."""
        return {
            name: field
            for name, field in record_model._fields.items()
            # Base64 blobs are useless in a chat answer and enormous in a prompt.
            if field.type != "binary" and not self._is_secret_field(name, field)
        }

    @api.model
    def _auto_fields(self, record_model):
        """A useful default field set when the caller did not name any."""
        available = self._readable_fields(record_model)
        preferred = [
            "display_name", "name", "complete_name", "reference", "code",
            "state", "stage_id", "partner_id", "user_id", "team_id",
            "date", "date_order", "invoice_date", "date_deadline",
            "create_date", "amount_total", "amount_residual", "currency_id",
            "company_id", "priority", "active",
        ]
        chosen = [name for name in preferred if name in available]
        for name in available:
            if len(chosen) >= self.MAX_AUTO_FIELDS:
                break
            field = available[name]
            if name in chosen or name.startswith("_"):
                continue
            if field.type in ("one2many", "many2many", "html", "text"):
                continue
            if not field.store:
                continue
            chosen.append(name)
        return chosen[: self.MAX_AUTO_FIELDS] or ["display_name"]

    @api.model
    def _clean_value(self, value):
        """Make one ORM value safe and small enough to put in a prompt."""
        if isinstance(value, bytes):
            return "<binary>"
        if isinstance(value, str) and len(value) > self.MAX_VALUE_CHARS:
            return value[: self.MAX_VALUE_CHARS] + "... (truncated)"
        if isinstance(value, (list, tuple)):
            if len(value) > 50:
                return list(value[:50]) + ["... (%s more)" % (len(value) - 50)]
            return list(value)
        return value

    # -------------------------------------------------------------- domain
    @api.model
    def _parse_domain(self, domain):
        if domain in (None, "", False):
            return []
        if isinstance(domain, str):
            try:
                # literal_eval, never eval: a domain arriving as text must not
                # be able to execute anything.
                domain = ast.literal_eval(domain)
            except (ValueError, SyntaxError) as exc:
                raise UserError(_(
                    "That search filter is not a valid Odoo domain: %s"
                ) % domain) from exc
        if not isinstance(domain, (list, tuple)):
            raise UserError(_("A search filter must be a list of conditions."))
        return list(domain)

    # --------------------------------------------------------------- reads
    @api.model
    def search_records(self, model_name, domain=None, field_names=None,
                       limit=None, order=None):
        record_model = self._require_read(model_name)
        domain = self._parse_domain(domain)
        limit = max(1, min(int(limit or self.DEFAULT_LIMIT), self.MAX_LIMIT))
        available = self._readable_fields(record_model)
        if field_names:
            requested = [name for name in field_names[: self.MAX_FIELDS]]
            missing = [name for name in requested if name not in available]
            if missing:
                raise UserError(_(
                    "These fields do not exist on %(model)s or are not "
                    "readable: %(fields)s"
                ) % {"model": model_name, "fields": ", ".join(missing)})
            chosen = requested
        else:
            chosen = self._auto_fields(record_model)

        try:
            records = record_model.search(domain, limit=limit, order=order or None)
        except (ValueError, TypeError, KeyError) as exc:
            raise UserError(_("That search could not be run: %s") % exc) from exc
        rows = records.read(chosen) if records else []
        total = record_model.search_count(domain)
        return {
            "model": model_name,
            "total_matching": total,
            "returned": len(rows),
            "truncated": total > len(rows),
            "fields": chosen,
            "records": [
                {key: self._clean_value(value) for key, value in row.items()}
                for row in rows
            ],
        }

    @api.model
    def read_record(self, model_name, record_id, field_names=None):
        record_model = self._require_read(model_name)
        record = record_model.browse(int(record_id)).exists()
        if not record:
            raise UserError(_("There is no %(model)s with id %(id)s, or you "
                              "cannot see it.") % {"model": model_name, "id": record_id})
        available = self._readable_fields(record_model)
        if field_names:
            chosen = [name for name in field_names[: self.MAX_FIELDS] if name in available]
        else:
            chosen = [
                name for name, field in available.items()
                if field.store and field.type not in ("one2many", "many2many")
            ][: self.MAX_FIELDS]
        row = record.read(chosen)[0]
        return {
            "model": model_name,
            "id": record.id,
            "display_name": record.display_name,
            "values": {key: self._clean_value(value) for key, value in row.items()},
        }

    @api.model
    def count_records(self, model_name, domain=None):
        record_model = self._require_read(model_name)
        return {
            "model": model_name,
            "count": record_model.search_count(self._parse_domain(domain)),
        }

    @api.model
    def find_models(self, query=None, limit=40):
        """Locate models by technical or human name, e.g. "helpdesk" or "invoice"."""
        self._require_read("ir.model")
        query = (query or "").strip()
        domain = []
        if query:
            domain = ["|", ("model", "ilike", query), ("name", "ilike", query)]
        # ir.model is schema metadata every user can already list through the
        # ORM; sudo here only avoids a needless per-database rights quirk.
        models_found = self.env["ir.model"].sudo().search(
            domain, limit=max(1, min(int(limit or 40), 100)), order="model"
        )
        out = []
        for record in models_found:
            if record.model in self.SECRET_MODELS:
                continue
            if not self.env[record.model].has_access("read"):
                continue
            out.append({
                "model": record.model,
                "name": record.name,
                "can_read": True,
                "can_write": self.env[record.model].has_access("write"),
                "transient": bool(record.transient),
            })
        return {"query": query, "models": out}

    @api.model
    def describe_model(self, model_name):
        # A model that simply is not installed is an answer, not a failure:
        # Claude should try another name rather than lose the turn. A blocked
        # or forbidden model still raises, so a refusal is never disguised as
        # "not found".
        if (model_name or "").strip() and (model_name or "").strip() not in self.env:
            self._require_read("ir.model")
            return {"found": False, "model": model_name,
                    "hint": _("No such model. Use find_odoo_models to look one up.")}
        record_model = self._require_read(model_name)
        available = self._readable_fields(record_model)
        described = []
        for name, field in list(available.items())[:150]:
            entry = {
                "name": name,
                "type": field.type,
                "label": field.string,
                "required": bool(field.required),
                "readonly": bool(field.readonly),
                "stored": bool(field.store),
            }
            if field.type in ("many2one", "one2many", "many2many"):
                entry["relation"] = field.comodel_name
            if field.type == "selection":
                try:
                    selection = field.selection
                    if callable(selection):
                        selection = selection(record_model)
                    entry["options"] = [key for key, _label in (selection or [])][:40]
                except Exception:  # noqa: BLE001 - a dynamic selection may need a record.
                    entry["options"] = []
            described.append(entry)
        return {
            "found": True,
            "model": model_name,
            "label": record_model._description,
            "record_count": record_model.search_count([]),
            "can_write": record_model.has_access("write"),
            "can_create": record_model.has_access("create"),
            "fields": described,
            "hidden_field_count": len(record_model._fields) - len(available),
        }

    # ---------------------------------------------------------- previewing
    @api.model
    def _describe_values(self, record_model, values):
        """Turn raw write values into something a person can check at a glance."""
        lines = []
        for key, value in (values or {}).items():
            field = record_model._fields.get(key)
            if not field:
                lines.append("%s = %s  (no such field)" % (key, value))
                continue
            if self._is_secret_field(key, field):
                lines.append("%s = <refused: credential field>" % key)
                continue
            label = field.string or key
            shown = value
            if field.type == "many2one" and value:
                try:
                    target = self.env[field.comodel_name].browse(int(value)).exists()
                    shown = "%s (id %s)" % (target.display_name, value) if target else value
                except (ValueError, TypeError, KeyError):
                    shown = value
            lines.append("%s (%s) = %s" % (label, key, shown))
        return "\n".join(lines) or _("No values.")

    @api.model
    def _validate_values(self, record_model, values):
        """Reject unknown and credential fields before anything is proposed."""
        if not isinstance(values, dict):
            raise UserError(_("The values for a change must be given as an object."))
        for key in values:
            field = record_model._fields.get(key)
            if not field:
                raise UserError(_(
                    "'%(field)s' is not a field on %(model)s."
                ) % {"field": key, "model": record_model._name})
            if self._is_secret_field(key, field):
                raise AccessError(_(
                    "'%s' is a credential field and can never be set through Claude."
                ) % key)
        return values


class CentricClaudeOperation(models.Model):
    """A change to Odoo data that Claude proposes and a person approves.

    Claude never writes to the database directly. It records what it intends to
    do here; the change happens only when the user presses Apply, and it is
    executed with that user's own rights.
    """

    _name = "centric.claude.operation"
    _description = "Claude Proposed Data Change"
    _order = "id desc"

    conversation_id = fields.Many2one(
        "centric.claude.conversation", required=True, ondelete="cascade", index=True
    )
    user_id = fields.Many2one(
        "res.users", required=True, index=True,
        default=lambda self: self.env.user,
        help="Whose permissions this change will be carried out with.",
    )
    kind = fields.Selection(
        [("create", "Create"), ("write", "Update"), ("unlink", "Delete"),
         ("method", "Run Action")],
        required=True, index=True,
    )
    model_name = fields.Char(required=True, index=True)
    record_ids = fields.Char(help="Comma-separated ids this change applies to.")
    values_json = fields.Text()
    method = fields.Char()
    summary = fields.Char(required=True)
    preview = fields.Text()
    state = fields.Selection(
        [("proposed", "Waiting for approval"), ("applied", "Applied"),
         ("rejected", "Rejected"), ("failed", "Failed")],
        default="proposed", required=True, index=True,
    )
    result = fields.Text()
    error = fields.Text()
    applied_by = fields.Many2one("res.users")
    applied_at = fields.Datetime()

    # ------------------------------------------------------------- helpers
    def _target_ids(self):
        """The ids this change applies to.

        Deliberately not called `_ids`: that is the recordset's own tuple of
        database ids in Odoo, and shadowing it breaks the model.
        """
        self.ensure_one()
        return [int(part) for part in (self.record_ids or "").split(",") if part.strip()]

    def _values(self):
        self.ensure_one()
        if not self.values_json:
            return {}
        try:
            return json.loads(self.values_json)
        except ValueError:
            return {}

    def _payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "kind": self.kind,
            "model": self.model_name,
            "record_ids": self._target_ids(),
            "summary": self.summary,
            "preview": self.preview or "",
            "state": self.state,
            "method": self.method or "",
            "result": self.result or "",
            "error": self.error or "",
            "user": self.user_id.name,
        }

    # -------------------------------------------------------------- apply
    def apply(self):
        """Carry out the change, as the user who is approving it."""
        self.ensure_one()
        if self.state != "proposed":
            raise UserError(_("This change is %s, so it cannot be applied.") % self.state)
        if self.user_id != self.env.user and not self.env.user.has_group(
            "centric_claude_integration.group_claude_admin"
        ):
            raise AccessError(_("You can only apply changes from your own conversations."))

        data = self.env["centric.claude.data"]
        # Re-check permission at apply time. The proposal may be minutes old and
        # the user's rights, or the administrator's settings, may have changed.
        operation = {"create": "create", "write": "write",
                     "unlink": "unlink", "method": "write"}[self.kind]
        record_model = data._require_write(self.model_name, operation=operation)

        try:
            if self.kind == "create":
                created = record_model.create(
                    data._validate_values(record_model, self._values())
                )
                result = _("Created %(name)s (id %(id)s)") % {
                    "name": created.display_name, "id": created.id
                }
                self.record_ids = str(created.id)
            else:
                records = record_model.browse(self._target_ids()).exists()
                if not records:
                    raise UserError(_("Those records no longer exist."))
                if self.kind == "write":
                    records.write(data._validate_values(record_model, self._values()))
                    result = _("Updated %s record(s)") % len(records)
                elif self.kind == "unlink":
                    names = ", ".join(records.mapped("display_name")[:10])
                    records.unlink()
                    result = _("Deleted %(count)s record(s): %(names)s") % {
                        "count": len(records), "names": names
                    }
                else:
                    returned = self._run_method(records)
                    result = _("Ran %(method)s on %(count)s record(s). Result: %(result)s") % {
                        "method": self.method, "count": len(records),
                        "result": str(returned)[:500],
                    }
        except Exception as exc:  # noqa: BLE001 - the reason belongs in the UI.
            # Do not swallow this: Odoo rolls the transaction back on an
            # exception, so the failure must be raised after being described.
            self.env.cr.rollback()
            self.write({"state": "failed", "error": str(exc)[:2000]})
            self.env.cr.commit()
            self.conversation_id._audit(
                "data_apply", details=_("%(kind)s on %(model)s failed: %(error)s") % {
                    "kind": self.kind, "model": self.model_name, "error": str(exc)[:300]
                }, success=False,
            )
            raise UserError(_("The change could not be applied:\n\n%s") % exc) from exc

        self.write({
            "state": "applied",
            "result": result,
            "applied_by": self.env.user.id,
            "applied_at": fields.Datetime.now(),
        })
        self.conversation_id._audit(
            "data_apply",
            details=_("%(kind)s on %(model)s: %(result)s") % {
                "kind": self.kind, "model": self.model_name, "result": result
            },
        )
        return result

    def _run_method(self, records):
        """Call a public model method, e.g. action_post on an invoice."""
        self.ensure_one()
        name = (self.method or "").strip()
        if not name or name.startswith("_"):
            raise UserError(_("Only public model methods can be run."))
        if name in ("unlink", "write", "create", "browse", "search", "read",
                    "sudo", "with_user", "with_context", "with_env", "_run_method"):
            raise UserError(_(
                "'%s' is not run this way. Propose a create, update or delete "
                "instead."
            ) % name)
        handler = getattr(records, name, None)
        if not callable(handler):
            raise UserError(_("%(model)s has no action called '%(method)s'.") % {
                "model": self.model_name, "method": name
            })
        return handler()

    def reject(self):
        self.ensure_one()
        if self.state != "proposed":
            raise UserError(_("This change is %s, so it cannot be rejected.") % self.state)
        self.state = "rejected"
        self.conversation_id._audit(
            "data_apply",
            details=_("Rejected %(kind)s on %(model)s") % {
                "kind": self.kind, "model": self.model_name
            },
            success=False,
        )
        return True
