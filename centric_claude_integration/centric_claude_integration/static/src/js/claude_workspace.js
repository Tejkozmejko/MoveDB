/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// Header lines of a unified diff, checked before the +/- prefixes so that the
// "---" and "+++" file headers are not mistaken for removed and added lines.
const DIFF_META_RE = /^(diff |index |--- |\+\+\+ |new file |deleted file |similarity |rename |old mode |new mode |Binary files )/;


export class ClaudeDeveloperWorkspace extends Component {
    static template = "centric_claude_integration.ClaudeDeveloperWorkspace";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            busy: false,
            access: {},
            conversations: [],
            activeConversationId: null,
            conversation: null,
            messages: [],
            changes: [],
            messageDraft: "",
            tab: "chat",
            modules: [],
            modulesLoaded: false,
            files: [],
            selectedModule: null,
            selectedFile: null,
            fileContent: "",
            remoteContent: "",
            editorContent: "",
            fileEditing: false,
            agent: {},
        });
        this.pollTimer = null;
        onWillUnmount(() => this.stopPolling());
        // A checkbox keeps its own DOM `checked` property once a user clicks it, so
        // the rendered attribute alone can leave the switch showing a stale position
        // after switching conversations. Push the state onto the property directly.
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
        onWillStart(() => this.loadBootstrap());
    }

    async call(method, args = []) {
        return this.orm.call("centric.claude.conversation", method, args, {});
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
            this.state.conversations = data.conversations || [];
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
        this.state.agent = payload.agent || {};
        this.state.busy = Boolean(this.state.agent.waiting);
        this.state.conversation = payload.conversation;
        this.state.activeConversationId = payload.conversation.id;
        this.state.messages = payload.messages || [];
        this.state.changes = payload.changes || [];
        this.state.access = payload.access || this.state.access;
        const index = this.state.conversations.findIndex((item) => item.id === payload.conversation.id);
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
            return `Running on ${agent.agent_name || "your machine"}...`;
        }
        return "Waiting for the local Claude agent to pick this up...";
    }

    async newConversation() {
        try {
            const payload = await this.call("create_workspace_conversation", []);
            this.applyConversationPayload(payload);
            this.resetCodeBrowser();
            this.state.tab = "chat";
        } catch (error) {
            this.notifyError(error);
        }
    }

    async selectConversation(id) {
        if (this.state.busy) {
            return;
        }
        this.stopPolling();
        try {
            const payload = await this.call("get_workspace_conversation", [id]);
            this.applyConversationPayload(payload);
            this.resetCodeBrowser();
        } catch (error) {
            this.notifyError(error);
        }
    }

    async toggleDeveloperMode(ev) {
        if (!this.state.conversation || this.state.busy) {
            return;
        }
        const enabled = Boolean(ev.target.checked);
        try {
            const payload = await this.call("set_workspace_developer_mode", [this.state.conversation.id, enabled]);
            this.applyConversationPayload(payload);
        } catch (error) {
            ev.target.checked = !enabled;
            this.notifyError(error);
        }
    }

    setTab(tab) {
        this.state.tab = tab;
        if (tab === "code" && !this.state.modules.length && this.state.conversation) {
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
            const payload = await this.call("send_workspace_message", [this.state.conversation.id, text]);
            this.applyConversationPayload(payload);
        } catch (error) {
            this.state.messageDraft = text;
            this.state.busy = false;
            this.notifyError(error);
        }
        // With the agent backend the turn is still queued here, so `busy` stays on
        // until polling sees the reply. applyConversationPayload owns it.
    }

    resetCodeBrowser() {
        this.state.modules = [];
        this.state.modulesLoaded = false;
        this.state.files = [];
        this.state.selectedModule = null;
        this.state.selectedFile = null;
        this.state.fileContent = "";
        this.state.remoteContent = "";
        this.state.editorContent = "";
        this.state.fileEditing = false;
    }

    async loadModules() {
        if (!this.state.conversation || !this.state.access.can_read_code) {
            return;
        }
        try {
            this.state.modules = await this.call("get_repository_modules", [this.state.conversation.id]);
            this.state.modulesLoaded = true;
        } catch (error) {
            this.notifyError(error);
        }
    }

    async selectModule(module) {
        this.state.selectedModule = module.name;
        this.state.selectedFile = null;
        this.state.fileContent = "";
        this.state.remoteContent = "";
        this.state.editorContent = "";
        this.state.fileEditing = false;
        try {
            this.state.files = await this.call("get_repository_module_files", [
                this.state.conversation.id,
                module.name,
            ]);
        } catch (error) {
            this.notifyError(error);
        }
    }

    async selectFile(file) {
        try {
            const data = await this.call("get_repository_file", [
                this.state.conversation.id,
                this.state.selectedModule,
                file.path,
            ]);
            this.state.selectedFile = file.path;
            // Show the staged version when one exists, and make Cancel return to it.
            this.state.fileContent = data.staged_content || data.content || "";
            this.state.remoteContent = data.content || "";
            this.state.editorContent = this.state.fileContent;
            this.state.fileEditing = false;
        } catch (error) {
            this.notifyError(error);
        }
    }

    startEditing() {
        this.state.fileEditing = true;
    }

    cancelEditing() {
        this.state.editorContent = this.state.fileContent;
        this.state.fileEditing = false;
    }

    async stageManualChange() {
        if (!this.state.selectedModule || !this.state.selectedFile || !this.state.conversation) {
            return;
        }
        try {
            const payload = await this.call("stage_manual_change", [
                this.state.conversation.id,
                this.state.selectedModule,
                this.state.selectedFile,
                this.state.editorContent,
                `Manual edit to ${this.state.selectedFile}`,
            ]);
            this.applyConversationPayload(payload);
            this.state.fileEditing = false;
            this.notification.add("Change staged for review.", { type: "success" });
        } catch (error) {
            this.notifyError(error);
        }
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
            const payload = await this.call("commit_workspace_changes", [this.state.conversation.id]);
            this.applyConversationPayload(payload);
            this.resetCodeBrowser();
            this.notification.add(`Committed to ${payload.conversation.review_branch}.`, { type: "success" });
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
            const payload = await this.call("create_workspace_pull_request", [this.state.conversation.id]);
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

    /**
     * Split a unified diff into classified lines so the template can colour
     * additions, removals and hunk headers instead of rendering flat text.
     */
    diffLines(diffText) {
        return String(diffText || "").split("\n").map((text, index) => {
            let kind = "context";
            if (text.startsWith("@@")) {
                kind = "hunk";
            } else if (DIFF_META_RE.test(text)) {
                kind = "meta";
            } else if (text.startsWith("+")) {
                kind = "add";
            } else if (text.startsWith("-")) {
                kind = "del";
            }
            return { key: index, kind, text };
        });
    }
}

registry.category("actions").add(
    "centric_claude_integration.developer_workspace",
    ClaudeDeveloperWorkspace
);
