/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

// "Lots/Serials" button for the PACK/PICK "Items" popup.
//
// The Items popup is itself an act_window dialog (target: "new"). Odoo's
// ActionService keeps only ONE action-dialog slot: opening a second
// target:"new" action (the standard "Detailed Operations" of a move) REMOVES
// the Items popup and replaces it, so closing Detailed Operations by any means
// (Save / Discard / X) drops all the way back to the transfers list and the
// operator's unsaved quantities are lost (see action_service.js: for
// target === "new", `dialog?.remove(); dialog = nextDialog;`).
//
// This widget instead opens Detailed Operations through the DIALOG SERVICE
// (FormViewDialog), which STACKS on top of the Items popup rather than
// replacing it. Closing Detailed Operations then returns to the Items popup
// exactly as expected, and the popup's in-memory quantities are never touched.
export class CentricLotsSerialsButton extends Component {
    static template = "centric_delivery_method_customisation.LotsSerialsButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.dialog = useService("dialog");
        this.orm = useService("orm");
    }

    get moveId() {
        const record = this.props.record;
        // Reusable in both the wizard line (move_id m2o) and a stock.move list.
        if (record.resModel === "stock.move") {
            return record.resId;
        }
        const move = record.data.move_id;
        if (!move) {
            return false;
        }
        // Odoo 19 exposes a many2one value as an object { id, display_name };
        // older builds used an [id, display_name] array. Handle both (and a
        // bare id) so we never pass the whole object to browse().
        if (Array.isArray(move)) {
            return move[0];
        }
        if (typeof move === "object") {
            return move.id;
        }
        return move;
    }

    async onClick() {
        const moveId = this.moveId;
        if (!moveId) {
            return;
        }
        // Reuse the exact server action (correct view id + context, incl.
        // centric_show_lots_serials and any PICK-stage auto-fill prep) that the
        // button used to return, but open it as a STACKED dialog instead of
        // doAction-ing it.
        const action = await this.orm.call("stock.move", "action_centric_show_details", [moveId]);
        const formView = (action.views || []).find((view) => view[1] === "form");
        this.dialog.add(FormViewDialog, {
            resModel: action.res_model || "stock.move",
            resId: action.res_id || moveId,
            viewId: formView ? formView[0] : false,
            context: action.context || {},
            title: action.name || _t("Detailed Operations"),
        });
    }
}

export const centricLotsSerialsButton = {
    component: CentricLotsSerialsButton,
    fieldDependencies: [
        { name: "move_id", type: "many2one" },
        { name: "show_details_visible", type: "boolean" },
    ],
};

registry.category("view_widgets").add("centric_lots_serials_button", centricLotsSerialsButton);
