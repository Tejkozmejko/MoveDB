/** @odoo-module **/

import {
    Component, markup, onWillStart, onWillUnmount, useEffect, useRef, useState,
} from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

import { highlight, highlightDiff, languageOf } from "./claude_highlight";
import { renderMarkdown } from "./claude_markdown";


/** Starter content for a newly created file, keyed by extension. */
function scaffoldFor(module, path) {
    const name = path.split("/").pop();
    const ext = name.includes(".") ? name.split(".").pop().toLowerCase() : "";
    if (name === "__init__.py") {
        return "from . import models\n";
    }
    if (ext === "py") {
        return "from odoo import _, api, fields, models\n";
    }
    if (ext === "xml") {
        return '<?xml version="1.0" encoding="utf-8"?>\n<odoo>\n\n</odoo>\n';
    }
    if (ext === "csv") {
        return "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n";
    }
    if (ext === "js") {
        return "/** @odoo-module **/\n";
    }
    if (ext === "md") {
        return `# ${module}\n`;
    }
    return "";
}

/** The two files Odoo needs before it will even see a directory as a module. */
function moduleScaffold(name) {
    const title = name
        .split("_")
        .filter(Boolean)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ");
    const manifest =
        "{\n" +
        `    "name": "${title}",\n` +
        '    "version": "19.0.1.0.0",\n' +
        '    "summary": "",\n' +
        '    "author": "Centric",\n' +
        '    "license": "LGPL-3",\n' +
        '    "category": "Customisations",\n' +
        '    "depends": ["base"],\n' +
        '    "data": [],\n' +
        "    \"installable\": True,\n" +
        "}\n";
    return [
        { path: "__manifest__.py", content: manifest },
        { path: "__init__.py", content: "# from . import models\n" },
    ];
}


export class ClaudeDeveloperWorkspace extends Component {
    static template = "centric_claude_integration.ClaudeDeveloperWorkspace";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            loading: true,
            busy: false,
            access: {},
            conversations: [],
            activeConversationId: null,
            // Projects: folders of chats that share standing instructions.
            projects: [],
            activeProjectId: null,
            projectName: "",
            projectInstructions: "",
            // { id, value } while a chat name is being edited in the list.
            renaming: null,
            conversation: null,
            messages: [],
            changes: [],
            operations: [],
            messageDraft: "",
            // Which activity-bar panel is showing: chat, projects,
            // explorer or scm.
            view: "chat",
            modules: [],
            modulesLoaded: false,
            modulesLoading: false,
            tree: [],
            activeModule: null,
            openFiles: [],
            activeFileKey: null,
            // The editor is single-buffer: `editorDraft` is the live text of the
            // file named by `editingKey`. t-model needs a plain state path, and
            // per-tab drafts would only give it a getter-backed one.
            editorDraft: "",
            editingKey: null,
            // { kind: "file" | "module", value: "", module: "..." } while naming.
            creating: null,
            agent: {},
        });
        this.pollTimer = null;
        this.codePane = useRef("codePane");
        this.gutter = useRef("gutter");
        this.newNameInput = useRef("newNameInput");
        this.renameInput = useRef("renameInput");
        this.composerInput = useRef("composerInput");
        this.chatScroll = useRef("chatScroll");
        // Rendering Markdown on every re-render would re-parse the whole
        // transcript each time the spinner ticks. Message text never changes
        // once stored, so cache on the id and check the source anyway.
        this.renderedMessages = new Map();

        onWillUnmount(() => this.stopPolling());

        // A checkbox keeps its own DOM `checked` property once a user clicks it,
        // so the rendered attribute alone can leave the switch showing a stale
        // position after switching conversations. Push state onto the property.
        this.developerModeToggle = useRef("developerModeToggle");
        useEffect(
            (el, enabled) => {
                if (el) {
                    el.checked = enabled;
                }
            },
            () => [
                this.developerModeToggle.el,
                Boolean(this.state.conversation && this.state.conversation.developer_mode),
            ]
        );

        // A <select> keeps its own value property once touched, and a rendered
        // `selected` attribute does not override it. Same trap as the checkbox
        // above: push the state onto the property.
        this.effortSelect = useRef("effortSelect");
        useEffect(
            (el, effort) => {
                if (el && effort) {
                    el.value = effort;
                }
            },
            () => [
                this.effortSelect.el,
                this.state.conversation && this.state.conversation.effort,
            ]
        );

        // Focus the inline name box the moment it appears, as an editor would.
        useEffect(
            (el) => {
                if (el) {
                    el.focus();
                }
            },
            () => [this.newNameInput.el]
        );

        // Same trap as the checkbox: a <select> keeps whatever the user last
        // picked, so the current project has to be pushed onto the property.
        this.projectSelect = useRef("projectSelect");
        useEffect(
            (el, projectId) => {
                if (el) {
                    el.value = projectId ? String(projectId) : "";
                }
            },
            () => [
                this.projectSelect.el,
                this.state.conversation && this.state.conversation.project_id,
            ]
        );

        // Focus the chat-rename box the moment it appears.
        useEffect(
            (el) => {
                if (el) {
                    el.focus();
                    el.select();
                }
            },
            () => [this.renameInput.el]
        );

        // The composer grows with the draft, up to a point, then scrolls - the
        // way every chat box behaves. A fixed three rows wasted space on short
        // questions and hid the end of long ones.
        useEffect(
            (el) => {
                if (el) {
                    el.style.height = "auto";
                    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
                }
            },
            () => [this.composerInput.el, this.state.messageDraft]
        );

        // Follow the conversation as it grows, so a new answer is not left
        // below the fold.
        useEffect(
            (el) => {
                if (el) {
                    el.scrollTop = el.scrollHeight;
                }
            },
            () => [
                this.chatScroll.el,
                this.state.messages.length,
                this.state.busy,
                this.state.operations.length,
            ]
        );

        onWillStart(() => this.loadBootstrap());
    }

    // ------------------------------------------------------------- plumbing
    async call(method, args = []) {
        return this.orm.call("centric.claude.conversation", method, args, {});
    }

    async callProject(method, args = []) {
        return this.orm.call("centric.claude.project", method, args, {});
    }

    /** Refresh the sidebar from any payload that carries a list of either. */
    applySidebar(payload) {
        if (!payload) {
            return;
        }
        if (payload.projects) {
            this.state.projects = payload.projects;
        }
        if (payload.conversations) {
            this.state.conversations = payload.conversations;
        }
    }

    /** Ask before anything irreversible. Resolves false if the box is dismissed. */
    confirm(title, body, confirmLabel) {
        return new Promise((resolve) => {
            this.dialog.add(
                ConfirmationDialog,
                {
                    title,
                    body,
                    confirmLabel,
                    confirmClass: "btn-danger",
                    confirm: () => resolve(true),
                    cancel: () => resolve(false),
                },
                // Closing the dialog any other way still has to settle the
                // promise, or the caller waits forever.
                { onClose: () => resolve(false) }
            );
        });
    }

    errorMessage(error) {
        return error?.data?.message || error?.message || String(error);
    }

    notifyError(error) {
        this.notification.add(this.errorMessage(error), { type: "danger", sticky: true });
    }

    async loadBootstrap() {
        try {
            const data = await this.call("workspace_bootstrap");
            this.state.access = data.access || {};
            this.applySidebar(data);
            if (this.state.conversations.length) {
                await this.selectConversation(this.state.conversations[0].id);
            }
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.loading = false;
        }
    }

    applyConversationPayload(payload) {
        this.applySidebar(payload);
        this.state.agent = payload.agent || {};
        this.state.busy = Boolean(this.state.agent.waiting);
        this.state.conversation = payload.conversation;
        this.state.activeConversationId = payload.conversation.id;
        this.state.messages = payload.messages || [];
        this.state.changes = payload.changes || [];
        this.state.operations = payload.operations || [];
        this.state.access = payload.access || this.state.access;
        const index = this.state.conversations.findIndex(
            (item) => item.id === payload.conversation.id
        );
        if (index >= 0) {
            this.state.conversations[index] = payload.conversation;
        } else {
            this.state.conversations.unshift(payload.conversation);
        }
        // A queued turn is answered by the local bridge, not by this request.
        if (this.state.agent.waiting) {
            this.startPolling();
        } else {
            this.stopPolling();
        }
    }

    /** Changes Claude has proposed that are still waiting on an answer. */
    get pendingOperations() {
        return this.state.operations.filter((op) => op.state === "proposed");
    }

    get answeredOperations() {
        return this.state.operations.filter((op) => op.state !== "proposed");
    }

    operationIcon(operation) {
        return {
            create: "fa-plus-circle",
            write: "fa-pencil-square-o",
            unlink: "fa-trash-o",
            method: "fa-play-circle-o",
        }[operation.kind] || "fa-question-circle-o";
    }

    async answerOperation(operationId, accept) {
        if (!this.state.conversation || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const payload = await this.call(
                accept ? "apply_workspace_operation" : "reject_workspace_operation",
                [this.state.conversation.id, operationId]
            );
            this.applyConversationPayload(payload);
            this.notification.add(
                accept ? "Done." : "Not applied.",
                { type: accept ? "success" : "info" }
            );
        } catch (error) {
            this.notifyError(error);
        } finally {
            // applyConversationPayload owns busy when a turn is queued; only
            // clear it here if nothing took over.
            if (!this.state.agent.waiting) {
                this.state.busy = false;
            }
        }
    }

    get lastMessageId() {
        const messages = this.state.messages;
        return messages.length ? messages[messages.length - 1].id : 0;
    }

    startPolling() {
        if (this.pollTimer) {
            return;
        }
        this.pollTimer = setInterval(() => this.pollOnce(), 2000);
    }

    stopPolling() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    }

    async pollOnce() {
        if (!this.state.conversation) {
            this.stopPolling();
            return;
        }
        try {
            const payload = await this.call("poll_workspace_conversation", [
                this.state.conversation.id,
                this.lastMessageId,
            ]);
            if (payload.unchanged) {
                this.state.agent = payload.agent || {};
                if (!this.state.agent.waiting) {
                    // The turn finished or was cancelled without a new message.
                    this.state.busy = false;
                    this.stopPolling();
                }
                return;
            }
            this.applyConversationPayload(payload);
        } catch (error) {
            this.stopPolling();
            this.state.busy = false;
            this.notifyError(error);
        }
    }

    async cancelTurn() {
        if (!this.state.conversation) {
            return;
        }
        this.stopPolling();
        try {
            const payload = await this.call("cancel_workspace_turn", [
                this.state.conversation.id,
            ]);
            this.applyConversationPayload(payload);
        } catch (error) {
            this.notifyError(error);
        }
    }

    get agentStatusText() {
        const agent = this.state.agent || {};
        if (agent.backend !== "agent" || !agent.waiting) {
            return "";
        }
        if (agent.state === "running") {
            return `Running on ${agent.connected_agent || agent.agent_name || "your machine"}...`;
        }
        if (!agent.online) {
            // Distinguish "thinking" from "nothing is listening", which
            // otherwise look identical and wait forever.
            return "No local agent is connected.";
        }
        const ahead = agent.queue_position || 0;
        if (ahead > 0) {
            // Questions are answered one at a time, so a queue is the whole
            // explanation for a wait that would otherwise look like a hang.
            return ahead === 1
                ? "1 question ahead of yours..."
                : `${ahead} questions ahead of yours...`;
        }
        return `Queued for ${agent.connected_agent || "your machine"}...`;
    }

    /** True when a turn is queued but no bridge has polled recently. */
    get agentOffline() {
        const agent = this.state.agent || {};
        return agent.backend === "agent" && Boolean(agent.waiting) && !agent.online;
    }

    // -------------------------------------------------------- conversations
    async newConversation(projectId = null) {
        try {
            const payload = await this.call("create_workspace_conversation", [
                null,
                projectId || false,
            ]);
            this.applyConversationPayload(payload);
            this.resetCodeBrowser();
            this.state.view = "chat";
        } catch (error) {
            this.notifyError(error);
        }
    }

    /** Move the open chat into a project, or out of every project. */
    async onProjectPicked(ev) {
        if (!this.state.conversation || this.state.busy) {
            return;
        }
        const previous = this.state.conversation.project_id;
        const chosen = ev.target.value ? Number(ev.target.value) : false;
        try {
            const payload = await this.call("set_workspace_conversation_project", [
                this.state.conversation.id,
                chosen,
            ]);
            this.applyConversationPayload(payload);
        } catch (error) {
            ev.target.value = previous ? String(previous) : "";
            this.notifyError(error);
        }
    }

    startRename(conv) {
        this.state.renaming = { id: conv.id, value: conv.name };
    }

    onRenameKeydown(ev) {
        if (ev.key === "Escape") {
            ev.preventDefault();
            this.state.renaming = null;
        } else if (ev.key === "Enter") {
            // Blurring is what commits, so Enter and clicking away agree.
            ev.preventDefault();
            ev.target.blur();
        }
    }

    async commitRename() {
        const renaming = this.state.renaming;
        if (!renaming) {
            return;
        }
        this.state.renaming = null;
        const name = (renaming.value || "").trim();
        const conv = this.state.conversations.find((item) => item.id === renaming.id);
        if (!name || !conv || name === conv.name) {
            return;
        }
        try {
            this.applySidebar(
                await this.call("rename_workspace_conversation", [renaming.id, name])
            );
            if (this.state.conversation && this.state.conversation.id === renaming.id) {
                this.state.conversation.name = name;
            }
        } catch (error) {
            this.notifyError(error);
        }
    }

    async deleteConversation(conv) {
        const confirmed = await this.confirm(
            "Delete chat",
            `"${conv.name}" and everything in it will be deleted. This cannot be undone.`,
            "Delete"
        );
        if (!confirmed) {
            return;
        }
        try {
            const data = await this.call("delete_workspace_conversation", [conv.id]);
            this.applySidebar(data);
            if (this.state.activeConversationId === conv.id) {
                // The open chat just went away: clear the pane rather than
                // leaving it showing a transcript that no longer exists.
                this.stopPolling();
                this.state.busy = false;
                this.state.conversation = null;
                this.state.activeConversationId = null;
                this.state.messages = [];
                this.state.changes = [];
                this.state.operations = [];
                this.renderedMessages.clear();
                this.resetCodeBrowser();
                if (this.state.conversations.length) {
                    await this.selectConversation(this.state.conversations[0].id);
                }
            }
        } catch (error) {
            this.notifyError(error);
        }
    }

    // ------------------------------------------------------------- projects
    get activeProject() {
        return (
            this.state.projects.find((item) => item.id === this.state.activeProjectId) ||
            null
        );
    }

    get projectConversations() {
        const projectId = this.state.activeProjectId;
        if (!projectId) {
            return [];
        }
        return this.state.conversations.filter((conv) => conv.project_id === projectId);
    }

    get projectInstructionsDirty() {
        const project = this.activeProject;
        return (
            Boolean(project) &&
            this.state.projectInstructions !== (project.instructions || "")
        );
    }

    /** The project chip shown on a chat row, empty when the chat is unfiled. */
    projectNameOf(conv) {
        if (!conv.project_id) {
            return "";
        }
        const project = this.state.projects.find((item) => item.id === conv.project_id);
        return project ? project.name : "";
    }

    selectProject(projectId) {
        this.state.activeProjectId = projectId;
        const project = this.activeProject;
        this.state.projectName = project ? project.name : "";
        this.state.projectInstructions = project ? project.instructions || "" : "";
    }

    async newProject() {
        try {
            const data = await this.callProject("create_workspace_project", []);
            this.applySidebar(data);
            this.state.view = "projects";
            this.selectProject(data.project_id);
        } catch (error) {
            this.notifyError(error);
        }
    }

    onProjectNameKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            ev.target.blur();
        } else if (ev.key === "Escape") {
            ev.preventDefault();
            this.state.projectName = this.activeProject ? this.activeProject.name : "";
        }
    }

    async saveProjectName() {
        const project = this.activeProject;
        if (!project) {
            return;
        }
        const name = (this.state.projectName || "").trim();
        if (!name || name === project.name) {
            this.state.projectName = project.name;
            return;
        }
        try {
            this.applySidebar(
                await this.callProject("rename_workspace_project", [project.id, name])
            );
        } catch (error) {
            this.state.projectName = project.name;
            this.notifyError(error);
        }
    }

    async saveProjectInstructions() {
        const project = this.activeProject;
        if (!project) {
            return;
        }
        try {
            this.applySidebar(
                await this.callProject("set_workspace_project_instructions", [
                    project.id,
                    this.state.projectInstructions,
                ])
            );
            this.notification.add("Project instructions saved.", { type: "success" });
        } catch (error) {
            this.notifyError(error);
        }
    }

    async deleteProject() {
        const project = this.activeProject;
        if (!project) {
            return;
        }
        const confirmed = await this.confirm(
            "Delete project",
            `"${project.name}" will be deleted. Its chats are kept, but they will ` +
                "no longer start from these instructions.",
            "Delete"
        );
        if (!confirmed) {
            return;
        }
        try {
            const data = await this.callProject("delete_workspace_project", [project.id]);
            this.applySidebar(data);
            this.selectProject(null);
            if (this.state.conversation) {
                // The open chat may have been filed here; re-read it so the
                // picker in the title bar stops naming a project that is gone.
                await this.selectConversation(this.state.conversation.id);
            }
        } catch (error) {
            this.notifyError(error);
        }
    }

    async openConversationFromProject(conversationId) {
        this.state.view = "chat";
        await this.selectConversation(conversationId);
    }

    async selectConversation(id) {
        if (this.state.busy) {
            return;
        }
        this.stopPolling();
        try {
            const payload = await this.call("get_workspace_conversation", [id]);
            // Rendered Markdown is keyed on message id, so leaving the previous
            // transcript's entries behind would only grow the map.
            this.renderedMessages.clear();
            this.applyConversationPayload(payload);
            this.resetCodeBrowser();
        } catch (error) {
            this.notifyError(error);
        }
    }

    get effortChoices() {
        return this.state.access.effort_choices || [];
    }

    async setEffort(ev) {
        if (!this.state.conversation || this.state.busy) {
            return;
        }
        const previous = this.state.conversation.effort;
        const chosen = ev.target.value;
        try {
            const payload = await this.call("set_workspace_effort", [
                this.state.conversation.id,
                chosen,
            ]);
            this.applyConversationPayload(payload);
        } catch (error) {
            ev.target.value = previous;
            this.notifyError(error);
        }
    }

    async toggleDeveloperMode(ev) {
        if (!this.state.conversation || this.state.busy) {
            return;
        }
        const enabled = Boolean(ev.target.checked);
        try {
            const payload = await this.call("set_workspace_developer_mode", [
                this.state.conversation.id,
                enabled,
            ]);
            this.applyConversationPayload(payload);
        } catch (error) {
            ev.target.checked = !enabled;
            this.notifyError(error);
        }
    }

    setView(view) {
        if (view === "explorer" && !this.state.access.can_read_code) {
            return;
        }
        this.state.view = view;
        if (view === "explorer" && !this.state.modulesLoaded && this.state.conversation) {
            this.loadModules();
        }
    }

    async sendMessage(ev) {
        ev.preventDefault();
        const text = this.state.messageDraft.trim();
        if (!text || this.state.busy) {
            return;
        }
        if (!this.state.conversation) {
            await this.newConversation();
            if (!this.state.conversation) {
                return;
            }
        }
        this.state.busy = true;
        this.state.messageDraft = "";
        try {
            const payload = await this.call("send_workspace_message", [
                this.state.conversation.id,
                text,
            ]);
            this.applyConversationPayload(payload);
        } catch (error) {
            this.state.messageDraft = text;
            this.state.busy = false;
            this.notifyError(error);
        }
        // With the agent backend the turn is still queued here, so `busy` stays
        // on until polling sees the reply. applyConversationPayload owns it.
    }

    get userInitials() {
        const name = (this.state.access.user_name || "").trim();
        if (!name) {
            return "?";
        }
        return name
            .split(/\s+/)
            .slice(0, 2)
            .map((part) => part.charAt(0).toUpperCase())
            .join("");
    }

    /**
     * A message body, ready for `t-out`.
     *
     * Claude answers in Markdown, so an assistant message is rendered; a user
     * message is returned as a plain string, which `t-out` escapes, because
     * there is nothing to gain from formatting what the user typed and plenty
     * to lose from parsing it.
     */
    messageHtml(message) {
        if (message.role === "user") {
            return message.content;
        }
        const cached = this.renderedMessages.get(message.id);
        if (cached && cached.source === message.content) {
            return cached.html;
        }
        const html = markup(renderMarkdown(message.content));
        this.renderedMessages.set(message.id, { source: message.content, html });
        return html;
    }

    get suggestions() {
        const module = this.state.activeModule || this.state.modules[0]?.name;
        const items = [
            "What modules are on this branch, and what does each one do?",
        ];
        if (module) {
            items.push(`Explain how ${module} works.`);
            items.push(`Review ${module} for bugs and tell me what you would change.`);
        } else {
            items.push("Explain how the modules on this branch fit together.");
        }
        if (this.canEdit) {
            items.push("Add a README to one of these modules describing what it does.");
        }
        return items;
    }

    useSuggestion(text) {
        this.state.messageDraft = text;
    }

    onComposerKeydown(ev) {
        // Enter sends, Shift+Enter breaks the line - the convention every chat
        // box uses, and the one people try first.
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage(ev);
        }
    }

    // ------------------------------------------------------------- explorer
    resetCodeBrowser() {
        this.state.modules = [];
        this.state.modulesLoaded = false;
        this.state.tree = [];
        this.state.activeModule = null;
        this.state.openFiles = [];
        this.state.activeFileKey = null;
        this.state.editorDraft = "";
        this.state.editingKey = null;
        this.state.creating = null;
    }

    async loadModules() {
        if (!this.state.conversation || !this.state.access.can_read_code) {
            return;
        }
        this.state.modulesLoading = true;
        try {
            const modules = await this.call("get_repository_modules", [
                this.state.conversation.id,
            ]);
            this.state.modules = modules;
            this.state.tree = modules.map((module) => ({
                type: "module",
                name: module.name,
                expanded: false,
                loaded: false,
                children: [],
            }));
            this.state.modulesLoaded = true;
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.modulesLoading = false;
        }
    }

    /** Turn a flat list of module-relative paths into nested folder nodes. */
    buildFileTree(files) {
        const root = { dirs: new Map(), files: [] };
        for (const file of files) {
            const parts = file.path.split("/");
            let node = root;
            for (const part of parts.slice(0, -1)) {
                if (!node.dirs.has(part)) {
                    node.dirs.set(part, { dirs: new Map(), files: [] });
                }
                node = node.dirs.get(part);
            }
            node.files.push({ type: "file", name: parts[parts.length - 1], path: file.path });
        }
        const toNodes = (node, prefix) => {
            const dirs = [...node.dirs.entries()]
                .sort((a, b) => a[0].localeCompare(b[0]))
                .map(([name, child]) => ({
                    type: "dir",
                    name,
                    path: prefix ? `${prefix}/${name}` : name,
                    // Folders open by default: an Odoo module is shallow, and a
                    // tree that starts fully collapsed hides everything at once.
                    expanded: true,
                    children: toNodes(child, prefix ? `${prefix}/${name}` : name),
                }));
            const files = node.files.sort((a, b) => a.name.localeCompare(b.name));
            return [...dirs, ...files];
        };
        return toNodes(root, "");
    }

    async toggleModule(node) {
        this.state.activeModule = node.name;
        node.expanded = !node.expanded;
        if (node.expanded && !node.loaded) {
            try {
                const files = await this.call("get_repository_module_files", [
                    this.state.conversation.id,
                    node.name,
                ]);
                node.children = this.buildFileTree(files);
                node.loaded = true;
            } catch (error) {
                node.expanded = false;
                this.notifyError(error);
            }
        }
    }

    toggleDir(node) {
        node.expanded = !node.expanded;
    }

    /** Flatten the tree into the rows actually visible right now. */
    get treeRows() {
        const rows = [];
        const walk = (nodes, moduleName, depth) => {
            for (const node of nodes) {
                rows.push({
                    key: `${moduleName}:${node.type}:${node.path || node.name}`,
                    node,
                    module: moduleName,
                    depth,
                });
                if (node.type === "dir" && node.expanded) {
                    walk(node.children, moduleName, depth + 1);
                }
            }
        };
        for (const module of this.state.tree) {
            rows.push({
                key: `module:${module.name}`,
                node: module,
                module: module.name,
                depth: 0,
            });
            if (module.expanded) {
                walk(module.children, module.name, 1);
            }
        }
        return rows;
    }

    indentOf(depth) {
        return `padding-left: ${8 + depth * 12}px`;
    }

    iconFor(node) {
        if (node.type === "module") {
            return "fa-cube";
        }
        if (node.type === "dir") {
            return node.expanded ? "fa-folder-open-o" : "fa-folder-o";
        }
        const language = languageOf(node.name);
        return {
            python: "fa-file-code-o",
            xml: "fa-file-code-o",
            javascript: "fa-file-code-o",
            css: "fa-file-code-o",
            json: "fa-file-text-o",
            csv: "fa-table",
        }[language] || "fa-file-o";
    }

    // ---------------------------------------------------------- editor tabs
    fileKey(module, path) {
        return `${module}/${path}`;
    }

    get activeFile() {
        return this.state.openFiles.find((f) => f.key === this.state.activeFileKey) || null;
    }

    async openFile(moduleName, path) {
        const key = this.fileKey(moduleName, path);
        const existing = this.state.openFiles.find((f) => f.key === key);
        if (existing) {
            this.state.activeFileKey = key;
            return;
        }
        try {
            const data = await this.call("get_repository_file", [
                this.state.conversation.id,
                moduleName,
                path,
            ]);
            // Show the staged version when one exists, so an edit builds on the
            // change already under review rather than silently reverting it.
            const content = data.staged_content || data.content || "";
            this.state.openFiles.push({
                key,
                module: moduleName,
                path,
                saved: content,
                remote: data.content || "",
            });
            this.state.activeFileKey = key;
            this.state.activeModule = moduleName;
        } catch (error) {
            this.notifyError(error);
        }
    }

    selectTab(key) {
        if (this.state.editingKey && this.state.editingKey !== key) {
            this.cancelEditing();
        }
        this.state.activeFileKey = key;
        const file = this.state.openFiles.find((f) => f.key === key);
        if (file) {
            this.state.activeModule = file.module;
        }
    }

    closeTab(key, ev) {
        if (ev) {
            ev.stopPropagation();
        }
        const index = this.state.openFiles.findIndex((f) => f.key === key);
        if (index < 0) {
            return;
        }
        this.state.openFiles.splice(index, 1);
        if (this.state.editingKey === key) {
            this.state.editingKey = null;
            this.state.editorDraft = "";
        }
        if (this.state.activeFileKey === key) {
            const next = this.state.openFiles[index] || this.state.openFiles[index - 1];
            this.state.activeFileKey = next ? next.key : null;
        }
    }

    isDirty(file) {
        return Boolean(file) && this.state.editingKey === file.key &&
            this.state.editorDraft !== file.saved;
    }

    get isEditing() {
        const file = this.activeFile;
        return Boolean(file) && this.state.editingKey === file.key;
    }

    /** The text on screen right now, edited or not. */
    get editorText() {
        const file = this.activeFile;
        if (!file) {
            return "";
        }
        return this.isEditing ? this.state.editorDraft : file.saved;
    }

    get highlightedCode() {
        const file = this.activeFile;
        if (!file) {
            return markup("");
        }
        return markup(highlight(file.saved, file.path));
    }

    get lineCount() {
        return this.editorText.split("\n").length;
    }

    get lineNumbers() {
        return Array.from({ length: this.lineCount }, (_, i) => i + 1)
            .join("\n");
    }

    get activeLanguage() {
        const file = this.activeFile;
        return file ? languageOf(file.path) : "";
    }

    /** Keep the line-number gutter aligned while the code pane scrolls. */
    onCodeScroll(ev) {
        if (this.gutter.el) {
            this.gutter.el.scrollTop = ev.target.scrollTop;
        }
    }

    onEditorKeydown(ev) {
        // Tab must indent, not jump to the next control - this is an editor.
        if (ev.key !== "Tab") {
            return;
        }
        ev.preventDefault();
        const el = ev.target;
        const { selectionStart: start, selectionEnd: end, value } = el;
        const next = `${value.slice(0, start)}    ${value.slice(end)}`;
        this.state.editorDraft = next;
        el.value = next;
        el.selectionStart = el.selectionEnd = start + 4;
    }

    get canEdit() {
        return Boolean(
            this.state.access.can_develop &&
            this.state.conversation &&
            this.state.conversation.developer_mode
        );
    }

    startEditing() {
        const file = this.activeFile;
        if (file && this.canEdit) {
            this.state.editorDraft = file.saved;
            this.state.editingKey = file.key;
        }
    }

    cancelEditing() {
        this.state.editingKey = null;
        this.state.editorDraft = "";
    }

    async stageActiveFile() {
        const file = this.activeFile;
        if (!file || !this.state.conversation) {
            return;
        }
        if (!this.isDirty(file)) {
            this.notification.add("Nothing changed in this file.", { type: "info" });
            return;
        }
        const draft = this.state.editorDraft;
        const ok = await this.stageFile(
            file.module, file.path, draft, `Manual edit to ${file.path}`
        );
        if (ok) {
            file.saved = draft;
            this.state.editingKey = null;
            this.state.editorDraft = "";
        }
    }

    async stageFile(moduleName, path, content, summary) {
        try {
            const payload = await this.call("stage_manual_change", [
                this.state.conversation.id,
                moduleName,
                path,
                content,
                summary,
            ]);
            this.applyConversationPayload(payload);
            this.notification.add(`Staged ${path} for review.`, { type: "success" });
            return true;
        } catch (error) {
            this.notifyError(error);
            return false;
        }
    }

    // ------------------------------------------------------ creating things
    startNewFile() {
        const module = this.state.activeModule || this.activeFile?.module;
        if (!module) {
            this.notification.add("Pick a module first, then add a file to it.", {
                type: "warning",
            });
            return;
        }
        this.state.creating = { kind: "file", value: "", module };
    }

    startNewModule() {
        this.state.creating = { kind: "module", value: "", module: null };
    }

    cancelCreate() {
        this.state.creating = null;
    }

    onCreateKeydown(ev) {
        if (ev.key === "Escape") {
            this.cancelCreate();
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            this.confirmCreate();
        }
    }

    async confirmCreate() {
        const creating = this.state.creating;
        if (!creating) {
            return;
        }
        const name = (creating.value || "").trim().replace(/^\/+/, "");
        if (!name) {
            this.cancelCreate();
            return;
        }
        this.state.creating = null;
        if (creating.kind === "file") {
            await this.createFile(creating.module, name);
        } else {
            await this.createModule(name);
        }
    }

    async createFile(moduleName, path) {
        const key = this.fileKey(moduleName, path);
        if (this.state.openFiles.some((f) => f.key === key)) {
            this.state.activeFileKey = key;
            return;
        }
        // Staging is what creates the file, and a staged change must differ from
        // the empty baseline - so a new file starts from a small scaffold.
        const content = scaffoldFor(moduleName, path) || `# ${path}\n`;
        const ok = await this.stageFile(
            moduleName, path, content, `New file: ${path}`
        );
        if (!ok) {
            return;
        }
        this.state.openFiles.push({
            key, module: moduleName, path, saved: content, remote: "",
        });
        this.state.activeFileKey = key;
        if (this.canEdit) {
            this.state.editorDraft = content;
            this.state.editingKey = key;
        }
        await this.refreshModuleFiles(moduleName);
    }

    async createModule(name) {
        if (!this.state.conversation) {
            return;
        }
        try {
            const payload = await this.call("create_workspace_module", [
                this.state.conversation.id,
                name,
                moduleScaffold(name),
            ]);
            this.applyConversationPayload(payload);
            await this.loadModules();
            const node = this.state.tree.find((m) => m.name === name);
            if (node) {
                await this.toggleModule(node);
            }
            this.state.activeModule = name;
            await this.openFile(name, "__manifest__.py");
            this.notification.add(
                `Module ${name} staged. Review it under Source Control, then Commit.`,
                { type: "success" }
            );
        } catch (error) {
            this.notifyError(error);
        }
    }

    /** Re-read one module's file list so a newly staged file appears in the tree. */
    async refreshModuleFiles(moduleName) {
        const node = this.state.tree.find((m) => m.name === moduleName);
        if (!node || !node.loaded) {
            return;
        }
        try {
            const files = await this.call("get_repository_module_files", [
                this.state.conversation.id,
                moduleName,
            ]);
            node.children = this.buildFileTree(files);
        } catch (error) {
            this.notifyError(error);
        }
    }

    // -------------------------------------------------------------- changes
    diffMarkup(change) {
        return markup(highlightDiff(change.diff_text || ""));
    }

    async discardChange(changeId) {
        try {
            const payload = await this.call("discard_workspace_change", [
                this.state.conversation.id,
                changeId,
            ]);
            this.applyConversationPayload(payload);
        } catch (error) {
            this.notifyError(error);
        }
    }

    async commitChanges() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const payload = await this.call("commit_workspace_changes", [
                this.state.conversation.id,
            ]);
            this.applyConversationPayload(payload);
            this.resetCodeBrowser();
            this.notification.add(`Committed to ${payload.conversation.review_branch}.`, {
                type: "success",
            });
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.busy = false;
        }
    }

    async createPullRequest() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const payload = await this.call("create_workspace_pull_request", [
                this.state.conversation.id,
            ]);
            this.applyConversationPayload(payload);
            this.notification.add("Pull request created.", { type: "success" });
        } catch (error) {
            this.notifyError(error);
        } finally {
            this.state.busy = false;
        }
    }

    openPullRequest() {
        if (this.state.conversation?.pull_request_url) {
            window.open(this.state.conversation.pull_request_url, "_blank", "noopener,noreferrer");
        }
    }

    get activeBranch() {
        const conv = this.state.conversation;
        return conv ? conv.review_branch || conv.base_branch : "";
    }

    get stagedChanges() {
        return this.state.changes.filter((change) => change.status === "staged");
    }
}

registry.category("actions").add(
    "centric_claude_integration.developer_workspace",
    ClaudeDeveloperWorkspace
);
