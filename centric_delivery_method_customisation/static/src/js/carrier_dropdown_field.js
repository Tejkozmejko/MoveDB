/** @odoo-module **/

import { Component, onWillDestroy, onWillStart, useState, xml } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";

function isComponentDestroyedError(error) {
    return String(error?.message || error) === "Component is destroyed";
}

export class CarrierDropdownField extends Component {
    static template = xml`
        <div class="centric_carrier_dropdown"
             t-on-click="stopEvent"
             t-on-mousedown="stopEvent"
             t-on-mouseup="stopEvent"
             t-on-pointerdown="stopEvent"
             t-on-pointerup="stopEvent">
            <select class="o_input w-100"
                    t-att-value="currentId"
                    t-att-disabled="isDisabled"
                    t-on-click="stopEvent"
                    t-on-change="onChange">
                <option value="" t-att-selected="!currentId"></option>
                <t t-foreach="state.carriers" t-as="carrier" t-key="carrier.id">
                    <option t-att-value="carrier.id" t-att-selected="carrier.id === currentId">
                        <t t-esc="carrier.display_name"/>
                    </option>
                </t>
            </select>
        </div>
    `;
    static props = standardFieldProps;

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.state = useState({ carriers: [] });
        this._centricIsDestroyed = false;

        onWillDestroy(() => {
            this._centricIsDestroyed = true;
        });
        onWillStart(async () => {
            try {
                await this.loadCarriers();
            } catch (error) {
                if (!isComponentDestroyedError(error)) {
                    throw error;
                }
            }
        });
    }

    get currentValue() {
        return this.props.record.data[this.props.name];
    }

    get currentId() {
        if (!this.currentValue) {
            return "";
        }
        if (Array.isArray(this.currentValue)) {
            return this.currentValue[0] || "";
        }
        return this.currentValue.id || this.currentValue.resId || "";
    }

    get currentDisplayName() {
        if (!this.currentValue) {
            return "";
        }
        if (Array.isArray(this.currentValue)) {
            return this.currentValue[1] || "";
        }
        return this.currentValue.display_name || this.currentValue.displayName || "";
    }

    get companyId() {
        const company = this.props.record.data.company_id;
        if (!company) {
            return false;
        }
        if (Array.isArray(company)) {
            return company[0] || false;
        }
        return company.id || company.resId || false;
    }

    get isDisabled() {
        return ["cancel", "done"].includes(this.props.record.data.state);
    }

    get listContext() {
        return this.props.record.model?.root?.context || this.props.record.context || {};
    }

    get recordModel() {
        return this.props.record.resModel || this.props.record.model?.config?.resModel || "";
    }

    get shouldConfirmDeliveryRouteSplit() {
        return (
            this.recordModel === "stock.picking"
            && Boolean(this.listContext.centric_is_delivery_operation)
            && !this.isDisabled
        );
    }

    stopEvent(ev) {
        ev.stopPropagation();
    }

    async loadCarriers() {
        const domain = this.companyId
            ? ["|", ["company_id", "=", false], ["company_id", "=", this.companyId]]
            : [];
        const carriers = await this.orm.searchRead(
            "delivery.carrier",
            domain,
            ["display_name"],
            { order: "sequence, id" }
        );

        if (this._centricIsDestroyed) {
            return;
        }
        if (this.currentId && !carriers.some((carrier) => carrier.id === this.currentId)) {
            carriers.unshift({
                id: this.currentId,
                display_name: this.currentDisplayName,
            });
        }
        this.state.carriers = carriers;
    }

    async saveCarrier(carrierId) {
        if (this._centricIsDestroyed) {
            return;
        }
        const carrier = this.state.carriers.find((item) => item.id === carrierId);
        const value = carrierId
            ? { id: carrierId, display_name: carrier?.display_name || "" }
            : false;

        try {
            await this.props.record.update({
                [this.props.name]: value,
            }, { save: true });
        } catch (error) {
            if (!isComponentDestroyedError(error)) {
                throw error;
            }
        }
    }

    async onChange(ev) {
        this.stopEvent(ev);
        const previousValue = this.currentId ? String(this.currentId) : "";
        const carrierId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        if (carrierId === this.currentId) {
            return;
        }

        if (this.shouldConfirmDeliveryRouteSplit) {
            ev.target.value = previousValue;
            this.dialog.add(ConfirmationDialog, {
                title: _t("Split delivery route?"),
                body: _t(
                    "This will create a separate sales order for this delivery/category "
                    + "and move it to the selected route. The other Frozen/Dry categories "
                    + "will stay on the original order and current route."
                ),
                confirmLabel: _t("Split Order"),
                cancelLabel: _t("Keep Current Route"),
                confirm: async () => {
                    if (!this._centricIsDestroyed) {
                        await this.saveCarrier(carrierId);
                    }
                },
            });
            return;
        }

        await this.saveCarrier(carrierId);
    }
}

registry.category("fields").add("centric_carrier_dropdown", {
    component: CarrierDropdownField,
    supportedTypes: ["many2one"],
});

export class DriverDropdownField extends Component {
    static template = xml`
        <div class="centric_driver_dropdown"
             t-on-click="stopEvent"
             t-on-mousedown="stopEvent"
             t-on-mouseup="stopEvent"
             t-on-pointerdown="stopEvent"
             t-on-pointerup="stopEvent">
            <select class="o_input w-100"
                    t-att-value="currentId"
                    t-att-disabled="isDisabled"
                    t-on-click="stopEvent"
                    t-on-change="onChange">
                <option value="" t-att-selected="!currentId"></option>
                <t t-foreach="state.employees" t-as="employee" t-key="employee.id">
                    <option t-att-value="employee.id" t-att-selected="employee.id === currentId">
                        <t t-esc="employee.display_name"/>
                    </option>
                </t>
            </select>
        </div>
    `;
    static props = standardFieldProps;

    setup() {
        this.orm = useService("orm");
        this.state = useState({ employees: [] });
        this._centricIsDestroyed = false;
        onWillDestroy(() => {
            this._centricIsDestroyed = true;
        });
        onWillStart(async () => {
            try {
                await this.loadEmployees();
            } catch (error) {
                if (!isComponentDestroyedError(error)) {
                    throw error;
                }
            }
        });
    }

    get currentValue() {
        return this.props.record.data[this.props.name];
    }

    get currentId() {
        const value = this.currentValue;
        if (!value) {
            return "";
        }
        if (Array.isArray(value)) {
            return value[0] || "";
        }
        return value.id || value.resId || "";
    }

    get currentDisplayName() {
        const value = this.currentValue;
        if (!value) {
            return "";
        }
        if (Array.isArray(value)) {
            return value[1] || "";
        }
        return value.display_name || value.displayName || "";
    }

    get companyId() {
        const company = this.props.record.data.company_id;
        if (!company) {
            return false;
        }
        if (Array.isArray(company)) {
            return company[0] || false;
        }
        return company.id || company.resId || false;
    }

    get isDisabled() {
        return ["cancel", "canceled", "done"].includes(this.props.record.data.state);
    }

    stopEvent(ev) {
        ev.stopPropagation();
    }

    async loadEmployees() {
        const companyId = this.companyId;
        let departmentId = false;
        if (companyId) {
            const companies = await this.orm.read(
                "res.company", [companyId], ["centric_driver_department_id"]);
            const dep = companies && companies[0] && companies[0].centric_driver_department_id;
            departmentId = Array.isArray(dep) ? dep[0] : (dep || false);
        }
        const domain = [];
        if (companyId) {
            domain.push("|", ["company_id", "=", false], ["company_id", "=", companyId]);
        }
        if (departmentId) {
            domain.push(["department_id", "=", departmentId]);
        }
        const employees = await this.orm.searchRead(
            "hr.employee", domain, ["display_name"], { order: "name, id" });
        if (this._centricIsDestroyed) {
            return;
        }
        if (this.currentId && !employees.some((employee) => employee.id === this.currentId)) {
            employees.unshift({ id: this.currentId, display_name: this.currentDisplayName });
        }
        this.state.employees = employees;
    }

    async onChange(ev) {
        this.stopEvent(ev);
        const employeeId = ev.target.value ? parseInt(ev.target.value, 10) : false;
        if (employeeId === this.currentId) {
            return;
        }
        const employee = this.state.employees.find((item) => item.id === employeeId);
        const value = employeeId
            ? { id: employeeId, display_name: employee?.display_name || "" }
            : false;
        try {
            await this.props.record.update({ [this.props.name]: value }, { save: true });
        } catch (error) {
            if (!isComponentDestroyedError(error)) {
                throw error;
            }
        }
    }
}

registry.category("fields").add("centric_driver_dropdown", {
    component: DriverDropdownField,
    supportedTypes: ["many2one"],
});

export class QuantityInputField extends Component {
    static template = xml`
        <div class="centric_quantity_input"
             t-on-click="stopEvent"
             t-on-mousedown="stopEvent"
             t-on-mouseup="stopEvent"
             t-on-pointerdown="stopEvent"
             t-on-pointerup="stopEvent">
            <input class="o_input"
                   type="text"
                   inputmode="decimal"
                   step="any"
                   t-att-value="currentValue"
                   t-att-disabled="isDisabled"
                   t-on-click="stopEvent"
                   t-on-change="onChange"/>
        </div>
    `;
    static props = standardFieldProps;

    get currentValue() {
        const value = this.props.record.data[this.props.name];

        if (value === 0 || value === 0.0 || value === null || value === undefined) {
            return "";
        }

        return value;
    }

    get isDisabled() {
        // Honour the view's readonly (e.g. the inline board Quantity is readonly
        // for multi-line pickings, which must use the Items popup) in addition to
        // the state gate.
        return this.props.readonly || ["cancel", "done"].includes(this.props.record.data.state);
    }

    get resModel() {
        return (
            this.props.record?.resModel
            || this.props.record?.model?.config?.resModel
            || ""
        );
    }

    get shouldStopNavigation() {
        // Only the pick/pack/delivery BOARD - a non-editable stock.picking list -
        // opens the picking form on a row click, so there we swallow the pointer
        // events to stop inline Quantity editing from navigating away. In the
        // editable "Items" popup (a wizard-line list) the click MUST reach the row
        // for it to enter edit mode; swallowing it leaves the cell un-editable
        // until the operator clicks a neighbouring cell first, which reads as "the
        // Quantity field needs several clicks before it accepts input".
        return this.resModel === "stock.picking";
    }

    stopEvent(ev) {
        if (this.shouldStopNavigation) {
            ev.stopPropagation();
        }
    }

    async onChange(ev) {
        // onChange must run in every context; only navigation-swallowing is
        // board-only, handled inside stopEvent.
        this.stopEvent(ev);

        const value = ev.target.value.replace(",", ".");
        const quantity = value === "" ? 0 : parseFloat(value);

        if (Number.isNaN(quantity)) {
            ev.target.value = this.currentValue;
            return;
        }

        try {
            await this.props.record.update({
                [this.props.name]: quantity,
            }, { save: true });
        } catch (error) {
            if (!isComponentDestroyedError(error)) {
                throw error;
            }
        }
    }
}

registry.category("fields").add("centric_quantity_input", {
    component: QuantityInputField,
    supportedTypes: ["float"],
});

const CENTRIC_PICK_ACTION_STYLE_ID = "centric_pick_action_style";
const listControllerClassName = Object.getOwnPropertyDescriptor(
    ListController.prototype,
    "className"
);
const listControllerActionMenuItems = Object.getOwnPropertyDescriptor(
    ListController.prototype,
    "actionMenuItems"
);
const listRendererOptionalFieldGroups = Object.getOwnPropertyDescriptor(
    ListRenderer.prototype,
    "optionalFieldGroups"
);

function ensureCentricPickActionStyles() {
    if (document.getElementById(CENTRIC_PICK_ACTION_STYLE_ID)) {
        return;
    }
    const style = document.createElement("style");
    style.id = CENTRIC_PICK_ACTION_STYLE_ID;
    style.textContent = `
        .o_centric_pick_action_button {
            display: none !important;
        }
        .o_centric_stock_pick_list .o_centric_pick_action_button {
            display: inline-flex !important;
        }
        .o_centric_pack_action_button {
            display: none !important;
        }
        .o_centric_stock_pack_list .o_centric_pack_action_button {
            display: inline-flex !important;
        }
        .o_centric_delivery_action_button {
            display: none !important;
        }
        .o_centric_stock_delivery_list .o_centric_delivery_action_button {
            display: inline-flex !important;
        }
        .o_centric_stock_pick_list .o_cp_action_menus button:has(.fa-print) {
            background-color: var(--o-brand-primary, #714b67) !important;
            border-color: var(--o-brand-primary, #714b67) !important;
            color: #fff !important;
        }
        .o_centric_stock_pack_list .o_cp_action_menus button:has(.fa-print) {
            display: none !important;
        }
        .o_centric_stock_pick_list .fa-print {
            position: relative;
            top: 3px;
        }
        .o_centric_stock_picking_list th[data-name="batch_id"],
        .o_centric_stock_picking_list td[name="batch_id"],
        .o_centric_stock_picking_list td[data-name="batch_id"] {
            display: none !important;
        }
        .o_centric_stock_picking_list .o_optional_columns_dropdown [data-name="batch_id"] {
            display: none !important;
        }
        .o_centric_stock_picking_list .o_optional_columns_dropdown [name="batch_id"] {
            display: none !important;
        }
        .o_centric_stock_pick_list td[name="centric_quantity"],
        .o_centric_stock_pack_list td[name="centric_quantity"],
        .o_centric_stock_picking_list td[name="centric_quantity"],
        .o_centric_stock_pick_list td[data-name="centric_quantity"],
        .o_centric_stock_pack_list td[data-name="centric_quantity"],
        .o_centric_stock_picking_list td[data-name="centric_quantity"],
        .o_centric_stock_pick_list th[data-name="centric_quantity"],
        .o_centric_stock_pack_list th[data-name="centric_quantity"],
        .o_centric_stock_picking_list th[data-name="centric_quantity"],
        .o_centric_stock_pack_list td[name="centric_pack_entered_qty"],
        .o_centric_stock_picking_list td[name="centric_pack_entered_qty"],
        .o_centric_stock_pack_list td[data-name="centric_pack_entered_qty"],
        .o_centric_stock_picking_list td[data-name="centric_pack_entered_qty"],
        .o_centric_stock_pack_list th[data-name="centric_pack_entered_qty"],
        .o_centric_stock_picking_list th[data-name="centric_pack_entered_qty"] {
            width: 4.5rem !important;
            max-width: 4.5rem !important;
        }
        .o_centric_stock_pick_list .centric_quantity_input,
        .o_centric_stock_pack_list .centric_quantity_input,
        .o_centric_stock_picking_list .centric_quantity_input {
            display: flex;
            justify-content: flex-end;
        }
        .o_centric_stock_pick_list .centric_quantity_input .o_input,
        .o_centric_stock_pack_list .centric_quantity_input .o_input,
        .o_centric_stock_picking_list .centric_quantity_input .o_input {
            width: 4rem;
            min-width: 4rem;
            text-align: right;
        }
    `;
    document.head.appendChild(style);
}

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        ensureCentricPickActionStyles();
    },

    get className() {
        let className = listControllerClassName.get.call(this) || "";
        if (this._centricIsStockPickingList()) {
            className = `${className} o_centric_stock_picking_list`;
        }
        if (this._centricIsStockPickList()) {
            className = `${className} o_centric_stock_pick_list`;
        }
        if (this._centricIsStockPackList()) {
            className = `${className} o_centric_stock_pack_list`;
        }
        if (this._centricIsStockDeliveryList()) {
            className = `${className} o_centric_stock_delivery_list`;
        }
        return className;
    },

    get actionMenuItems() {
        const items = listControllerActionMenuItems
            ? listControllerActionMenuItems.get.call(this)
            : super.actionMenuItems;
        // On delivery orders the "Validate" action is exposed as a dedicated
        // header button (o_centric_delivery_action_button), so drop the
        // duplicate entry from the cog "Action" menu for that list only.
        if (!this._centricIsStockDeliveryList() || !items?.action) {
            return items;
        }
        return {
            ...items,
            action: items.action.filter((item) => item.name !== "Validate"),
        };
    },

    _centricIsStockPickingList() {
        return this.props.resModel === "stock.picking";
    },

    _centricIsStockPickList() {
        const context = this.model?.root?.context || this.props.context || {};
        return this.props.resModel === "stock.picking" && Boolean(context.centric_is_pick_operation);
    },

    _centricIsStockPackList() {
        const context = this.model?.root?.context || this.props.context || {};
        return this.props.resModel === "stock.picking" && Boolean(context.centric_is_pack_operation);
    },

    _centricIsStockDeliveryList() {
        const context = this.model?.root?.context || this.props.context || {};
        return this.props.resModel === "stock.picking"
            && Boolean(context.centric_is_delivery_operation);
    },
});

patch(ListRenderer.prototype, {
    get optionalFieldGroups() {
        const groups = listRendererOptionalFieldGroups.get.call(this);
        if (this.props.list?.resModel !== "stock.picking") {
            return groups;
        }
        return groups
            .map((group) => ({
                ...group,
                optionalFields: group.optionalFields.filter((field) => field.name !== "batch_id"),
            }))
            .filter((group) => group.displayName || group.optionalFields.length);
    },
});
