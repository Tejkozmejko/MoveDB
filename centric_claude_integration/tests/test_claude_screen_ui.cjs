/* Run with node; Odoo services are replaced while the actual module methods run. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const jsRoot = path.join(__dirname, "../static/src/js");
const stripModules = (name) => fs.readFileSync(path.join(jsRoot, name), "utf8")
    .replace(/^import[\s\S]*?;\r?$/gm, "").replace(/^export /gm, "");
const sandbox = {
    Component: class {}, FormController: class {}, ListController: class {}, KanbanController: class {},
    registry: { category: () => ({ add() {} }) }, patch() {}, reactive: (value) => value,
    user: { context: { allowed_company_ids: [1] } }, _t: (text) => text,
    setTimeout, clearTimeout,
};
vm.createContext(sandbox);
vm.runInContext(stripModules("claude_screen_context.js") +
    "\nglobalThis.capture = captureScreenContext; globalThis.serviceDefinition = claudeScreenService;", sandbox);
vm.runInContext(stripModules("claude_screen_panel.js") +
    "\nglobalThis.Panel = ClaudeScreenPanel;", sandbox);
const plain = (value) => JSON.parse(JSON.stringify(value));
const controller = (root, extra = {}) => ({
    props: { resModel: "helpdesk.ticket", context: {}, ...extra }, model: { root },
});

test("form context carries identifiers and no unsaved field values", () => {
    const context = sandbox.capture(controller({ resId: 142, data: { description: "unsaved secret" } }), "form");
    assert.deepEqual(plain(context), {
        model: "helpdesk.ticket", allowed_company_ids: [1], active_test: true,
        scope: "record", record_ids: [142], is_new: false,
    });
});

test("new forms are marked unsaved without falling back to every record", () => {
    const context = sandbox.capture(controller({ isNew: true }), "form");
    assert.equal(context.is_new, true);
    assert.equal(context.scope, "record");
    assert.deepEqual(plain(context.record_ids), []);
});

test("list selection takes priority over the filter", () => {
    const context = sandbox.capture(controller({ selection: [{ resId: 2 }, { resId: 9 }], domain: [] }), "list");
    assert.equal(context.scope, "selection");
    assert.deepEqual(plain(context.record_ids), [2, 9]);
});

test("select all matching uses the domain rather than the loaded page", () => {
    const domain = [["stage_id", "=", 4]];
    const context = sandbox.capture(controller({
        selection: [{ resId: 2 }], isDomainSelected: true, domain,
    }), "list");
    assert.equal(context.scope, "filter");
    assert.deepEqual(plain(context.domain), domain);
    assert.deepEqual(plain(context.record_ids), []);
    domain.push(["priority", "=", "3"]);
    assert.equal(context.domain.length, 1, "Captured filters are a snapshot");
});

test("kanban preserves filters, selected companies and archived-record scope", () => {
    const context = sandbox.capture(controller({
        domain: [["team_id", "=", 7]], context: { allowed_company_ids: [3, 1], active_test: false },
    }), "kanban");
    assert.deepEqual(plain(context.allowed_company_ids), [3, 1]);
    assert.equal(context.active_test, false);
    assert.equal(context.scope, "filter");
});

test("context service forgets unmounted and hidden views", () => {
    const service = sandbox.serviceDefinition.start();
    const removeA = service.register("A", () => ({ model: "helpdesk.ticket" }));
    const removeB = service.register("B", () => ({ model: "res.partner" }));
    assert.equal(service.state.current.model, "res.partner");
    removeB();
    assert.equal(service.state.current.model, "helpdesk.ticket");
    service.register("hidden", () => null);
    assert.equal(service.state.current.model, "helpdesk.ticket");
    removeA();
    assert.equal(service.state.current, null);
});

function panel() {
    const result = Object.create(sandbox.Panel.prototype);
    result.revision = 1;
    result.polling = false;
    result.screenState = { open: true };
    result.state = {
        conversation: { id: 10 }, messages: [], operations: [], agent: { waiting: true },
        draft: "", context: { scope: "record" }, sending: false, answering: false,
    };
    result.schedulePoll = () => {};
    return result;
}

test("a late poll cannot replace a chat after a screen switch", async () => {
    const instance = panel();
    let resolve;
    instance.call = () => new Promise((done) => { resolve = done; });
    let applied = false;
    instance.applyPayload = () => { applied = true; };
    const pending = instance.pollOnce();
    instance.revision++;
    instance.state.conversation = { id: 20 };
    resolve({ conversation: { id: 10 }, messages: [{ id: 1 }] });
    await pending;
    assert.equal(applied, false);
    assert.equal(instance.state.conversation.id, 20);
});

test("slow polls do not overlap", async () => {
    const instance = panel();
    let resolve;
    let calls = 0;
    instance.call = () => { calls++; return new Promise((done) => { resolve = done; }); };
    const pending = instance.pollOnce();
    await instance.pollOnce();
    assert.equal(calls, 1);
    resolve({ unchanged: true, agent: { waiting: false } });
    await pending;
    assert.equal(instance.polling, false);
});

test("sending reuses the pinned conversation and does not read the new screen", async () => {
    const instance = panel();
    instance.state.agent = {};
    instance.state.draft = "Summarize this ticket";
    instance.screenState.current = { model: "res.partner", record_ids: [99] };
    let sent;
    instance.call = async (method, args) => {
        sent = { method, args };
        return { conversation: { id: 10 }, messages: [], agent: {} };
    };
    instance.applyPayload = () => {};
    await instance.sendMessage();
    assert.equal(sent.method, "send_workspace_message");
    assert.equal(sent.args[0], 10);
    assert.equal(sent.args[1], "Summarize this ticket");
});

test("failed send keeps the draft available for retry", async () => {
    const instance = panel();
    instance.state.agent = {};
    instance.state.draft = "Keep this question";
    instance.call = async () => { throw new Error("Offline"); };
    await instance.sendMessage();
    assert.equal(instance.state.draft, "Keep this question");
    assert.equal(instance.state.error, "Offline");
    assert.equal(instance.state.sending, false);
});

test("proposals are applied only by the explicit confirmation handler", async () => {
    const instance = panel();
    instance.state.agent = {};
    const calls = [];
    instance.call = async (method, args) => { calls.push({ method, args }); return {}; };
    instance.applyPayload = () => {};
    assert.equal(calls.length, 0);
    await instance.answerOperation({ id: 5 }, true);
    assert.equal(calls[0].method, "apply_workspace_operation");
    assert.deepEqual(plain(calls[0].args), [10, 5]);
});
