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
    developer_mode = fields.Boolean(default=False)
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

    @api.model
    def _default_branch(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            "centric_claude.default_branch", "testing"
        ) or "testing"

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
        return {
            "enabled": enabled,
            "can_chat": enabled and is_user,
            "can_read_code": enabled and read_enabled and (is_reader or is_developer or is_admin),
            "can_develop": enabled and write_enabled and (is_developer or is_admin),
            "can_create_pr": enabled and write_enabled and pr_enabled and (is_developer or is_admin),
            "can_admin": is_admin,
            "repository": f"{owner}/{repo}" if owner and repo else "",
            "default_branch": self._default_branch(),
            "allowed_module_prefix": self._param("centric_claude.allowed_module_prefix", "centric_"),
            "user_name": user.name,
        }

    @api.model
    def workspace_bootstrap(self):
        access = self._workspace_access()
        conversations = self.search([("user_id", "=", self.env.user.id)], limit=50)
        return {
            "access": access,
            "conversations": [self._conversation_summary(conv) for conv in conversations],
        }

    @api.model
    def create_workspace_conversation(self, name=None):
        access = self._workspace_access()
        if not access["can_chat"]:
            raise AccessError(_("You do not have access to the Claude workspace."))
        conv = self.create({
            "name": (name or _("New Claude Conversation")).strip()[:120],
            "user_id": self.env.user.id,
            "base_branch": access["default_branch"],
        })
        return self._conversation_payload(conv)

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
    def send_workspace_message(self, conversation_id, text):
        conv = self.browse(int(conversation_id)).exists()
        if not conv:
            raise UserError(_("Claude conversation not found."))
        conv._check_owner()
        access = self._workspace_access()
        if not access["can_chat"]:
            raise AccessError(_("Claude is disabled or you do not have workspace access."))
        text = (text or "").strip()
        if not text:
            raise ValidationError(_("Enter a message first."))
        if len(text) > 30000:
            raise ValidationError(_("Messages are limited to 30,000 characters."))

        self.env["centric.claude.message"].create({
            "conversation_id": conv.id,
            "role": "user",
            "content": text,
        })
        if conv.name in conv._default_names():
            conv.name = text.splitlines()[0][:80]

        if self._param("centric_claude.backend", "agent") == "agent":
            # Odoo.sh cannot run the Claude Code CLI, so the turn is queued for the
            # developer's local bridge to claim. The browser polls for the answer.
            self.env["centric.claude.turn"].create({
                "conversation_id": conv.id,
                "user_id": self.env.user.id,
                "prompt": text,
                "developer_mode": conv.developer_mode,
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
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in history_records
        ]
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
""".strip()

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
                "description": "Describe an Odoo model schema and its fields. This does not read business records or secret values.",
                "input_schema": {
                    "type": "object",
                    "properties": {"model": {"type": "string"}},
                    "required": ["model"],
                    "additionalProperties": False,
                },
                "strict": True,
            },
        ]
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

    def _execute_tool(self, tool_name, tool_input, access):
        self.ensure_one()
        github = self.env["centric.claude.github.client"]
        branch = self.review_branch or self.base_branch

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

    def _stage_change(self, module_name, file_path, new_content, summary=None):
        self.ensure_one()
        access = self._workspace_access()
        if not self.developer_mode or not access["can_develop"]:
            raise AccessError(_("Developer Mode is not enabled or you do not have code-write permission."))
        if len(new_content or "") > 512000:
            raise ValidationError(_("Staged files are limited to 500 KB."))
        branch = self.review_branch or self.base_branch
        # allow_missing lets Claude add a file to an approved module. The module
        # itself must already exist, so a brand-new module still cannot appear.
        current = self.env["centric.claude.github.client"]._read_module_file(
            module_name, file_path, branch=branch, allow_missing=True
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
            "original_content": original_content,
            "proposed_content": new_content,
            "diff_text": diff_text,
            # Flag new files so the Changes tab shows at a glance that this adds
            # a file rather than editing one.
            "summary": (("New file: " if current is None else "")
                        + (summary or "Code change staged by Claude"))[:500],
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
        files = self.env["centric.claude.github.client"]._list_module_files(module_name, branch=branch)
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
        data = self.env["centric.claude.github.client"]._read_module_file(module_name, file_path, branch=branch)
        staged = conv.change_ids.filtered(
            lambda change: change.status == "staged"
            and change.module_name == module_name
            and change.file_path == file_path
        )[:1]
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
    def _conversation_summary(self, conv):
        return {
            "id": conv.id,
            "name": conv.name,
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
            "access": self._workspace_access(),
            "agent": self._agent_status(conv),
        }

    @api.model
    def _agent_status(self, conv):
        """What the browser needs to decide whether to keep polling."""
        backend = self._param("centric_claude.backend", "agent")
        if backend != "agent":
            return {"backend": backend, "waiting": False}
        turn = self.env["centric.claude.turn"].sudo().search(
            [("conversation_id", "=", conv.id)], order="id desc", limit=1
        )
        return {
            "backend": backend,
            "waiting": bool(turn) and turn.state in ("pending", "running"),
            "state": turn.state if turn else "",
            "agent_name": (turn.agent_name or "") if turn else "",
        }

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
    summary = fields.Char()
    # Not required: a brand-new file has an empty baseline, and Odoo stores an
    # empty string as NULL, which a required field would reject. Read these
    # through `or ""` rather than assuming they are strings.
    original_content = fields.Text()
    proposed_content = fields.Text()
    diff_text = fields.Text()
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
