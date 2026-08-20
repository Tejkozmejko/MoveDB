from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
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

    # -- creating modules -------------------------------------------------
    def _github(self, modules):
        """Patch the module listing so name rules can be tested without GitHub."""
        return patch.object(
            type(self.env["centric.claude.github.client"]),
            "_list_allowed_modules",
            lambda self, branch=None, tree=None: modules,
        )

    def test_a_new_module_root_sits_beside_the_existing_ones(self):
        github = self.env["centric.claude.github.client"]
        with self._github([
            {"name": "centric_a", "root": "addons/centric_a"},
            {"name": "centric_b", "root": "addons/centric_b"},
            {"name": "centric_c", "root": "centric_c"},
        ]):
            self.assertEqual(
                github._new_module_root("centric_new"), "addons/centric_new"
            )

    def test_a_new_module_root_defaults_to_the_repository_root(self):
        github = self.env["centric.claude.github.client"]
        with self._github([]):
            self.assertEqual(github._new_module_root("centric_new"), "centric_new")

    def test_a_new_module_must_use_the_approved_prefix(self):
        github = self.env["centric.claude.github.client"]
        with self._github([]):
            with self.assertRaises(UserError):
                github._new_module_root("other_module")

    def test_a_new_module_name_must_be_a_valid_identifier(self):
        github = self.env["centric.claude.github.client"]
        with self._github([]):
            for name in ("centric mod", "Centric_Mod", "../escape", "9centric", ""):
                with self.assertRaises(UserError, msg=name):
                    github._new_module_root(name)

    def test_an_existing_module_cannot_be_recreated(self):
        github = self.env["centric.claude.github.client"]
        with self._github([{"name": "centric_a", "root": "centric_a"}]):
            with self.assertRaises(UserError):
                github._new_module_root("centric_a")

    def test_creating_a_module_needs_a_manifest(self):
        conversation = self._conversation(developer_mode=True)
        with self._github([]):
            with self.assertRaises(UserError):
                self.Conversation.create_workspace_module(
                    conversation.id, "centric_new",
                    [{"path": "models/thing.py", "content": "X = 1\n"}],
                )

    def test_creating_a_module_needs_developer_mode(self):
        conversation = self._conversation(developer_mode=False)
        with self._github([]):
            with self.assertRaises(AccessError):
                self.Conversation.create_workspace_module(
                    conversation.id, "centric_new",
                    [{"path": "__manifest__.py", "content": "{}\n"}],
                )

    def test_creating_a_module_needs_the_write_permission(self):
        self._configure(**{"centric_claude.code_write_enabled": "False"})
        conversation = self._conversation(developer_mode=True)
        with self._github([]):
            with self.assertRaises(AccessError):
                self.Conversation.create_workspace_module(
                    conversation.id, "centric_new",
                    [{"path": "__manifest__.py", "content": "{}\n"}],
                )

    def test_a_staged_change_records_its_full_repository_path(self):
        conversation = self._conversation(developer_mode=True)
        change = self.env["centric.claude.change"].create({
            "conversation_id": conversation.id,
            "module_name": "centric_a",
            "file_path": "models/thing.py",
            "full_path": "addons/centric_a/models/thing.py",
            "is_new_module": True,
            "proposed_content": "X = 1\n",
        })
        self.assertEqual(
            conversation._pending_module_root("centric_a"), "addons/centric_a"
        )
        change.status = "committed"
        # Once committed the module is real, so it is no longer pending.
        self.assertIsNone(conversation._pending_module_root("centric_a"))

    # -- odoo data access -------------------------------------------------
    def _data(self):
        return self.env["centric.claude.data"]

    def _as_level(self, level):
        """A fresh user holding exactly one Claude data level."""
        group = {
            "user": "centric_claude_integration.group_data_user",
            "intermediate": "centric_claude_integration.group_data_intermediate",
            "admin": "centric_claude_integration.group_data_admin",
        }
        user = self.env["res.users"].create({
            "name": "Claude %s" % level,
            "login": "claude_%s_%s" % (level, self.env.cr.dbname[-4:]),
            "groups_id": [
                (4, self.env.ref("base.group_user").id),
                (4, self.env.ref("centric_claude_integration.group_claude_user").id),
                (4, self.env.ref(group[level]).id),
            ],
        })
        return self.env(user=user)

    def test_the_three_levels_are_distinct(self):
        for level in ("user", "intermediate", "admin"):
            env = self._as_level(level)
            self.assertEqual(env["centric.claude.data"]._level(), level)

    def test_a_user_without_a_data_group_has_no_level(self):
        user = self.env["res.users"].create({
            "name": "Plain", "login": "claude_plain_%s" % self.env.cr.dbname[-4:],
            "groups_id": [(4, self.env.ref("base.group_user").id)],
        })
        self.assertEqual(self.env(user=user)["centric.claude.data"]._level(), "none")

    def test_group_implications_replace_rather_than_append(self):
        """implied_ids must use (6, 0, ids), never (4, id).

        (4, id) links a group and nothing ever unlinks it: an implication
        deleted from claude_security.xml would survive every future upgrade,
        silently granting access the file no longer describes. This bit once -
        Claude Administrator kept implying Data Administrator after the line
        was removed, which floored the data dropdown at Administrator.
        """
        import os
        import re

        # Resolve through the addon package rather than __file__, so this works
        # wherever the test module itself happens to be loaded from.
        import odoo.addons.centric_claude_integration as addon

        path = os.path.join(
            os.path.dirname(addon.__file__), "security", "claude_security.xml"
        )
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        implications = re.findall(
            r'name="implied_ids"\s+eval="([^"]+)"', source
        )
        self.assertTrue(implications, "no implied_ids found to check")
        for expression in implications:
            self.assertNotIn("(4,", expression.replace(" ", ""),
                             "implied_ids must replace, not append: %s" % expression)
            self.assertIn("(6,0,", expression.replace(" ", ""),
                          "implied_ids must use (6, 0, ids): %s" % expression)

    def test_the_code_ladder_implies_no_data_level(self):
        admin = self.env.ref("centric_claude_integration.group_claude_admin")
        data_groups = {
            self.env.ref("centric_claude_integration.group_data_user").id,
            self.env.ref("centric_claude_integration.group_data_intermediate").id,
            self.env.ref("centric_claude_integration.group_data_admin").id,
        }
        reachable = set(admin.trans_implied_ids.ids) | {admin.id}
        self.assertFalse(
            reachable & data_groups,
            "Claude Administrator still implies a data level, which floors the "
            "Centric Claude Data dropdown so no lower level can be chosen.",
        )

    def test_all_three_data_levels_exist(self):
        for name in ("group_data_user", "group_data_intermediate", "group_data_admin"):
            group = self.env.ref("centric_claude_integration.%s" % name, False)
            self.assertTrue(group, "%s is missing" % name)
            self.assertEqual(
                group.privilege_id,
                self.env.ref("centric_claude_integration.res_groups_privilege_claude_data"),
            )

    def test_the_two_ladders_are_independent(self):
        """Code access confers no data level, and vice versa.

        They were briefly chained, which had two costs: a developer silently
        gained the right to read every record, and Odoo floors a privilege
        dropdown at whatever another group implies, so Administrator became the
        only选 selectable data level for anyone holding Claude Administrator.
        """
        code_admin = self.env["res.users"].create({
            "name": "Code Only",
            "login": "claude_codeonly_%s" % self.env.cr.dbname[-4:],
            "groups_id": [
                (4, self.env.ref("base.group_user").id),
                (4, self.env.ref("centric_claude_integration.group_claude_admin").id),
            ],
        })
        self.assertTrue(
            code_admin.has_group("centric_claude_integration.group_claude_admin")
        )
        self.assertEqual(self.env(user=code_admin)["centric.claude.data"]._level(), "none")

        data_admin = self._as_level("admin")
        self.assertFalse(
            data_admin["centric.claude.conversation"]._workspace_access()["can_develop"]
        )

    def test_only_intermediate_and_above_may_change_records(self):
        self.assertFalse(
            self._as_level("user")["centric.claude.data"]._data_access()["can_propose"]
        )
        for level in ("intermediate", "admin"):
            self.assertTrue(
                self._as_level(level)["centric.claude.data"]._data_access()["can_propose"],
                level,
            )

    def test_reading_respects_the_users_own_permissions(self):
        # res.partner is readable by any internal user; the point is that the
        # query runs as that user rather than as superuser.
        env = self._as_level("user")
        result = env["centric.claude.data"].search_records("res.partner", limit=5)
        self.assertEqual(result["model"], "res.partner")
        self.assertLessEqual(result["returned"], 5)

    def test_the_parameter_table_holding_our_keys_is_never_readable(self):
        for level in ("user", "intermediate", "admin"):
            env = self._as_level(level)
            with self.assertRaises(AccessError, msg=level):
                env["centric.claude.data"].search_records("ir.config_parameter")

    def test_password_fields_are_filtered_out(self):
        fields_seen = self._data()._readable_fields(self.env["res.users"])
        for name in fields_seen:
            self.assertNotIn("password", name.lower())

    def test_intermediate_may_not_change_users_or_settings(self):
        env = self._as_level("intermediate")
        for model_name in ("res.users", "res.groups", "res.config.settings"):
            with self.assertRaises(AccessError, msg=model_name):
                env["centric.claude.data"]._require_write(model_name)

    def test_nobody_may_change_claude_s_own_configuration(self):
        for level in ("intermediate", "admin"):
            env = self._as_level(level)
            for model_name in ("ir.config_parameter", "ir.rule", "ir.model.access",
                               "centric.claude.conversation"):
                with self.assertRaises(AccessError, msg="%s/%s" % (level, model_name)):
                    env["centric.claude.data"]._require_write(model_name)

    def test_a_domain_is_never_evaluated_as_code(self):
        with self.assertRaises(UserError):
            self._data().search_records("res.partner", domain="__import__('os').listdir('.')")

    def test_a_change_is_proposed_not_performed(self):
        conversation = self._conversation()
        before = self.env["res.partner"].search_count([("name", "=", "Claude Test Co")])
        result = conversation._propose_change(
            "create", "res.partner", "", '{"name": "Claude Test Co"}', "Add a contact"
        )
        self.assertTrue(result["awaiting_confirmation"])
        self.assertEqual(
            self.env["res.partner"].search_count([("name", "=", "Claude Test Co")]), before
        )
        operation = self.env["centric.claude.operation"].browse(result["operation_id"])
        self.assertEqual(operation.state, "proposed")
        self.assertIn("Claude Test Co", operation.preview)

    def test_confirming_performs_it_and_declining_does_not(self):
        conversation = self._conversation()
        yes = conversation._propose_change(
            "create", "res.partner", "", '{"name": "Claude Yes Co"}', "Add"
        )
        no = conversation._propose_change(
            "create", "res.partner", "", '{"name": "Claude No Co"}', "Add"
        )
        self.Conversation.apply_workspace_operation(conversation.id, yes["operation_id"])
        self.Conversation.reject_workspace_operation(conversation.id, no["operation_id"])
        self.assertTrue(self.env["res.partner"].search([("name", "=", "Claude Yes Co")]))
        self.assertFalse(self.env["res.partner"].search([("name", "=", "Claude No Co")]))

    def test_a_confirmation_cannot_be_answered_twice(self):
        conversation = self._conversation()
        result = conversation._propose_change(
            "create", "res.partner", "", '{"name": "Claude Once Co"}', "Add"
        )
        self.Conversation.apply_workspace_operation(conversation.id, result["operation_id"])
        with self.assertRaises(UserError):
            self.Conversation.apply_workspace_operation(
                conversation.id, result["operation_id"]
            )
        self.assertEqual(
            self.env["res.partner"].search_count([("name", "=", "Claude Once Co")]), 1
        )

    def test_a_credential_field_can_never_be_set(self):
        conversation = self._conversation()
        with self.assertRaises(AccessError):
            conversation._propose_change(
                "create", "res.users", "", '{"password": "hunted"}', "nope"
            )

    def test_data_tools_are_offered_by_level(self):
        conversation = self._conversation()
        readonly = self._as_level("user")["centric.claude.conversation"]
        names = {
            tool["name"]
            for tool in readonly._data_tool_definitions(readonly._workspace_access())
        }
        self.assertIn("search_odoo_records", names)
        self.assertNotIn("propose_odoo_change", names)

        writer = self._as_level("intermediate")["centric.claude.conversation"]
        names = {
            tool["name"]
            for tool in writer._data_tool_definitions(writer._workspace_access())
        }
        self.assertIn("propose_odoo_change", names)

    def test_data_tool_schemas_satisfy_strict_tool_use(self):
        conversation = self._conversation()
        access = self.Conversation._workspace_access()
        for tool in conversation._data_tool_definitions(access):
            schema = tool["input_schema"]
            self.assertIs(schema["additionalProperties"], False, tool["name"])
            self.assertEqual(sorted(schema["required"]), sorted(schema["properties"]),
                             tool["name"])

    def test_no_tool_is_declared_twice(self):
        """The Messages API rejects a tool list with duplicate names."""
        conversation = self._conversation(developer_mode=True)
        access = self.Conversation._workspace_access()
        names = [tool["name"] for tool in conversation._tool_definitions(access)]
        self.assertEqual(len(names), len(set(names)))

    def test_turning_the_global_switch_off_closes_the_gate(self):
        self._configure(**{"centric_claude.data_enabled": "False"})
        access = self._data()._data_access()
        self.assertEqual(access["level"], "none")
        with self.assertRaises(AccessError):
            self._data().search_records("res.partner")
