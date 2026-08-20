from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestClaudeWorkspace(TransactionCase):
    """Offline tests: nothing here contacts Anthropic or GitHub."""

    def setUp(self):
        super().setUp()
        self.Conversation = self.env["centric.claude.conversation"]
        self.params = self.env["ir.config_parameter"].sudo()
        self._configure()

    def _configure(self, **overrides):
        values = {
            "centric_claude.enabled": "True",
            "centric_claude.api_key": "sk-ant-test",
            "centric_claude.model": "claude-opus-5",
            "centric_claude.max_tokens": "16000",
            "centric_claude.github_owner": "centricmt",
            "centric_claude.github_repo": "odoo-addons",
            "centric_claude.allowed_module_prefix": "centric_",
            "centric_claude.code_read_enabled": "True",
            "centric_claude.code_write_enabled": "True",
            "centric_claude.pull_request_enabled": "True",
        }
        values.update(overrides)
        for key, value in values.items():
            self.params.set_param(key, value)

    def _conversation(self, developer_mode=False):
        return self.Conversation.create({
            "name": "Fix Talexio Attendance",
            "user_id": self.env.user.id,
            "base_branch": "testing",
            "developer_mode": developer_mode,
        })

    # -- helpers ----------------------------------------------------------
    def test_unified_diff_is_generated(self):
        diff = self.Conversation._make_diff(
            "models/example.py",
            "value = 1\n",
            "value = 2\n",
        )
        self.assertIn("-value = 1", diff)
        self.assertIn("+value = 2", diff)

    def test_review_branch_name_is_scoped_to_conversation(self):
        conversation = self._conversation()
        branch = conversation._new_review_branch_name()
        self.assertTrue(branch.startswith(f"claude/odoo-{conversation.id}-fix-talexio-attendance-"))

    def test_default_names_include_the_translated_placeholder(self):
        """Auto-naming must still fire on a non-English UI."""
        self.assertIn("New Claude Conversation", self.Conversation._default_names())

    # -- settings ---------------------------------------------------------
    def test_disabling_a_permission_actually_disables_it(self):
        """`set_param(key, False)` deletes the row, so these must be stored as text.

        Without the explicit write in res.config.settings.set_values, unticking a
        permission that defaults to True silently leaves it enabled.
        """
        settings = self.env["res.config.settings"].create({
            "centric_claude_enabled": True,
            "centric_claude_code_write_enabled": True,
            "centric_claude_code_read_enabled": False,
            "centric_claude_pull_request_enabled": False,
        })
        settings.set_values()

        self.assertEqual(self.params.get_param("centric_claude.code_read_enabled"), "False")
        self.assertEqual(self.params.get_param("centric_claude.pull_request_enabled"), "False")
        access = self.Conversation._workspace_access()
        self.assertFalse(access["can_read_code"])
        self.assertFalse(access["can_create_pr"])

    def test_global_switches_close_every_gate(self):
        self._configure(**{"centric_claude.enabled": "False"})
        access = self.Conversation._workspace_access()
        self.assertFalse(access["can_chat"])
        self.assertFalse(access["can_read_code"])
        self.assertFalse(access["can_develop"])
        self.assertFalse(access["can_create_pr"])

    # -- tool surface -----------------------------------------------------
    def test_tool_schemas_satisfy_strict_tool_use(self):
        """Strict schemas need `additionalProperties: false` and a `required` list."""
        conversation = self._conversation(developer_mode=True)
        tools = conversation._tool_definitions(self.Conversation._workspace_access())
        self.assertTrue(tools)
        for tool in tools:
            schema = tool["input_schema"]
            self.assertTrue(tool.get("strict"), tool["name"])
            self.assertIs(schema["additionalProperties"], False, tool["name"])
            self.assertIn("required", schema, tool["name"])
            self.assertEqual(
                set(schema["required"]) - set(schema["properties"]),
                set(),
                "%s requires a property it does not declare" % tool["name"],
            )

    def test_repository_tools_are_hidden_and_blocked_without_read_access(self):
        self._configure(**{"centric_claude.code_read_enabled": "False"})
        conversation = self._conversation()
        access = self.Conversation._workspace_access()
        names = [tool["name"] for tool in conversation._tool_definitions(access)]
        self.assertNotIn("read_module_file", names)
        self.assertNotIn("search_module_code", names)
        with self.assertRaises(AccessError):
            conversation._execute_tool(
                "read_module_file",
                {"module": "centric_demo", "path": "models/demo.py"},
                access,
            )

    def test_stage_tool_requires_developer_mode(self):
        conversation = self._conversation(developer_mode=False)
        access = self.Conversation._workspace_access()
        names = [tool["name"] for tool in conversation._tool_definitions(access)]
        self.assertNotIn("stage_file_change", names)
        with self.assertRaises(AccessError):
            conversation._execute_tool(
                "stage_file_change",
                {
                    "module": "centric_demo",
                    "path": "models/demo.py",
                    "new_content": "x",
                    "summary": "y",
                },
                access,
            )

    def test_developer_mode_denial_is_audited(self):
        self._configure(**{"centric_claude.code_write_enabled": "False"})
        conversation = self._conversation()
        with self.assertRaises(AccessError):
            self.Conversation.set_workspace_developer_mode(conversation.id, True)
        denied = self.env["centric.claude.audit.log"].sudo().search([
            ("conversation_id", "=", conversation.id),
            ("action", "=", "security_denied"),
        ])
        self.assertEqual(len(denied), 1)
        self.assertFalse(denied.success)

    def test_system_prompt_reflects_the_current_mode(self):
        conversation = self._conversation(developer_mode=True)
        access = self.Conversation._workspace_access()
        self.assertIn("Developer Mode: ON", conversation._system_prompt(access))
        self.assertIn("stage_file_change", conversation._system_prompt(access))
        conversation.developer_mode = False
        self.assertIn("read-only", conversation._system_prompt(access))

    # -- repository sandbox ------------------------------------------------
    def test_path_traversal_is_rejected(self):
        """`root` is passed in, so this never touches the network."""
        github = self.env["centric.claude.github.client"]
        for path in ("../../other_module/secret.py",
                     "models/../../other_module/secret.py",
                     "/../other_module/secret.py",
                     "..",
                     "models/..",
                     ""):
            with self.assertRaises(Exception, msg="path %r was not rejected" % path):
                github._validate_module_file("centric_demo", path, root="centric_demo")

    def test_blocked_and_non_text_paths_are_rejected(self):
        github = self.env["centric.claude.github.client"]
        for path in (".env", "requirements.txt", "static/description/icon.png"):
            with self.assertRaises(Exception, msg="path %r was not rejected" % path):
                github._validate_module_file("centric_demo", path, root="centric_demo")
        root, full_path = github._validate_module_file(
            "centric_demo", "models/demo.py", root="centric_demo"
        )
        self.assertEqual(root, "centric_demo")
        self.assertEqual(full_path, "centric_demo/models/demo.py")

    def test_installed_module_filter_respects_the_prefix(self):
        """`like 'centric_%'` is SQL LIKE, where `_` matches any single character."""
        conversation = self._conversation()
        access = self.Conversation._workspace_access()
        modules = conversation._execute_tool("list_installed_custom_modules", {}, access)
        prefix = access["allowed_module_prefix"]
        for module in modules:
            self.assertTrue(
                module["name"].startswith(prefix),
                "%s does not start with %s" % (module["name"], prefix),
            )

    def test_describe_odoo_model_returns_field_metadata(self):
        conversation = self._conversation()
        access = self.Conversation._workspace_access()
        described = conversation._execute_tool(
            "describe_odoo_model", {"model": "centric.claude.change"}, access
        )
        self.assertTrue(described["found"])
        self.assertIn("proposed_content", [field["name"] for field in described["fields"]])
        missing = conversation._execute_tool(
            "describe_odoo_model", {"model": "no.such.model"}, access
        )
        self.assertFalse(missing["found"])

    # -- API request shape -------------------------------------------------
    def test_request_uses_adaptive_thinking_and_caching(self):
        captured = {}

        class Response:
            status_code = 200

            @staticmethod
            def json():
                return {"content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn"}

        def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
            captured["url"] = url
            captured["headers"] = headers
            captured["body"] = json
            return Response()

        with patch("odoo.addons.centric_claude_integration.models.claude_client.requests.post",
                   fake_post):
            self.env["centric.claude.client"]._create_message(
                [{"role": "user", "content": "hello"}],
                system="be brief",
                tools=[{
                    "name": "noop",
                    "description": "does nothing",
                    "input_schema": {
                        "type": "object", "properties": {},
                        "required": [], "additionalProperties": False,
                    },
                    "strict": True,
                }],
            )

        body = captured["body"]
        self.assertEqual(captured["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(captured["headers"]["x-api-key"], "sk-ant-test")
        self.assertEqual(body["model"], "claude-opus-5")
        self.assertEqual(body["max_tokens"], 16000)
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertEqual(body["output_config"], {"effort": "high"})
        self.assertEqual(body["cache_control"], {"type": "ephemeral"})
        # budget_tokens is rejected by every model this addon targets.
        self.assertNotIn("budget_tokens", str(body))

    def test_api_key_never_reaches_the_request_body(self):
        conversation = self._conversation(developer_mode=True)
        access = self.Conversation._workspace_access()
        payload = str(conversation._tool_definitions(access)) + conversation._system_prompt(access)
        self.assertNotIn("sk-ant-test", payload)
        self.assertNotIn(self.params.get_param("centric_claude.github_token") or "!", payload)

    # -- local agent backend ------------------------------------------------
    def test_agent_backend_queues_instead_of_calling_anthropic(self):
        self._configure(**{"centric_claude.backend": "agent"})
        conversation = self._conversation(developer_mode=True)
        self.Conversation.send_workspace_message(conversation.id, "fix the importer")
        turn = self.env["centric.claude.turn"].search([
            ("conversation_id", "=", conversation.id)
        ])
        self.assertEqual(len(turn), 1)
        self.assertEqual(turn.state, "pending")
        self.assertEqual(turn.prompt, "fix the importer")
        self.assertTrue(turn.developer_mode)
        # The user's message is stored; the reply arrives later from the bridge.
        self.assertEqual(conversation.message_ids.mapped("role"), ["user"])

    def test_agent_payload_carries_no_credentials(self):
        self._configure(**{"centric_claude.backend": "agent"})
        conversation = self._conversation()
        self.Conversation.send_workspace_message(conversation.id, "hello")
        turn = self.env["centric.claude.turn"].search([
            ("conversation_id", "=", conversation.id)
        ])
        payload = str(turn._payload_for_agent())
        for secret in ("sk-ant-test", self.params.get_param("centric_claude.github_token") or "!"):
            self.assertNotIn(secret, payload)

    def test_cancelling_a_queued_turn(self):
        self._configure(**{"centric_claude.backend": "agent"})
        conversation = self._conversation()
        self.Conversation.send_workspace_message(conversation.id, "hello")
        payload = self.Conversation.cancel_workspace_turn(conversation.id)
        self.assertFalse(payload["agent"]["waiting"])
        turn = self.env["centric.claude.turn"].search([
            ("conversation_id", "=", conversation.id)
        ])
        self.assertEqual(turn.state, "cancelled")

    def test_agent_token_is_generated_and_stored(self):
        settings = self.env["res.config.settings"].create({})
        settings.action_generate_agent_token()
        token = self.params.get_param("centric_claude.agent_token")
        self.assertTrue(token)
        self.assertGreaterEqual(len(token), 32)
