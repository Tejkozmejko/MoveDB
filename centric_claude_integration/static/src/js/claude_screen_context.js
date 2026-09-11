/** @odoo-module **/

import { onMounted, onPatched, onWillUnmount, reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";
import { ListController } from "@web/views/list/list_controller";
import { KanbanController } from "@web/views/kanban/kanban_controller";

/** Identifiers only: never copy form field values or a controller's whole context. */
export function captureScreenContext(controller, viewType) {
    const root = controller.model?.root;
    if (!root || !controller.props.resModel) {
        return null;
    }
    const context = root.context || controller.props.context || {};
    const common = {
        model: controller.props.resModel,
        allowed_company_ids: [...(context.allowed_company_ids || user.context.allowed_company_ids || [])],
        active_test: context.active_test !== false,
    };
    if (viewType === "form") {
        return {
            ...common,
            scope: "record",
            record_ids: root.resId ? [root.resId] : [],
            is_new: Boolean(root.isNew || !root.resId),
        };
    }
    const ids = (root.selection || []).map((record) => record.resId).filter(Number.isInteger);
    if (ids.length && !root.isDomainSelected) {
        return { ...common, scope: "selection", record_ids: ids };
    }
    // "Select all matching records" is a domain, not just the loaded page.
    return {
        ...common,
        scope: "filter",
        record_ids: [],
        domain: JSON.parse(JSON.stringify(root.domain || controller.props.domain || [])),
    };
}

export function screenContextKey(context) {
    return JSON.stringify(context || null);
}

export const claudeScreenService = {
    start() {
        const providers = new Map();
        const state = reactive({ open: false, current: null });
        const service = {
            state,
            register(owner, read) {
                providers.set(owner, read);
                service.refresh();
                return () => {
                    providers.delete(owner);
                    service.refresh();
                };
            },
            refresh() {
                let current = null;
                for (const read of [...providers.values()].reverse()) {
                    current = read();
                    if (current) {
                        break;
                    }
                }
                if (screenContextKey(current) !== screenContextKey(state.current)) {
                    state.current = current;
                }
                return current;
            },
            toggle() {
                service.refresh();
                state.open = !state.open;
            },
            close() {
                state.open = false;
            },
        };
        return service;
    },
};

registry.category("services").add("centric_claude_screen", claudeScreenService);

function useClaudeScreen(controller, viewType) {
    const screen = useService("centric_claude_screen");
    let unregister;
    onMounted(() => {
        unregister = screen.register(controller, () => {
            const element = controller.rootRef?.el;
            // Embedded views and dialogs must not replace the main page's scope.
            if (controller.env.inDialog || !element?.isConnected || !element.getClientRects().length) {
                return null;
            }
            return captureScreenContext(controller, viewType);
        });
    });
    onPatched(() => screen.refresh());
    onWillUnmount(() => unregister?.());
}

for (const [Controller, viewType] of [
    [FormController, "form"], [ListController, "list"], [KanbanController, "kanban"],
]) {
    patch(Controller.prototype, {
        setup() {
            super.setup(...arguments);
            useClaudeScreen(this, viewType);
        },
    });
}
