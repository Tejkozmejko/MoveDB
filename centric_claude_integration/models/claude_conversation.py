import difflib
import json
import re
from datetime import datetime, timezone

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class CentricClaudeConversation(models.Model):
    _name = "centric.claude.conversation"
    _description = "Claude Developer Conversation"
    _order = "write_date desc, id desc"

    name = fields.Char(required=True, default="New Claude Conversation")
    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="cascade",
        index=True,
    )
    project_id = fields.Many2one(
        "centric.claude.project",
        string="Project",
        ondelete="set null",
        index=True,
        help="Groups this conversation with related ones and gives it the "
             "project's standing instructions.",
    )
    developer_mode = fields.Boolean(default=False)
    # Both backends take the same five levels: the Messages API as
    # output_config.effort, and the Claude Code CLI as --effort. Keeping one
    # field means the choice means the same thing whichever answers.
    effort = fields.Selection(
        [
            ("low", "Low - quick lookups"),
            ("medium", "Medium - routine work"),
            ("high", "High - balanced (default)"),
            ("xhigh", "Very high - deep code work"),
            ("max", "Maximum - correctness over cost"),
        ],
        default=lambda self: self._default_effort(),
        required=True,
        help="How much thinking and how many tokens Claude spends on this "
             "conversation. Lower levels answer simple questions with less of "
             "your subscription usage.",
    )
    base_branch = fields.Char(required=True, default=lambda self: self._default_branch())
    review_branch = fields.Char(readonly=True, copy=False)
    commit_sha = fields.Char(readonly=True, copy=False)
    pull_request_number = fields.Integer(readonly=True, copy=False)
    pull_request_url = fields.Char(readonly=True, copy=False)
    state = fields.Selection(
        [
            ("active", "Active"),
            ("committed", "Committed"),
            ("closed", "Closed"),
        ],
        default="active",
        required=True,
        index=True,
    )
    message_ids = fields.One2many("centric.claude.message", "conversation_id", string="Messages")
    change_ids = fields.One2many("centric.claude.change", "conversation_id", string="Code Changes")
    operation_ids = fields.One2many("centric.claude.operation", "conversation_id", string="Data Changes")

    @api.model
    def _default_branch(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "centric_claude.default_branch", "testing"
        ) or "testing"

    EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

    @api.model
    def _default_effort(self):
        value = self.env["ir.config_parameter"].sudo().get_param(
            "centric_claude.default_effort", "high"
        )
        return value if value in self.EFFORT_LEVELS else "high"

    @api.model
    def _param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    @api.model
    def _bool_param(self, key, default=False):
        value = self._param(key, "True" if default else "False")
        return str(value).lower() in {"1", "true", "yes", "on"}

    def _check_owner(self):
        self.ensure_one()
        if self.user_id != self.env.user and not self.env.user.has_group(
            "centric_claude_integration.group_claude_admin"
        ):
            raise AccessError(_("You can only open your own Claude conversations."))

    @api.model
    def _workspace_access(self):
        user = self.env.user
        enabled = self._bool_param("centric_claude.enabled", False)
        read_enabled = self._bool_param("centric_claude.code_read_enabled", True)
        write_enabled = self._bool_param("centric_claude.code_write_enabled", False)
        pr_enabled = self._bool_param("centric_claude.pull_request_enabled", True)
        is_user = user.has_group("centric_claude_integration.group_claude_user")
        is_reader = user.has_group("centric_claude_integration.group_claude_code_reader")
        is_developer = user.has_group("centric_claude_integration.group_claude_developer")
        is_admin = user.has_group("centric_claude_integration.group_claude_admin")
        owner = self._param("centric_claude.github_owner")
        repo = self._param("centric_claude.github_repo")
        data_access = self.env["centric.claude.data"]._data_access()
        return {
            "data_level": data_access["level"],
            "data_level_label": data_access["level_label"],
            "can_read_data": data_access["can_read"],
            "can_propose_data": data_access["can_propose"],
            "enabled": enabled,
            "can_chat": enabled and is_user,
            "can_read_code": enabled and read_enabled and (is_reader or is_developer or is_admin),
            "can_develop": enabled and write_enabled and (is_developer or is_admin),
            "can_create_pr": enabled and write_enabled and pr_enabled and (is_developer or is_admin),
            "can_admin": is_admin,
            "repository": f"{owner}/{repo}" if owner and repo else "",
            "default_branch": self._default_branch(),
            "allowed_module_prefix": self._param("centric_claude.allowed_module_prefix", "centric_"),
            "effort_choices": self._effort_choices(),
            "attachments_enabled": self.env["centric.claude.attachment"]._enabled(),
            "attachment_max_mb": round(
                self.env["centric.claude.attachment"]._max_bytes() / 1024 / 1024, 1
            ),
            "user_name": user.name,
        }

    @api.model
    def _workspace_sidebar(self):
        """Everything the sidebar shows: the projects and the chat list."""
        conversations = self.search([("user_id", "=", self.env.user.id)], limit=200)
        return {
            "projects": self.env["centric.claude.project"]._workspace_projects(),
            "conversations": [
                self._conversation_summary(conv) for conv in conversations
            ],
        }

    @api.model
    def workspace_bootstrap(self):
        return {"access": self._workspace_access()} | self._workspace_sidebar()

    @api.model
    def create_workspace_conversation(self, name=None, project_id=None):
        access = self._workspace_access()
        if not access["can_chat"]:
            raise AccessError(_("You do not have access to the Claude workspace."))
        project = self.env["centric.claude.project"]
        if project_id:
            project = project.browse(int(project_id)).exists()
            if project:
                project._check_owner()
        conv = self.create({
            "name": (name or _("New Claude Conversation")).strip()[:120],
            "user_id": self.env.user.id,
            "base_branch": access["default_branch"],
            "project_id": project.id or False,
        })
        return self._conversation_payload(conv)

    @api.model
    def rename_workspace_conversation(self, conversation_id, name):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        clean = (name or "").strip()[:120]
        if not clean:
            raise ValidationError(_("A conversation needs a name."))
        conv.name = clean
        return self._workspace_sidebar()

    @api.model
    def set_workspace_conversation_project(self, conversation_id, project_id):
        """File a chat under a project, or take it out of one with a false id."""
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        project = self.env["centric.claude.project"]
        if project_id:
            project = project.browse(int(project_id)).exists()
            if not project:
                raise UserError(_("That Claude project no longer exists."))
            project._check_owner()
        conv.project_id = project.id or False
        return self._conversation_payload(conv)

    @api.model
    def delete_workspace_conversation(self, conversation_id):
        """Delete one chat and everything cascading from it.

        A queued turn is cancelled first: the bridge would otherwise claim a
        turn whose conversation no longer exists and fail posting the answer
        back.
        """
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            # Already gone - deleting twice is not an error worth raising.
            return self._workspace_sidebar()
        conv._check_owner()
        self.env["centric.claude.turn"].sudo().search([
            ("conversation_id", "=", conv.id),
            ("state", "in", ("pending", "running")),
        ]).write({"state": "cancelled", "finished_at": fields.Datetime.now()})
        conv._audit(
            "conversation_delete",
            details="Conversation deleted: %s" % conv.name,
        )
        conv.unlink()
        return self._workspace_sidebar()

    @api.model
    def get_workspace_conversation(self, conversation_id):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        return self._conversation_payload(conv)

    @api.model
    def set_workspace_developer_mode(self, conversation_id, enabled):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if enabled and not access["can_develop"]:
            conv._audit("security_denied", details="Developer Mode enable denied.", success=False)
            raise AccessError(_(
                "Developer Mode requires the Claude Developer security group and the global Allow Code Modifications setting."
            ))
        conv.developer_mode = bool(enabled)
        return self._conversation_payload(conv)

    @api.model
    def set_workspace_effort(self, conversation_id, effort):
        """Change how hard Claude works on this conversation."""
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        if effort not in self.EFFORT_LEVELS:
            raise UserError(_("'%s' is not an effort level.") % effort)
        conv.effort = effort
        return self._conversation_payload(conv)

    @api.model
    def send_workspace_message(self, conversation_id, text, attachment_ids=None):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not access["can_chat"]:
            raise AccessError(_("Claude is disabled or you do not have workspace access."))
        typed = (text or "").strip()
        # Only images that are still unsent, and only this user's: an id from an
        # older message must not be re-attachable to a new one.
        attachments = self.env["centric.claude.attachment"]._pending_for(
            conv, attachment_ids
        )
        if not typed and not attachments:
            raise ValidationError(_("Enter a message first."))
        if len(typed) > 30000:
            raise ValidationError(_("Messages are limited to 30,000 characters."))

        # `content` is required, and an image on its own still has to say
        # something to Claude, so an image-only message carries the obvious ask.
        text = typed or (
            _("Please look at the attached image.") if len(attachments) == 1
            else _("Please look at the attached images.")
        )
        message = self.env["centric.claude.message"].create({
            "conversation_id": conv.id,
            "role": "user",
            "content": text,
        })
        if attachments:
            attachments.write({"message_id": message.id})
        if conv.name in conv._default_names():
            # An image-only message names the chat after the image; "Please look
            # at the attached image" would name every one of them the same.
            label = typed or (attachments[:1].name if attachments else text)
            conv.name = label.splitlines()[0][:80]

        if self._param("centric_claude.backend", "agent") == "agent":
            # Odoo.sh cannot run the Claude Code CLI, so the turn is queued for the
            # developer's local bridge to claim. The browser polls for the answer.
            self.env["centric.claude.turn"].create({
                "conversation_id": conv.id,
                "user_id": self.env.user.id,
                # The turn points at its message so the bridge can find the
                # images without guessing which message it came from.
                "message_id": message.id,
                "prompt": text,
                "developer_mode": conv.developer_mode,
                "effort": conv.effort,
                "base_branch": conv.base_branch,
                "review_branch": conv.review_branch or False,
            })
            return self._conversation_payload(conv)

        # A failure late in a turn must not roll back the user's message, anything
        # Claude staged, or the audit trail. Report it as an assistant reply instead.
        try:
            assistant_text = conv._run_claude_turn()
            failed = False
        except (UserError, ValidationError, AccessError) as exc:
            assistant_text = _("The request could not be completed: %s") % exc
            failed = True

        self.env["centric.claude.message"].create({
            "conversation_id": conv.id,
            "role": "assistant",
            "content": assistant_text,
        })
        conv._audit(
            "chat",
            details="Claude conversation turn completed." if not failed else assistant_text[:500],
            success=not failed,
        )
        return self._conversation_payload(conv)

    @api.model
    def _default_names(self):
        """Every spelling of the placeholder name, so auto-naming survives translation."""
        return {"New Claude Conversation", _("New Claude Conversation")}

    def _run_claude_turn(self):
        self.ensure_one()
        access = self._workspace_access()
        history_records = self.message_ids.filtered(
            lambda msg: msg.role in {"user", "assistant"}
        ).sorted("id")[-30:]
        messages = self._api_messages(history_records)
        tools = self._tool_definitions(access)
        max_rounds = int(self._param("centric_claude.max_tool_rounds", "8") or 8)
        max_rounds = min(max(max_rounds, 1), 20)
        client = self.env["centric.claude.client"]

        narration = []

        for _round in range(max_rounds):
            response = client._create_message(
                messages,
                system=self._system_prompt(access),
                tools=tools,
                effort=self.effort,
            )
            content_blocks = response.get("content", [])
            stop_reason = response.get("stop_reason")
            tool_blocks = [block for block in content_blocks if block.get("type") == "tool_use"]
            text = "\n".join(
                block.get("text", "")
                for block in content_blocks
                if block.get("type") == "text" and block.get("text")
            ).strip()

            # A safety decline arrives as HTTP 200, so it has to be checked here.
            if stop_reason == "refusal":
                details = response.get("stop_details") or {}
                category = details.get("category")
                narration.append(
                    _("Claude declined this request (%s).") % category
                    if category
                    else _("Claude declined this request.")
                )
                return "\n\n".join(narration).strip()

            if stop_reason == "max_tokens":
                narration.append(_(
                    "Claude ran out of output tokens. Raise Maximum Output Tokens in "
                    "the Centric Claude settings, or ask for a smaller change."
                ))
                return "\n\n".join(narration + ([text] if text else [])).strip()

            if not tool_blocks:
                return "\n\n".join(narration + [text]).strip() or _(
                    "Claude returned no text response."
                )

            # Keep what Claude said before reaching for a tool; it explains the work.
            if text:
                narration.append(text)
            messages.append({"role": "assistant", "content": content_blocks})
            tool_results = []
            for block in tool_blocks:
                tool_name = block.get("name")
                tool_input = block.get("input") or {}
                try:
                    result = self._execute_tool(tool_name, tool_input, access)
                    tool_content = json.dumps(result, ensure_ascii=False, default=str)
                    is_error = False
                except Exception as exc:  # noqa: BLE001 - tool errors must be returned to Claude cleanly.
                    tool_content = str(exc)
                    is_error = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": tool_content[:200000],
                    "is_error": is_error,
                })
            messages.append({"role": "user", "content": tool_results})

        # Budget stop, not a failure: keep the narration and everything Claude staged.
        narration.append(_(
            "Claude stopped after the configured limit of %s tool rounds. "
            "Review the staged changes, or send a narrower follow-up request."
        ) % max_rounds)
        return "\n\n".join(narration).strip()

    def _api_messages(self, history_records):
        """History as Messages API content, with images attached where sent.

        Walked newest-first so that when the image budget runs out it is the
        oldest screenshots that drop, not the ones just sent.
        """
        Attachment = self.env["centric.claude.attachment"]
        budget = Attachment.HISTORY_IMAGE_LIMIT
        messages = []
        for msg in reversed(history_records):
            blocks = []
            if msg.role == "user":
                for attachment in msg.attachment_ids:
                    if budget <= 0:
                        break
                    blocks.append(attachment._image_block())
                    budget -= 1
            if blocks:
                blocks.append({"type": "text", "text": msg.content})
                messages.append({"role": msg.role, "content": blocks})
            else:
                messages.append({"role": msg.role, "content": msg.content})
        messages.reverse()
        return messages

    def _system_prompt(self, access):
        self.ensure_one()
        current_branch = self.review_branch or self.base_branch
        permission_text = (
            "You may stage source changes with stage_file_change when a fix is justified. "
            "Staging is reversible and does not commit to GitHub."
            if self.developer_mode and access["can_develop"]
            else "You are read-only. Do not claim that you changed source code."
        )
        return f"""
You are the Claude developer assistant embedded in Odoo 19 for Centric.

Odoo database access: {access['data_level_label']}
Repository: {access['repository'] or 'not configured'}
Current branch: {current_branch}
Allowed custom-module prefix: {access['allowed_module_prefix'] or 'centric_'}
Developer Mode: {'ON' if self.developer_mode else 'OFF'}

Rules:
- Investigate with the provided tools before making claims about repository code.
- You may only inspect repository modules returned by list_repository_modules.
- Never ask for, expose, or infer API keys, GitHub tokens, passwords, OAuth secrets, or other credentials.
- Never modify Odoo core, Enterprise source, third-party modules, repository CI, or server configuration.
- {permission_text}
- When staging a change, read the current file first and preserve unrelated code.
- Prefer the smallest correct change and explain exactly what was staged.
- You cannot commit, merge, deploy, or push production. A human developer controls GitHub commit/PR actions in Odoo.
- If required context is unavailable, say what is missing instead of inventing it.
{self._data_prompt(access)}
{self._project_prompt()}
""".strip()

    def _project_prompt(self):
        """The standing instructions of the project this conversation sits in."""
        self.ensure_one()
        project = self.project_id
        text = (project.instructions or "").strip() if project else ""
        if not text:
            return ""
        limit = self.env["centric.claude.project"].MAX_INSTRUCTIONS
        return (
            "\nProject: %s\n"
            "The user filed this conversation under a project with standing "
            "instructions. Follow them unless they conflict with the rules "
            "above, which always win:\n%s\n"
        ) % (project.name, text[:limit])

    def _data_prompt(self, access):
        """The part of the system prompt that governs live Odoo records."""
        if not access["can_read_data"]:
            return (
                "- You have no access to Odoo business records. If asked about "
                "tickets, invoices or any other data, say plainly that your "
                "administrator has not given this account a Claude data level."
            )
        lines = [
            "- You can look up real records with find_odoo_models, "
            "search_odoo_records, read_odoo_record and count_odoo_records. "
            "Use find_odoo_models first when you are unsure of a model name; "
            "guessing model or field names wastes a turn.",
            "- Every query runs with the permissions of the person you are "
            "talking to. A result of zero rows may mean the records exist but "
            "they may not see them; say so rather than asserting there are none.",
            "- Quote figures and names exactly as the database returns them. "
            "Never estimate, extrapolate or invent a record.",
        ]
        if access["can_propose_data"]:
            lines.append(
                "- To change anything, call propose_odoo_change or "
                "propose_odoo_action. This does NOT perform the change: it puts "
                "a confirmation in front of the user, who must press Yes. Say "
                "clearly what you have proposed and that it is waiting on them. "
                "Never claim a record was created, updated or deleted."
            )
            lines.append(
                "- Before proposing, read the record and check the model's "
                "fields, so the values you send are real field names with "
                "plausible values. Propose one coherent change at a time."
            )
        else:
            lines.append(
                "- Your data level is read-only. You cannot create, edit or "
                "delete anything. If asked to, say that it needs the "
                "Intermediate or Administrator level."
            )
        return chr(10).join(lines)

    def _tool_definitions(self, access):
        tools = [
            {
                "name": "list_installed_custom_modules",
                "description": "List installed Odoo modules whose technical name matches the configured Centric custom-module prefix.",
                "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                "strict": True,
            },
            {
                "name": "get_odoo_module_info",
                "description": "Get installed-state and version metadata for one Odoo module. This returns metadata, not source code.",
                "input_schema": {
                    "type": "object",
                    "properties": {"module": {"type": "string"}},
                    "required": ["module"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "name": "describe_odoo_model",
                "description": (
                    "Describe an Odoo model and its fields, with types, labels and selection "
                    "options. Read this before filtering on, or setting, a field you have not "
                    "already seen. Returns schema only, never business records or secrets."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"model": {"type": "string"}},
                    "required": ["model"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        ]
        if access["can_read_data"]:
            tools.extend(self._data_tool_definitions(access))
        if access["can_read_code"]:
            tools.extend([
                {
                    "name": "list_repository_modules",
                    "description": "List approved custom Odoo modules discovered in the configured GitHub repository on the current branch.",
                    "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                    "strict": True,
                },
                {
                    "name": "list_module_files",
                    "description": "List files inside one approved repository module.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"module": {"type": "string"}},
                        "required": ["module"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "name": "read_module_file",
                    "description": "Read one UTF-8 source file from an approved repository module on the current branch.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "module": {"type": "string"},
                            "path": {"type": "string"},
                        },
                        "required": ["module", "path"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "name": "search_module_code",
                    "description": "Search text inside source files of one approved repository module and return matching lines.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "module": {"type": "string"},
                            "query": {"type": "string"},
                        },
                        "required": ["module", "query"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            ])
        if self.developer_mode and access["can_develop"]:
            tools.append({
                "name": "stage_file_change",
                "description": (
                    "Stage a complete replacement version of one already-existing source file in an approved custom module. "
                    "This does not commit to GitHub. Always read the file first, preserve unrelated content, and provide the entire new file content."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "module": {"type": "string"},
                        "path": {"type": "string"},
                        "new_content": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["module", "path", "new_content", "summary"],
                    "additionalProperties": False,
                },
                "strict": True,
            })
        return tools

    def _data_tool_definitions(self, access):
        """Tools for reading and changing ordinary Odoo records.

        Every argument is a plain string and every property is required, which
        is what strict tool use demands. Optional arguments are expressed as an
        empty string rather than an absent key.
        """
        tools = [
            {
                "name": "find_odoo_models",
                "description": (
                    "Find Odoo models by technical or human name, for example 'helpdesk', "
                    "'invoice' or 'sale'. Use this before searching when you are not certain "
                    "of the exact model name. Returns only models this user may read."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Words to look for. Empty lists the first models alphabetically."},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "name": "search_odoo_records",
                "description": (
                    "Search real records in the Odoo database. Runs with the permissions of "
                    "the user you are talking to, so results are limited to what they may see."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string", "description": "Technical model name, e.g. helpdesk.ticket"},
                        "domain": {
                            "type": "string",
                            "description": (
                                "An Odoo domain as JSON, e.g. "
                                "[[\"state\",\"=\",\"open\"]]. Use [] for everything."
                            ),
                        },
                        "fields": {
                            "type": "string",
                            "description": "Comma-separated field names, or empty to let Odoo choose useful ones.",
                        },
                        "limit": {"type": "integer", "description": "Maximum rows, 1 to 200."},
                        "order": {"type": "string", "description": "Sort clause such as 'create_date desc', or empty."},
                    },
                    "required": ["model", "domain", "fields", "limit", "order"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "name": "read_odoo_record",
                "description": "Read one record in full by id, for detail a search result did not include.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "record_id": {"type": "integer"},
                        "fields": {"type": "string", "description": "Comma-separated names, or empty for all readable fields."},
                    },
                    "required": ["model", "record_id", "fields"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
            {
                "name": "count_odoo_records",
                "description": "Count matching records without fetching them. Use for 'how many' questions.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "model": {"type": "string"},
                        "domain": {"type": "string", "description": "An Odoo domain as JSON. Use [] for everything."},
                    },
                    "required": ["model", "domain"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        ]
        if access["can_propose_data"]:
            tools.extend([
                {
                    "name": "propose_odoo_change",
                    "description": (
                        "Propose creating, updating or deleting records. This does NOT change "
                        "anything: it shows the user a confirmation they must accept. Tell them "
                        "what you proposed and that it is waiting for their Yes."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["create", "write", "unlink"]},
                            "model": {"type": "string"},
                            "record_ids": {
                                "type": "string",
                                "description": "Comma-separated ids for update or delete. Empty when creating.",
                            },
                            "values": {
                                "type": "string",
                                "description": (
                                    "Field values as a JSON object, e.g. "
                                    "{\"name\": \"ACME\"}. Empty when deleting."
                                ),
                            },
                            "summary": {
                                "type": "string",
                                "description": "One plain sentence the user will read before deciding.",
                            },
                        },
                        "required": ["kind", "model", "record_ids", "values", "summary"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
                {
                    "name": "propose_odoo_action",
                    "description": (
                        "Propose running a built-in Odoo action on records, such as action_post "
                        "on an invoice or action_confirm on a sales order. Like propose_odoo_change "
                        "this only asks the user; it does not run anything."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "model": {"type": "string"},
                            "record_ids": {"type": "string", "description": "Comma-separated ids."},
                            "method": {"type": "string", "description": "Public method name, e.g. action_post."},
                            "summary": {"type": "string"},
                        },
                        "required": ["model", "record_ids", "method", "summary"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            ])
        return tools

    def _execute_data_tool(self, tool_name, tool_input, access):
        """Run one database tool. Returns None when the name is not ours."""
        data = self.env["centric.claude.data"]

        def field_list(raw):
            return [part.strip() for part in (raw or "").split(",") if part.strip()]

        if tool_name == "find_odoo_models":
            result = data.find_models(tool_input.get("query"))
            self._audit("data_read", details="Looked for models matching: %s"
                        % (tool_input.get("query") or "(all)")[:100])
            return result

        if tool_name == "describe_odoo_model":
            model_name = tool_input.get("model")
            result = data.describe_model(model_name)
            self._audit("data_read", details="Described model %s" % model_name)
            return result

        if tool_name == "search_odoo_records":
            model_name = tool_input.get("model")
            result = data.search_records(
                model_name,
                domain=tool_input.get("domain"),
                field_names=field_list(tool_input.get("fields")),
                limit=tool_input.get("limit"),
                order=(tool_input.get("order") or "").strip() or None,
            )
            self._audit("data_read", details="Searched %s: %s row(s) of %s" % (
                model_name, result["returned"], result["total_matching"]))
            return result

        if tool_name == "read_odoo_record":
            model_name = tool_input.get("model")
            result = data.read_record(
                model_name, tool_input.get("record_id"),
                field_names=field_list(tool_input.get("fields")),
            )
            self._audit("data_read", details="Read %s id %s" % (
                model_name, tool_input.get("record_id")))
            return result

        if tool_name == "count_odoo_records":
            model_name = tool_input.get("model")
            result = data.count_records(model_name, domain=tool_input.get("domain"))
            self._audit("data_read", details="Counted %s: %s" % (
                model_name, result["count"]))
            return result

        if tool_name == "propose_odoo_change":
            return self._propose_change(
                tool_input.get("kind"),
                tool_input.get("model"),
                tool_input.get("record_ids"),
                tool_input.get("values"),
                tool_input.get("summary"),
            )

        if tool_name == "propose_odoo_action":
            return self._propose_change(
                "method",
                tool_input.get("model"),
                tool_input.get("record_ids"),
                "",
                tool_input.get("summary"),
                method=tool_input.get("method"),
            )

        return None

    def _propose_change(self, kind, model_name, record_ids, values, summary, method=None):
        """Record a change for the user to confirm. Nothing is written here."""
        self.ensure_one()
        data = self.env["centric.claude.data"]
        kind = (kind or "").strip()
        if kind not in ("create", "write", "unlink", "method"):
            raise UserError(_("'%s' is not a kind of change that can be proposed.") % kind)
        operation = {"create": "create", "write": "write",
                     "unlink": "unlink", "method": "write"}[kind]
        record_model = data._require_write(model_name, operation=operation)

        ids = [int(part) for part in str(record_ids or "").replace(" ", "").split(",") if part]
        if kind == "create" and ids:
            raise UserError(_("A create has no existing records to point at."))
        if kind != "create" and not ids:
            raise UserError(_("Say which record ids this applies to."))
        if len(ids) > data.MAX_WRITE_RECORDS:
            raise UserError(_("At most %s records can be changed at once.")
                            % data.MAX_WRITE_RECORDS)

        parsed = {}
        if kind in ("create", "write"):
            if isinstance(values, str):
                try:
                    parsed = json.loads(values or "{}")
                except ValueError as exc:
                    raise UserError(_("The values must be a JSON object: %s") % values) from exc
            else:
                parsed = values or {}
            data._validate_values(record_model, parsed)
            if not parsed:
                raise UserError(_("No values were given to set."))

        # Show the user what will actually happen, in their language, before
        # they are asked to agree to it.
        if kind == "create":
            preview = _("Create a new %(model)s with:") % {"model": record_model._description}
            preview += chr(10) + data._describe_values(record_model, parsed)
        elif kind == "write":
            records = record_model.browse(ids).exists()
            if not records:
                raise UserError(_("Those records do not exist, or you cannot see them."))
            preview = _("Change %(count)s record(s): %(names)s") % {
                "count": len(records),
                "names": ", ".join(records.mapped("display_name")[:10]),
            }
            preview += chr(10) + chr(10) + _("Set:") + chr(10)
            preview += data._describe_values(record_model, parsed)
            preview += chr(10) + chr(10) + _("Currently:") + chr(10)
            current = records[0].read(list(parsed))[0]
            preview += data._describe_values(
                record_model, {k: v for k, v in current.items() if k != "id"}
            )
        elif kind == "unlink":
            records = record_model.browse(ids).exists()
            if not records:
                raise UserError(_("Those records do not exist, or you cannot see them."))
            preview = _("Permanently delete %(count)s %(model)s record(s): %(names)s") % {
                "count": len(records), "model": record_model._description,
                "names": ", ".join(records.mapped("display_name")[:10]),
            }
        else:
            records = record_model.browse(ids).exists()
            if not records:
                raise UserError(_("Those records do not exist, or you cannot see them."))
            if not method or method.startswith("_"):
                raise UserError(_("Only public Odoo actions can be proposed."))
            preview = _("Run '%(method)s' on %(count)s record(s): %(names)s") % {
                "method": method, "count": len(records),
                "names": ", ".join(records.mapped("display_name")[:10]),
            }

        record = self.env["centric.claude.operation"].create({
            "conversation_id": self.id,
            "user_id": self.user_id.id,
            "kind": kind,
            "model_name": model_name,
            "record_ids": ",".join(str(i) for i in ids),
            "values_json": json.dumps(parsed) if parsed else False,
            "method": method or False,
            # Claude writes this sentence, so treat it as text, never as a
            # format string: a stray % in it would otherwise raise here.
            "summary": ((summary or "").strip()
                        or _("Change to %s") % model_name)[:200],
            "preview": preview,
        })
        self._audit(
            "data_propose",
            details="%s on %s: %s" % (kind, model_name, record.summary),
        )
        return {
            "proposed": True,
            "operation_id": record.id,
            "awaiting_confirmation": True,
            "note": (
                "Nothing has changed yet. The user has been shown this and must "
                "press Yes before it happens. Tell them what you proposed."
            ),
            "preview": preview,
        }

    def _execute_tool(self, tool_name, tool_input, access):
        self.ensure_one()
        github = self.env["centric.claude.github.client"]
        branch = self.review_branch or self.base_branch

        if access["can_read_data"]:
            handled = self._execute_data_tool(tool_name, tool_input, access)
            if handled is not None:
                return handled

        if tool_name == "list_installed_custom_modules":
            prefix = access["allowed_module_prefix"] or "centric_"
            # `like` is SQL LIKE, where `_` matches any single character, so the
            # database query is only a prefilter; startswith is the real check.
            modules = self.env["ir.module.module"].sudo().search([
                ("state", "=", "installed"),
                ("name", "like", f"{prefix}%"),
            ]).filtered(lambda module: module.name.startswith(prefix))
            return [
                {
                    "name": module.name,
                    "display_name": module.shortdesc,
                    "version": module.installed_version,
                }
                for module in modules.sorted("name")
            ]

        if tool_name == "get_odoo_module_info":
            name = (tool_input.get("module") or "").strip()
            module = self.env["ir.module.module"].sudo().search([("name", "=", name)], limit=1)
            if not module:
                return {"found": False, "module": name}
            return {
                "found": True,
                "name": module.name,
                "display_name": module.shortdesc,
                "state": module.state,
                "installed_version": module.installed_version,
                "latest_version": module.latest_version,
                "summary": module.summary,
            }

        if tool_name == "describe_odoo_model":
            model_name = (tool_input.get("model") or "").strip()
            if model_name not in self.env:
                return {"found": False, "model": model_name}
            model = self.env[model_name]
            field_rows = []
            for name, field in sorted(model._fields.items()):
                field_rows.append({
                    "name": name,
                    "type": field.type,
                    "string": field.string,
                    "required": bool(field.required),
                    "readonly": bool(field.readonly),
                    "relation": getattr(field, "comodel_name", False) or False,
                })
            return {
                "found": True,
                "model": model_name,
                "description": getattr(model, "_description", ""),
                "fields": field_rows[:500],
            }

        if tool_name in {"list_repository_modules", "list_module_files", "read_module_file", "search_module_code"}:
            if not access["can_read_code"]:
                raise AccessError(_("Repository read access is disabled."))

        if tool_name == "list_repository_modules":
            modules = github._list_allowed_modules(branch=branch)
            self._audit("repo_read", branch=branch, details="Listed approved repository modules.")
            return modules

        if tool_name == "list_module_files":
            module = tool_input.get("module")
            result = github._list_module_files(module, branch=branch)
            self._audit("repo_read", branch=branch, module_name=module, details="Listed module files.")
            return result

        if tool_name == "read_module_file":
            module = tool_input.get("module")
            path = tool_input.get("path")
            result = github._read_module_file(module, path, branch=branch)
            self._audit(
                "repo_read",
                branch=branch,
                module_name=module,
                file_path=path,
                details="Read repository source file.",
            )
            return result

        if tool_name == "search_module_code":
            module = tool_input.get("module")
            query = tool_input.get("query")
            result = github._search_module_code(module, query, branch=branch)
            self._audit(
                "repo_read",
                branch=branch,
                module_name=module,
                details=f"Searched module source for: {query[:120]}",
            )
            return result

        if tool_name == "stage_file_change":
            if not self.developer_mode or not access["can_develop"]:
                raise AccessError(_("Developer Mode is not enabled for this conversation."))
            return self._stage_change(
                tool_input.get("module"),
                tool_input.get("path"),
                tool_input.get("new_content"),
                tool_input.get("summary"),
            )

        raise UserError(_("Unknown Claude tool: %s") % tool_name)

    def _stage_change(self, module_name, file_path, new_content, summary=None,
                      allow_new_module=False):
        self.ensure_one()
        access = self._workspace_access()
        if not self.developer_mode or not access["can_develop"]:
            raise AccessError(_("Developer Mode is not enabled or you do not have code-write permission."))
        if len(new_content or "") > 512000:
            raise ValidationError(_("Staged files are limited to 500 KB."))
        branch = self.review_branch or self.base_branch
        github = self.env["centric.claude.github.client"]
        # A module already staged in this conversation is treated as existing,
        # so its second and later files resolve to the same root.
        pending_root = self._pending_module_root(module_name)
        if pending_root:
            root, is_new_module = pending_root, True
        else:
            root, is_new_module = github._resolve_module_root(
                module_name, branch=branch, allow_new=allow_new_module
            )
        _root, full_path = github._validate_module_file(
            module_name, file_path, branch=branch, root=root
        )
        # allow_missing lets Claude add a file to an approved module; a module
        # that does not exist on the branch yet has nothing to read at all.
        current = None if is_new_module else github._read_module_file(
            module_name, file_path, branch=branch, root=root, allow_missing=True
        )
        current_content = current["content"] if current else ""
        if new_content == current_content:
            return {"staged": False, "reason": "No content changed."}

        existing = self.change_ids.filtered(
            lambda change: change.status == "staged"
            and change.module_name == module_name
            and change.file_path == file_path
        )[:1]
        original_content = (existing.original_content or "") if existing else current_content
        diff_text = self._make_diff(file_path, original_content, new_content)
        values = {
            "conversation_id": self.id,
            "module_name": module_name,
            "file_path": file_path,
            "full_path": full_path,
            "original_content": original_content,
            "proposed_content": new_content,
            "diff_text": diff_text,
            # Flag new files so the Changes tab shows at a glance that this adds
            # a file rather than editing one.
            "summary": (("New file: " if current is None else "")
                        + (summary or "Code change staged by Claude"))[:500],
            "is_new_module": is_new_module,
            "status": "staged",
            "staged_by": self.env.user.id,
            "staged_at": fields.Datetime.now(),
        }
        if existing:
            existing.write(values)
            change = existing
        else:
            change = self.env["centric.claude.change"].create(values)
        self._audit(
            "code_stage",
            branch=branch,
            module_name=module_name,
            file_path=file_path,
            details=values["summary"],
        )
        return {
            "staged": True,
            "change_id": change.id,
            "module": module_name,
            "path": file_path,
            "summary": change.summary,
        }

    def _pending_module_root(self, module_name):
        """Root of a module this conversation created but has not committed."""
        self.ensure_one()
        staged = self.change_ids.filtered(
            lambda change: change.status == "staged"
            and change.is_new_module
            and change.module_name == module_name
            and change.full_path
        )[:1]
        if not staged:
            return None
        full_path, file_path = staged.full_path, staged.file_path
        if full_path.endswith(file_path):
            return full_path[: -len(file_path)].rstrip("/")
        return None

    @api.model
    def create_workspace_module(self, conversation_id, name, files=None):
        """Stage the files that bring a new module into existence.

        Nothing is written to GitHub here. The module appears in the workspace
        as staged changes and only reaches the branch when a developer commits,
        which keeps new modules under exactly the same review gate as edits.
        """
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not conv.developer_mode or not access["can_develop"]:
            raise AccessError(_(
                "Developer Mode and Claude Developer permission are required to "
                "create a module."
            ))
        # Creating a module must never be a way to overwrite one. _stage_change
        # would happily treat these as ordinary edits to an existing module.
        github = self.env["centric.claude.github.client"]
        branch = conv.review_branch or conv.base_branch
        existing = github._list_allowed_modules(branch=branch)
        if any(module["name"] == name for module in existing):
            raise UserError(_(
                "Module '%s' already exists on this branch. Open it in the "
                "Explorer to add files to it."
            ) % name)
        entries = [entry for entry in (files or []) if (entry or {}).get("path")]
        if not any(entry["path"] == "__manifest__.py" for entry in entries):
            raise UserError(_(
                "A new module needs a __manifest__.py before Odoo will recognise it."
            ))
        for entry in entries:
            content = entry.get("content") or ""
            # An empty file cannot be staged - it matches the empty baseline of
            # a file that does not exist - so give it a placeholder body.
            if not content.strip():
                content = "# %s\n" % entry["path"]
            conv._stage_change(
                name,
                entry["path"],
                content,
                summary=_("New module %s") % name,
                allow_new_module=True,
            )
        return self._conversation_payload(conv)

    @api.model
    def stage_manual_change(self, conversation_id, module_name, file_path, new_content, summary=None):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        conv._stage_change(module_name, file_path, new_content, summary or "Manual code edit")
        return self._conversation_payload(conv)

    @api.model
    def discard_workspace_change(self, conversation_id, change_id):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        change = self.env["centric.claude.change"].browse(int(change_id)).exists()
        if not change or change.conversation_id != conv:
            raise UserError(_("Code change not found."))
        if change.status != "staged":
            raise UserError(_("Only staged changes can be discarded."))
        change.status = "discarded"
        conv._audit(
            "code_discard",
            branch=conv.review_branch or conv.base_branch,
            module_name=change.module_name,
            file_path=change.file_path,
            details="Staged code change discarded.",
        )
        return self._conversation_payload(conv)

    @api.model
    def commit_workspace_changes(self, conversation_id, message=None):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not conv.developer_mode or not access["can_develop"]:
            raise AccessError(_("Developer Mode and Claude Developer permission are required to commit code."))
        staged = conv.change_ids.filtered(lambda change: change.status == "staged")
        if not staged:
            raise UserError(_("There are no staged changes to commit."))

        github = self.env["centric.claude.github.client"]
        payload = [
            {
                "module_name": change.module_name,
                "file_path": change.file_path,
                "full_path": change.full_path or "",
                "original_content": change.original_content or "",
                "proposed_content": change.proposed_content or "",
            }
            for change in staged
        ]

        # Validate against the branch the review branch would be cut from, so a
        # rejected commit never leaves an orphan branch behind on GitHub.
        if conv.review_branch:
            tree_entries = github._prepare_tree_entries(conv.review_branch, payload)
        else:
            tree_entries = github._prepare_tree_entries(conv.base_branch, payload)
            conv.review_branch = conv._new_review_branch_name()
            github._create_branch(conv.review_branch, from_branch=conv.base_branch)

        commit_message = (message or f"Claude changes: {conv.name}").strip()[:200]
        result = github._commit_files(
            conv.review_branch,
            payload,
            commit_message,
            tree_entries=tree_entries,
        )
        staged.write({"status": "committed", "commit_sha": result["commit_sha"]})
        conv.write({
            "commit_sha": result["commit_sha"],
            "state": "committed",
        })
        conv._audit(
            "git_commit",
            branch=conv.review_branch,
            details=commit_message,
            commit_sha=result["commit_sha"],
        )
        return self._conversation_payload(conv)

    @api.model
    def create_workspace_pull_request(self, conversation_id, title=None, body=None):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not access["can_create_pr"]:
            raise AccessError(_("Pull request creation is disabled or you do not have permission."))
        if not conv.review_branch or not conv.commit_sha:
            raise UserError(_("Commit the staged changes before creating a pull request."))
        if conv.pull_request_url:
            return self._conversation_payload(conv)

        result = self.env["centric.claude.github.client"]._create_pull_request(
            conv.review_branch,
            conv.base_branch,
            title or f"Claude: {conv.name}",
            body=body or (
                "Created from the Centric Claude Integration in Odoo.\n\n"
                "Review the diff and allow Odoo.sh to validate the branch before merging."
            ),
        )
        conv.write({
            "pull_request_number": result.get("number") or 0,
            "pull_request_url": result.get("url"),
        })
        conv._audit(
            "pull_request",
            branch=conv.review_branch,
            details=f"Created pull request #{result.get('number')}",
            commit_sha=conv.commit_sha,
        )
        return self._conversation_payload(conv)

    @api.model
    def get_repository_modules(self, conversation_id):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not access["can_read_code"]:
            raise AccessError(_("Repository code reading is disabled or you do not have permission."))
        branch = conv.review_branch or conv.base_branch
        modules = self.env["centric.claude.github.client"]._list_allowed_modules(branch=branch)
        known = {module["name"] for module in modules}
        for change in conv.change_ids.filtered(
            lambda change: change.status == "staged" and change.is_new_module
        ):
            if change.module_name in known:
                continue
            known.add(change.module_name)
            modules.append({
                "name": change.module_name,
                "root": conv._pending_module_root(change.module_name) or change.module_name,
                "manifest_path": "",
                "staged_only": True,
            })
        modules.sort(key=lambda module: module["name"].lower())
        conv._audit("repo_read", branch=branch, details="Opened repository module browser.")
        return modules

    @api.model
    def get_repository_module_files(self, conversation_id, module_name):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not access["can_read_code"]:
            raise AccessError(_("Repository code reading is disabled or you do not have permission."))
        branch = conv.review_branch or conv.base_branch
        staged = conv.change_ids.filtered(
            lambda change: change.status == "staged" and change.module_name == module_name
        )
        if conv._pending_module_root(module_name):
            # The module exists only as staged changes; there is nothing on the
            # branch to list.
            files = []
        else:
            files = self.env["centric.claude.github.client"]._list_module_files(
                module_name, branch=branch
            )
        known = {item["path"] for item in files}
        for change in staged:
            if change.file_path in known:
                continue
            known.add(change.file_path)
            files.append({
                "path": change.file_path,
                "size": len(change.proposed_content or ""),
                "sha": False,
                "staged_only": True,
            })
        files.sort(key=lambda item: item["path"].lower())
        conv._audit("repo_read", branch=branch, module_name=module_name, details="Opened module file list.")
        return files

    @api.model
    def get_repository_file(self, conversation_id, module_name, file_path):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not access["can_read_code"]:
            raise AccessError(_("Repository code reading is disabled or you do not have permission."))
        branch = conv.review_branch or conv.base_branch
        github = self.env["centric.claude.github.client"]
        staged = conv.change_ids.filtered(
            lambda change: change.status == "staged"
            and change.module_name == module_name
            and change.file_path == file_path
        )[:1]
        # A file staged but not committed has no version on the branch yet, so
        # reading it must not 404 the whole request.
        data = None
        if not conv._pending_module_root(module_name):
            data = github._read_module_file(
                module_name, file_path, branch=branch, allow_missing=bool(staged)
            )
        if data is None:
            data = {
                "module": module_name,
                "path": file_path,
                "full_path": staged.full_path or "",
                "sha": False,
                "content": "",
                "branch": branch,
            }
        if staged:
            data["staged_content"] = staged.proposed_content
            data["change_id"] = staged.id
        conv._audit(
            "repo_read",
            branch=branch,
            module_name=module_name,
            file_path=file_path,
            details="Opened repository source file in workspace.",
        )
        return data

    def _new_review_branch_name(self):
        self.ensure_one()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        slug = re.sub(r"[^a-z0-9-]+", "-", (self.name or "change").lower()).strip("-")[:32]
        slug = slug or "change"
        return f"claude/odoo-{self.id}-{slug}-{timestamp}"

    @api.model
    def _make_diff(self, file_path, original, proposed):
        return "".join(difflib.unified_diff(
            (original or "").splitlines(keepends=True),
            (proposed or "").splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        ))

    def _audit(
        self,
        action,
        *,
        branch=None,
        module_name=None,
        file_path=None,
        details=None,
        commit_sha=None,
        success=True,
    ):
        self.ensure_one()
        access = self._workspace_access()
        self.env["centric.claude.audit.log"].sudo().create({
            "action": action,
            "user_id": self.env.user.id,
            "conversation_id": self.id,
            "repository": access.get("repository"),
            "branch": branch or self.review_branch or self.base_branch,
            "module_name": module_name,
            "file_path": file_path,
            "details": details,
            "commit_sha": commit_sha,
            "success": success,
        })

    @api.model
    def _effort_choices(self):
        """The levels and their labels, for the picker."""
        field = self._fields["effort"]
        selection = field.selection
        if callable(selection):
            selection = selection(self)
        return [{"value": value, "label": label} for value, label in selection]

    @api.model
    def _conversation_summary(self, conv):
        return {
            "effort": conv.effort,
            "id": conv.id,
            "name": conv.name,
            "project_id": conv.project_id.id or False,
            "developer_mode": conv.developer_mode,
            "base_branch": conv.base_branch,
            "review_branch": conv.review_branch or "",
            "state": conv.state,
            "write_date": fields.Datetime.to_string(conv.write_date) if conv.write_date else "",
        }

    @api.model
    def _conversation_payload(self, conv):
        conv._check_owner()
        return {
            "conversation": self._conversation_summary(conv) | {
                "commit_sha": conv.commit_sha or "",
                "pull_request_number": conv.pull_request_number or 0,
                "pull_request_url": conv.pull_request_url or "",
            },
            "messages": [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "attachments": [
                        attachment._summary() for attachment in msg.attachment_ids
                    ],
                    "create_date": fields.Datetime.to_string(msg.create_date) if msg.create_date else "",
                }
                for msg in conv.message_ids.filtered(lambda msg: msg.role in {"user", "assistant"}).sorted("id")
            ],
            "changes": [
                {
                    "id": change.id,
                    "module_name": change.module_name,
                    "file_path": change.file_path,
                    "summary": change.summary or "",
                    "diff_text": change.diff_text or "",
                    "status": change.status,
                    "commit_sha": change.commit_sha or "",
                    "staged_at": fields.Datetime.to_string(change.staged_at) if change.staged_at else "",
                }
                for change in conv.change_ids.sorted("id", reverse=True)
            ],
            "operations": [
                operation._payload() for operation in conv.operation_ids.sorted("id")
            ],
            "access": self._workspace_access(),
            "agent": self._agent_status(conv),
            # Images uploaded but not yet sent, so a reload does not lose them.
            "pending_attachments": [
                attachment._summary()
                for attachment in self.env["centric.claude.attachment"]._pending_for(conv)
            ],
            # The sidebar shows a per-project chat count, so it has to follow
            # every payload that could have moved a chat between projects.
            "projects": self.env["centric.claude.project"]._workspace_projects(),
        }

    @api.model
    def _agent_status(self, conv):
        """What the browser needs to decide whether to keep polling."""
        backend = self._param("centric_claude.backend", "agent")
        if backend != "agent":
            return {"backend": backend, "waiting": False}
        Turn = self.env["centric.claude.turn"]
        # Whether *a* bridge is alive, separately from what this turn is doing:
        # a question queued with nothing listening would otherwise spin forever
        # with no hint that the laptop side is simply not running.
        online, last_seen, connected_agent = Turn._agent_online()
        turn = Turn.sudo().search(
            [("conversation_id", "=", conv.id)], order="id desc", limit=1
        )
        return {
            "backend": backend,
            "waiting": bool(turn) and turn.state in ("pending", "running"),
            "state": turn.state if turn else "",
            "agent_name": (turn.agent_name or "") if turn else "",
            "online": online,
            "last_seen": last_seen,
            "connected_agent": connected_agent,
            # Questions are answered one at a time, so a queue behind you is the
            # difference between "slow" and "broken".
            "queue_position": Turn._queue_position(turn),
        }

    @api.model
    def apply_workspace_operation(self, conversation_id, operation_id):
        """The user answered Yes to a proposed change: carry it out."""
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        operation = self.env["centric.claude.operation"].browse(
            int(operation_id)
        ).exists()
        if not operation or operation.conversation_id != conv:
            raise UserError(_("That proposed change was not found."))
        result = operation.apply()
        # Record the answer in the conversation, so the transcript shows what
        # the user agreed to and Claude can see it happened on the next turn.
        self.env["centric.claude.message"].create({
            "conversation_id": conv.id,
            "role": "assistant",
            "content": _("Confirmed by %(user)s. %(result)s") % {
                "user": self.env.user.name, "result": result
            },
        })
        return self._conversation_payload(conv)

    @api.model
    def reject_workspace_operation(self, conversation_id, operation_id):
        """The user answered No."""
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        operation = self.env["centric.claude.operation"].browse(
            int(operation_id)
        ).exists()
        if not operation or operation.conversation_id != conv:
            raise UserError(_("That proposed change was not found."))
        operation.reject()
        self.env["centric.claude.message"].create({
            "conversation_id": conv.id,
            "role": "assistant",
            "content": _("%(user)s declined: %(summary)s") % {
                "user": self.env.user.name, "summary": operation.summary
            },
        })
        return self._conversation_payload(conv)

    @api.model
    def poll_workspace_conversation(self, conversation_id, after_message_id=0):
        """Cheap poll while a queued turn is in flight.

        Returns the full payload only once something actually changed, so the
        browser can poll on a short interval without re-sending the transcript.
        """
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        latest = conv.message_ids.sorted("id")[-1:]
        latest_id = latest.id if latest else 0
        if latest_id > int(after_message_id or 0):
            return self._conversation_payload(conv)
        return {"unchanged": True, "agent": self._agent_status(conv)}

    @api.model
    def cancel_workspace_turn(self, conversation_id):
        """Stop waiting on a queued turn the bridge never picked up."""
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        pending = self.env["centric.claude.turn"].sudo().search([
            ("conversation_id", "=", conv.id),
            ("state", "in", ("pending", "running")),
        ])
        pending.write({"state": "cancelled", "finished_at": fields.Datetime.now()})
        return self._conversation_payload(conv)


class CentricClaudeMessage(models.Model):
    _name = "centric.claude.message"
    _description = "Claude Developer Message"
    _order = "id asc"

    conversation_id = fields.Many2one(
        "centric.claude.conversation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    role = fields.Selection(
        [("user", "User"), ("assistant", "Assistant"), ("tool", "Tool")],
        required=True,
        index=True,
    )
    content = fields.Text(required=True)
    attachment_ids = fields.One2many(
        "centric.claude.attachment", "message_id", string="Attachments",
    )


class CentricClaudeChange(models.Model):
    _name = "centric.claude.change"
    _description = "Claude Staged Code Change"
    _order = "id desc"

    conversation_id = fields.Many2one(
        "centric.claude.conversation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    module_name = fields.Char(required=True, index=True)
    file_path = fields.Char(required=True, index=True)
    # The repository path resolved when the change was staged. A module created
    # in this conversation has no root to look up on the branch at commit time.
    full_path = fields.Char()
    summary = fields.Char()
    # Not required: a brand-new file has an empty baseline, and Odoo stores an
    # empty string as NULL, which a required field would reject. Read these
    # through `or ""` rather than assuming they are strings.
    original_content = fields.Text()
    proposed_content = fields.Text()
    diff_text = fields.Text()
    # True when this change is part of a module that did not exist on the
    # branch when it was staged.
    is_new_module = fields.Boolean(default=False)
    status = fields.Selection(
        [
            ("staged", "Staged"),
            ("committed", "Committed"),
            ("discarded", "Discarded"),
        ],
        default="staged",
        required=True,
        index=True,
    )
    staged_by = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    staged_at = fields.Datetime(default=fields.Datetime.now, required=True)
    commit_sha = fields.Char(index=True)
