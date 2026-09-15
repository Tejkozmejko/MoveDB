/** @odoo-module **/

import { Component, markup, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { renderMarkdown } from "./claude_markdown";
import { screenContextKey } from "./claude_screen_context";

// What the paperclip offers. The server decides from the bytes either way;
// this only keeps the file dialog from suggesting files that will be refused.
const ATTACH_ACCEPT = "image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,"
    + ".txt,.csv,.md,.json,.log,.xml";

function readAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const result = String(reader.result || "");
            resolve(result.slice(result.indexOf(",") + 1));
        };
        reader.onerror = () => reject(reader.error || new Error("Could not read the file."));
        reader.readAsDataURL(file);
    });
}

export class ClaudeScreenPanel extends Component {
    static template = "centric_claude_integration.ClaudeScreenPanel";
    static props = {};

    setup() {
        this.screen = useService("centric_claude_screen");
        this.screenState = useState(this.screen.state);
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: false, sending: false, answering: false, error: "", pollError: "",
            access: {}, context: null, rawContext: null, initialized: false,
            conversation: null, messages: [], operations: [], agent: {}, draft: "",
            pendingAttachments: [], uploading: 0, dragging: false,
            model: "", effort: "",
            history: [], historyOpen: false, historyLoading: false,
        });
        this.attachAccept = ATTACH_ACCEPT;
        this.scroll = useRef("messages");
        this.composer = useRef("composer");
        this.fileInput = useRef("fileInput");
        this.rendered = new Map();
        this.revision = 0;
        this.pollTimer = null;
        this.polling = false;
        useEffect(() => {
            if (this.screenState.open) {
                if (!this.state.initialized) {
                    this.useCurrentScreen();
                } else {
                    this.schedulePoll();
                }
                this.composer.el?.focus();
            } else {
                this.stopPolling();
            }
        }, () => [this.screenState.open]);
        useEffect(() => {
            if (this.scroll.el && !this.state.historyOpen) {
                this.scroll.el.scrollTop = this.scroll.el.scrollHeight;
            }
        }, () => [this.state.messages.length, this.state.operations.length, this.state.sending, this.state.historyOpen]);
        onWillUnmount(() => {
            this.revision++;
            this.stopPolling();
        });
    }

    call(method, args = []) {
        return this.orm.call("centric.claude.conversation", method, args, {});
    }

    errorMessage(error) {
        return error?.data?.message || error?.message || String(error);
    }

    resetChat() {
        this.stopPolling();
        this.rendered.clear();
        Object.assign(this.state, {
            conversation: null, messages: [], operations: [], agent: {}, draft: "",
            pendingAttachments: [], error: "", pollError: "", historyOpen: false,
            model: this.state.access.default_model || this.state.model,
            effort: this.state.access.default_effort || this.state.effort,
        });
    }

    async useCurrentScreen() {
        if (this.state.sending || this.state.answering) {
            return;
        }
        const raw = this.screen.refresh();
        const revision = ++this.revision;
        this.discardPending();
        this.resetChat();
        Object.assign(this.state, {
            initialized: true, loading: true, context: null, history: [],
            rawContext: raw ? JSON.parse(JSON.stringify(raw)) : null,
        });
        try {
            const bootstrap = await this.call("workspace_bootstrap");
            if (revision !== this.revision) {
                return;
            }
            this.state.access = bootstrap.access || {};
            this.state.model = this.state.access.default_model || "";
            this.state.effort = this.state.access.default_effort || "";
            if (!this.state.access.can_chat) {
                throw new Error(_t("Claude is disabled or your account does not have workspace access."));
            }
            if (!this.state.access.can_read_data) {
                throw new Error(_t("Ask an administrator to give your account a Centric Claude Data level to use screen context."));
            }
            if (!raw) {
                throw new Error(_t("Open a saved record, list, or kanban view, then choose Use current screen."));
            }
            const context = await this.call("prepare_screen_context", [raw]);
            if (revision === this.revision) {
                this.state.context = context;
                this.loadHistory();
            }
        } catch (error) {
            if (revision === this.revision) {
                this.state.error = this.errorMessage(error);
            }
        } finally {
            if (revision === this.revision) {
                this.state.loading = false;
            }
        }
    }

    get screenChanged() {
        return screenContextKey(this.state.rawContext) !== screenContextKey(this.screenState.current);
    }

    get waiting() {
        return this.state.sending || this.state.answering || Boolean(this.state.agent.waiting);
    }

    get pending() {
        return this.state.pendingAttachments || [];
    }

    get canSend() {
        return Boolean(
            this.state.context && !this.state.uploading && !this.waiting && !this.state.loading
            && (this.state.draft.trim() || this.pending.length)
        );
    }

    get attachmentsEnabled() {
        return Boolean(this.state.access.attachments_enabled);
    }

    get modelChoices() {
        return this.state.access.model_choices || [];
    }

    get effortChoices() {
        return this.state.access.effort_choices || [];
    }

    shortLabel(label) {
        return String(label || "").split(" - ")[0];
    }

    get suggestions() {
        if (this.state.context?.model === "helpdesk.ticket") {
            return this.state.context.scope === "record" ? [
                _t("Summarize this ticket and what has been tried."),
                _t("Draft a reply to the customer for me to review."),
                _t("What information is missing to resolve this ticket?"),
            ] : [
                _t("Summarize these tickets."),
                _t("Which of these tickets need attention first, and why?"),
                _t("Are there recurring issues in these tickets?"),
            ];
        }
        return this.state.context?.scope === "record" ? [
            _t("Summarize this record."), _t("What should I check next?"),
        ] : [_t("Summarize these records."), _t("Which records need attention, and why?")];
    }

    useSuggestion(text) {
        this.state.draft = text;
        this.composer.el?.focus();
    }

    applyPayload(payload) {
        this.state.conversation = payload.conversation;
        this.state.context = payload.conversation.screen_context || this.state.context;
        this.state.messages = payload.messages || [];
        this.state.operations = payload.operations || [];
        this.state.agent = payload.agent || {};
        this.state.access = payload.access || this.state.access;
        if (payload.conversation.model) {
            this.state.model = payload.conversation.model;
        }
        if (payload.conversation.effort) {
            this.state.effort = payload.conversation.effort;
        }
        this.schedulePoll();
    }

    // A chat is only created once there is something to put in it - a question
    // or a file - and it starts with the model and effort already picked.
    async ensureConversation(revision) {
        if (this.state.conversation) {
            return this.state.conversation.id;
        }
        const payload = await this.call("create_screen_conversation", [
            this.state.rawContext, { model: this.state.model, effort: this.state.effort },
        ]);
        if (revision !== this.revision) {
            return false;
        }
        this.applyPayload(payload);
        return payload.conversation.id;
    }

    async sendMessage(event) {
        event?.preventDefault();
        if (!this.canSend) {
            return;
        }
        const revision = this.revision;
        const text = this.state.draft.trim();
        const attachments = this.pending.map((item) => item.id);
        this.state.sending = true;
        this.state.error = "";
        try {
            const id = await this.ensureConversation(revision);
            if (!id) {
                return;
            }
            const payload = await this.call("send_workspace_message", [id, text, attachments]);
            if (revision === this.revision) {
                this.state.draft = "";
                this.state.pendingAttachments = [];
                this.applyPayload(payload);
                this.loadHistory();
            }
        } catch (error) {
            if (revision === this.revision) {
                this.state.error = this.errorMessage(error);
            }
        } finally {
            if (revision === this.revision) {
                this.state.sending = false;
            }
        }
    }

    onKeydown(event) {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            this.sendMessage();
        }
    }

    // ------------------------------------------------------ model & effort
    async setModel(event) {
        const previous = this.state.model;
        this.state.model = event.target.value;
        if (!this.state.conversation) {
            return;
        }
        try {
            this.applyPayload(await this.call("set_workspace_model", [this.state.conversation.id, this.state.model]));
        } catch (error) {
            this.state.model = previous;
            event.target.value = previous;
            this.state.error = this.errorMessage(error);
        }
    }

    async setEffort(event) {
        const previous = this.state.effort;
        this.state.effort = event.target.value;
        if (!this.state.conversation) {
            return;
        }
        try {
            this.applyPayload(await this.call("set_workspace_effort", [this.state.conversation.id, this.state.effort]));
        } catch (error) {
            this.state.effort = previous;
            event.target.value = previous;
            this.state.error = this.errorMessage(error);
        }
    }

    // --------------------------------------------------------- attachments
    pickFiles() {
        this.fileInput.el?.click();
    }

    onFilesPicked(event) {
        const files = [...(event.target.files || [])];
        // Cleared, or picking the same file twice in a row fires no change.
        event.target.value = "";
        this.uploadFiles(files);
    }

    onPaste(event) {
        if (!this.attachmentsEnabled) {
            return;
        }
        const files = [...(event.clipboardData?.items || [])]
            .filter((item) => item.kind === "file")
            .map((item) => item.getAsFile())
            .filter(Boolean);
        if (files.length) {
            // Otherwise an ordinary text paste, left to the textarea.
            event.preventDefault();
            this.uploadFiles(files);
        }
    }

    onDragOver(event) {
        if (this.attachmentsEnabled && this.state.context
                && [...(event.dataTransfer?.types || [])].includes("Files")) {
            event.preventDefault();
            this.state.dragging = true;
        }
    }

    onDragLeave() {
        this.state.dragging = false;
    }

    onDrop(event) {
        this.state.dragging = false;
        const files = [...(event.dataTransfer?.files || [])];
        if (!this.attachmentsEnabled || !files.length) {
            return;
        }
        event.preventDefault();
        this.uploadFiles(files);
    }

    async uploadFiles(files) {
        if (!this.attachmentsEnabled || !files.length || !this.state.context || this.state.sending) {
            return;
        }
        const revision = this.revision;
        this.state.error = "";
        this.state.uploading += 1;
        try {
            const conversationId = await this.ensureConversation(revision);
            if (!conversationId) {
                return;
            }
            for (const file of files) {
                const data = await readAsBase64(file);
                try {
                    const summary = await this.orm.call(
                        "centric.claude.attachment", "upload_workspace_attachment",
                        [conversationId, file.name || "", data], {}
                    );
                    // The chat can change mid-upload; keep the file only if
                    // we are still looking at the one it belongs to.
                    if (revision === this.revision && this.state.conversation?.id === conversationId) {
                        this.state.pendingAttachments.push(summary);
                    }
                } catch (error) {
                    if (revision === this.revision) {
                        this.state.error = `${file.name || _t("That file")}: ${this.errorMessage(error)}`;
                    }
                }
            }
        } catch (error) {
            if (revision === this.revision) {
                this.state.error = this.errorMessage(error);
            }
        } finally {
            this.state.uploading -= 1;
        }
    }

    async removeAttachment(attachment) {
        try {
            await this.orm.call("centric.claude.attachment", "discard_workspace_attachment", [attachment.id], {});
        } catch (error) {
            this.state.error = this.errorMessage(error);
            return;
        }
        const index = this.pending.findIndex((item) => item.id === attachment.id);
        if (index >= 0) {
            this.state.pendingAttachments.splice(index, 1);
        }
    }

    // Files picked but never sent are not left waiting on a chat we walk away from.
    discardPending() {
        for (const attachment of this.pending) {
            this.orm.call("centric.claude.attachment", "discard_workspace_attachment", [attachment.id], {})
                .catch(() => {});
        }
        this.state.pendingAttachments = [];
    }

    openAttachment(attachment) {
        window.open(attachment.url, "_blank", "noopener,noreferrer");
    }

    fileSize(bytes) {
        if (!bytes) {
            return "";
        }
        return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB`
            : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    }

    // ------------------------------------------------------------- history
    async loadHistory() {
        if (!this.state.rawContext || !this.state.context) {
            return;
        }
        const revision = this.revision;
        this.state.historyLoading = true;
        try {
            const history = await this.call("list_screen_conversations", [this.state.rawContext]);
            if (revision === this.revision) {
                this.state.history = history || [];
            }
        } catch {
            // The list is a convenience; a failure here must not block asking.
        } finally {
            if (revision === this.revision) {
                this.state.historyLoading = false;
            }
        }
    }

    toggleHistory() {
        this.state.historyOpen = !this.state.historyOpen;
        if (this.state.historyOpen) {
            this.loadHistory();
        }
    }

    get recentChats() {
        return this.state.history.slice(0, 3);
    }

    relativeTime(value) {
        if (!value) {
            return "";
        }
        const then = new Date(value.replace(" ", "T") + "Z");
        const minutes = Math.round((Date.now() - then.getTime()) / 60000);
        if (minutes < 1) {
            return _t("just now");
        }
        if (minutes < 60) {
            return _t("%s min ago", minutes);
        }
        const hours = Math.round(minutes / 60);
        if (hours < 24) {
            return _t("%s h ago", hours);
        }
        const days = Math.round(hours / 24);
        return days < 30 ? _t("%s d ago", days) : then.toLocaleDateString();
    }

    async openChat(item) {
        if (this.state.sending || this.state.answering || this.state.uploading) {
            return;
        }
        if (this.state.conversation?.id === item.id) {
            this.state.historyOpen = false;
            return;
        }
        const revision = ++this.revision;
        this.discardPending();
        this.resetChat();
        this.state.loading = true;
        try {
            const payload = await this.call("get_workspace_conversation", [item.id]);
            if (revision === this.revision) {
                this.applyPayload(payload);
            }
        } catch (error) {
            if (revision === this.revision) {
                this.state.error = this.errorMessage(error);
            }
        } finally {
            if (revision === this.revision) {
                this.state.loading = false;
            }
        }
    }

    newChat() {
        if (this.state.sending || this.state.answering || this.state.uploading) {
            return;
        }
        this.revision++;
        this.discardPending();
        this.resetChat();
        this.loadHistory();
        this.composer.el?.focus();
    }

    messageHtml(message) {
        const cached = this.rendered.get(message.id);
        if (cached?.source === message.content) {
            return cached.html;
        }
        const html = markup(renderMarkdown(message.content));
        this.rendered.set(message.id, { source: message.content, html });
        return html;
    }

    stopPolling() {
        clearTimeout(this.pollTimer);
        this.pollTimer = null;
    }

    schedulePoll() {
        this.stopPolling();
        if (this.screenState.open && this.state.agent.waiting && !this.polling) {
            this.pollTimer = setTimeout(() => this.pollOnce(), 1500);
        }
    }

    async pollOnce() {
        if (this.polling || !this.state.conversation || !this.screenState.open) {
            return;
        }
        const id = this.state.conversation.id;
        const revision = this.revision;
        this.polling = true;
        try {
            const after = this.state.messages.at(-1)?.id || 0;
            const payload = await this.call("poll_workspace_conversation", [id, after]);
            if (revision !== this.revision || id !== this.state.conversation?.id) {
                return;
            }
            this.state.pollError = "";
            if (payload.unchanged) {
                this.state.agent = payload.agent || {};
            } else {
                this.applyPayload(payload);
            }
        } catch (error) {
            if (revision === this.revision) {
                this.state.pollError = _t("Connection interrupted. Retrying…");
            }
        } finally {
            this.polling = false;
            this.schedulePoll();
        }
    }

    async answerOperation(operation, accept) {
        if (this.waiting || !this.state.conversation) {
            return;
        }
        this.state.answering = true;
        this.state.error = "";
        try {
            const payload = await this.call(
                accept ? "apply_workspace_operation" : "reject_workspace_operation",
                [this.state.conversation.id, operation.id]
            );
            this.applyPayload(payload);
        } catch (error) {
            this.state.error = this.errorMessage(error);
        } finally {
            this.state.answering = false;
        }
    }

    async openWorkspace() {
        await this.action.doAction("centric_claude_integration.action_claude_workspace", {
            additionalContext: { claude_conversation_id: this.state.conversation?.id || false },
        });
        this.screen.close();
    }

    close() {
        this.screen.close();
    }
}

registry.category("main_components").add("centric_claude_integration.screen_panel", {
    Component: ClaudeScreenPanel,
});
