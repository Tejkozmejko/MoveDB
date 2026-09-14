/** @odoo-module **/

import { Component, markup, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { renderMarkdown } from "./claude_markdown";
import { screenContextKey } from "./claude_screen_context";

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
        });
        this.scroll = useRef("messages");
        this.composer = useRef("composer");
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
            if (this.scroll.el) {
                this.scroll.el.scrollTop = this.scroll.el.scrollHeight;
            }
        }, () => [this.state.messages.length, this.state.operations.length, this.state.sending]);
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

    async useCurrentScreen() {
        if (this.state.sending || this.state.answering) {
            return;
        }
        const raw = this.screen.refresh();
        const revision = ++this.revision;
        this.stopPolling();
        this.rendered.clear();
        Object.assign(this.state, {
            initialized: true, loading: true, error: "", pollError: "", context: null,
            rawContext: raw ? JSON.parse(JSON.stringify(raw)) : null,
            conversation: null, messages: [], operations: [], agent: {}, draft: "",
        });
        try {
            const bootstrap = await this.call("workspace_bootstrap");
            if (revision !== this.revision) {
                return;
            }
            this.state.access = bootstrap.access || {};
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

    get canSend() {
        return Boolean(this.state.context && this.state.draft.trim() && !this.waiting && !this.state.loading);
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
        this.schedulePoll();
    }

    async sendMessage(event) {
        event?.preventDefault();
        if (!this.canSend) {
            return;
        }
        const revision = this.revision;
        const text = this.state.draft.trim();
        this.state.sending = true;
        this.state.error = "";
        try {
            if (!this.state.conversation) {
                const payload = await this.call("create_screen_conversation", [this.state.rawContext]);
                if (revision !== this.revision) {
                    return;
                }
                this.applyPayload(payload);
            }
            const id = this.state.conversation.id;
            const payload = await this.call("send_workspace_message", [id, text, []]);
            if (revision === this.revision) {
                this.state.draft = "";
                this.applyPayload(payload);
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
