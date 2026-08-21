/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

/**
 * The Claude mark in the navbar, one click from anywhere in Odoo.
 *
 * Registered with a very high sequence because the systray renders its entries
 * highest-sequence-first, left to right: this is what puts the mark immediately
 * to the left of Odoo's own AI button rather than somewhere in the middle of
 * the tray.
 */
export class ClaudeSystrayItem extends Component {
    static template = "centric_claude_integration.ClaudeSystrayItem";
    static props = {};

    setup() {
        this.action = useService("action");
        this.state = useState({ allowed: false });
        onWillStart(async () => {
            // The registry is client-side, so the group check has to happen
            // here: without it the mark would show for every user in the
            // database, including the ones the action would refuse.
            this.state.allowed = await user.hasGroup(
                "centric_claude_integration.group_claude_user"
            );
        });
    }

    openWorkspace() {
        this.action.doAction("centric_claude_integration.action_claude_workspace");
    }
}

registry.category("systray").add(
    "centric_claude_integration.claude",
    { Component: ClaudeSystrayItem },
    { sequence: 1000 }
);
