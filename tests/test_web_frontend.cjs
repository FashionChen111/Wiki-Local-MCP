const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const page = fs.readFileSync(path.join(__dirname, "../src/confluence_mcp/web_page.py"), "utf8");
const script = page.split("<script>")[1].split("</script>")[0];

function functionSource(name) {
  const start = script.indexOf("function " + name + "(");
  assert.ok(start >= 0, "Missing frontend function " + name);
  const declaration = script.slice(start);
  const firstLine = declaration.split("\n", 1)[0];
  if (firstLine.endsWith("}")) return firstLine;
  const end = declaration.indexOf("\n}\n");
  assert.ok(end >= 0, "Missing end of frontend function " + name);
  return declaration.slice(0, end + 2);
}

function context() {
  const fields = { search: { value: "" }, "space-filter": { value: "" } };
  const statuses = ["pending", "approved", "executing", "succeeded", "failed", "indeterminate", "rejected"];
  const state = vm.createContext({
    ops: statuses.map((status, index) => ({
      id: "op-" + index,
      title: index === 0 ? "设备接入" : "Guide " + index,
      summary: "接入流程",
      status,
      space_key: [1, 2, 5].includes(index) ? "QA" : "OPS",
    })),
    filter: "active",
    historyPage: 1,
    checked: new Set(),
    $: id => fields[id],
  });
  vm.runInContext(["heading", "canApprove", "visibleOps", "checkedIds"].map(functionSource).join("\n"), state);
  return { state, fields };
}

test("the complete embedded script compiles", () => {
  new vm.Script(script);
});

function element(tag, className = "", textContent = "") {
  return {
    tag, className, textContent, children: [], dataset: {}, attributes: {},
    appendChild(node) { this.children.push(node); },
    replaceChildren() { this.children.length = 0; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener() {},
  };
}

function changesPanel(kind, preview) {
  const panel = element("section");
  const state = vm.createContext({ $: () => panel, tab: "diff", panelKey: "", el: element });
  vm.runInContext(functionSource("buildPanel"), state);
  state.buildPanel({ action: kind === "update" ? "update_page_section" : "create_page", kind, preview });
  return panel.children.at(-1);
}

test("unified diffs render full rows and distinguish content from version headers", () => {
  const lines = ["--- v7", "+++ v8", "@@ -1,3 +1,4 @@", " # 标题", "----", "++++ 示例", "+新增说明", " 原样保留"];
  const preview = lines.join("\n");
  const diff = changesPanel("update", preview);

  assert.equal(diff.tag, "pre");
  assert.equal(diff.className, "diff-view");
  assert.deepEqual(diff.children.map(row => row.className), [
    "diff-line diff-meta", "diff-line diff-meta", "diff-line diff-hunk", "diff-line",
    "diff-line diff-remove", "diff-line diff-add", "diff-line diff-add", "diff-line",
  ]);
  assert.equal(diff.children.map(row => row.textContent).join(""), preview);
});

test("headerless updates keep their markers and new pages show the original Markdown", () => {
  const preview = "--- old\n+++ new\n+";
  assert.deepEqual(changesPanel("update", preview).children.map(row => row.className), [
    "diff-line diff-remove", "diff-line diff-add", "diff-line diff-add",
  ]);
  const markdown = changesPanel("create", preview);
  assert.equal(markdown.textContent, preview);
  assert.equal(markdown.children.length, 0);
});

test("queue cards show the operation ID for submissions with the same title", () => {
  const { state } = context();
  Object.assign(state, {
    el: element, selected: null, locked: () => false,
    ACTIONS: { update_page: "整页更新" }, STATUSES: { pending: "待审批" },
  });
  vm.runInContext(functionSource("card"), state);

  for (const id of ["a4c2eb7f", "31b8dd69"]) {
    const submission = { id, title: "设备接入", action: "update_page", status: "pending", page_id: "42" };
    const [checkbox, button] = state.card(submission).children;
    const metadata = button.children.find(node => node.className === "card-meta");
    assert.equal(metadata.textContent, `页面 42 · 操作 ID ${id}`);
    assert.match(checkbox.children[0].attributes["aria-label"], new RegExp(`操作 ID ${id}$`));
  }
});

test("expanded result details use the operation status and a matching label", () => {
  const head = element("header");
  head.querySelector = () => null;
  const { state } = context();
  Object.assign(state, {
    $: () => head, el: element, locationBlock: () => element("div"), sourceBlock: () => null,
    ACTIONS: { update_page: "整页更新" },
    STATUSES: { succeeded: "已成功", failed: "失败", indeterminate: "结果不明", executing: "写入中", rejected: "已拒绝" },
  });
  vm.runInContext(["renderHead", "describe"].map(functionSource).join("\n"), state);

  const cases = [
    { status: "succeeded", result: { id: "31", version: 2 }, error: null, open: false },
    { status: "failed", result: { failed_attachment: "sample.png", attachment_upload_retries: { "sample.png": 2 } }, error: "连接超时", open: true },
    { status: "indeterminate", result: { id: "31", version: 1 }, error: "响应超时", open: true },
    { status: "executing", result: { id: "31", version: 1 }, error: null, open: false },
    { status: "rejected", result: { rejection_reason: "请补充 <测试报告>。" }, error: null, open: true },
  ];
  for (const { status, result, error, open } of cases) {
    state.renderHead({ id: "a4c2eb7f", title: "设备接入", action: "update_page", status, result, error });
    const details = head.children.at(-1);
    assert.equal(details.className, `metadata result-details status-${status}`);
    assert.equal(details.open, open);
    assert.equal(details.children[0].textContent, error ? "执行结果与错误详情" : status === "rejected" ? "拒绝详情" : "执行结果");
    assert.match(details.children[1].textContent, new RegExp(state.STATUSES[status]));
    if (status === "failed") assert.match(details.children[1].textContent, /上传失败 · sample\.png\n附件重试 · sample\.png · 2 次/);
  }
  assert.equal(head.children.at(-1).children[1].textContent, "状态 · 已拒绝\n拒绝原因 · 请补充 <测试报告>。");
});

test("status filters cover active, successful, attention and rejected operations", () => {
  const { state } = context();
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-0", "op-1", "op-2"]);
  state.filter = "attention";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-4", "op-5"]);
  state.filter = "succeeded";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-3"]);
  state.filter = "rejected";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-6"]);
});

test("space and case-insensitive search filters compose", () => {
  const { state, fields } = context();
  state.filter = "all";
  fields["space-filter"].value = "QA";
  fields.search.value = "OP-1";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-1"]);
  fields.search.value = "设备";
  assert.equal(state.visibleOps().length, 0);
  fields["space-filter"].value = "";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-0"]);
});

test("checked operations keep queue order and respect approval and rejection eligibility", () => {
  const { state, fields } = context();
  state.checked = new Set(["op-1", "op-0", "op-4", "op-5"]);
  fields["space-filter"].value = "QA";
  assert.deepEqual(Array.from(state.checkedIds("approve")), ["op-0", "op-1"]);
  assert.deepEqual(Array.from(state.checkedIds("reject")), ["op-0"]);
});

test("more than 200 operations are rejected before opening a confirmation", () => {
  const { state } = context();
  state.ops = Array.from({ length: 201 }, (_, index) => ({ id: "op-" + index, status: "pending" }));
  state.locked = () => false;
  state.confirmIds = [];
  const messages = [];
  state.notice = (message, error) => messages.push({ message, error });
  state.$ = () => assert.fail("Oversized batches must stop before rendering a dialog");
  vm.runInContext(functionSource("confirmAction"), state);
  state.confirmAction("approve", state.ops.map(op => op.id));
  assert.equal(messages.length, 1);
  assert.equal(messages[0].error, true);
  assert.match(messages[0].message, /200/);
});

test("approval progress stays open until the request succeeds or fails", async () => {
  for (const requestFails of [false, true]) {
    const { state } = context();
    const progress = { open: false, showModal() { this.open = true; }, close() { this.open = false; } };
    const nodes = { "approval-progress": progress, "approval-progress-message": {}, notice: { textContent: "上次审批结果" } };
    const requests = [];
    let completeRequest;
    const response = new Promise((resolve, reject) => {
      completeRequest = requestFails ? () => reject(new Error("连接中断")) : () => resolve({
        executed: [{ operation_id: "op-0", status: "succeeded" }],
      });
    });
    Object.assign(state, {
      $: id => nodes[id], busy: false, busyLabel: "", expired: false, APPROVE_PATH: "/api/approve",
      api(path, body) { requests.push({ path, body }); return response; },
      render() {}, refresh: () => Promise.resolve(),
    });
    vm.runInContext(["locked", "notice", "act"].map(functionSource).join("\n"), state);

    const completed = state.act("approve", ["op-0"]);
    assert.equal(progress.open, true);
    assert.match(nodes["approval-progress-message"].textContent, /写入 1 条/);
    assert.equal(nodes.notice.textContent, "");
    state.act("approve", ["op-0"]);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].path, "/api/approve");

    completeRequest();
    await completed;
    assert.equal(progress.open, false);
    assert.equal(state.locked(), false);
    assert.match(nodes.notice.textContent, requestFails ? /请求失败/ : /成功 1 条/);
  }
});

function stateResponse(operations = []) {
  return {
    operations, totals: { active: 0, succeeded: 0, attention: 0 },
    total: operations.length, spaces: [], history: { page: 1, pages: 1 },
  };
}

function refreshContext() {
  const indicator = { dataset: { state: "checking" }, textContent: "检查会话…" };
  const { state, fields } = context();
  const nodes = { ...fields, "session-state": indicator, "sync-state": {} };
  Object.assign(state, {
    $: id => nodes[id], refreshing: null, refreshingPath: "", loadedPath: "", expired: false, selected: null,
    STATE_PATH: "/api/state", URLSearchParams, api: () => Promise.resolve(stateResponse()),
    renderSpaces() {}, render() {}, selectVisible() {},
  });
  vm.runInContext(["setSessionState", "statePath", "refresh"].map(functionSource).join("\n"), state);
  return { state, nodes, indicator };
}

test("queue refresh updates the session light and recovers from a read failure", async () => {
  const { state, nodes, indicator } = refreshContext();

  await state.refresh();
  assert.equal(indicator.dataset.state, "valid");
  assert.equal(indicator.textContent, "会话有效");
  assert.match(nodes["sync-state"].textContent, /^更新于 /);

  state.api = () => Promise.reject(new Error("temporarily offline"));
  await assert.rejects(state.refresh(), /temporarily offline/);
  assert.equal(indicator.dataset.state, "unavailable");
  assert.equal(indicator.textContent, "刷新失败");
  assert.match(indicator.title, /5 秒后重试/);
  assert.equal(state.expired, false);

  state.api = () => Promise.resolve(stateResponse());
  await state.refresh();
  assert.equal(indicator.dataset.state, "valid");
  assert.equal(indicator.title, "");
});

test("a slow previous history response cannot replace the selected status view", async () => {
  const { state } = refreshContext();
  const requests = [];
  state.api = path => new Promise(resolve => requests.push({ path, resolve }));
  state.filter = "succeeded";
  const succeeded = state.refresh();
  state.filter = "attention";
  const attention = state.refresh();
  assert.match(requests[0].path, /history=succeeded/);
  assert.match(requests[1].path, /history=attention/);
  const failedOperation = { id: "failed", status: "failed" };
  requests[1].resolve(stateResponse([failedOperation]));
  await attention;
  requests[0].resolve(stateResponse([{ id: "succeeded", status: "succeeded" }]));
  await succeeded;
  assert.deepEqual(state.ops, [failedOperation]);
});

test("while history loads, a pending operation cannot remain selected under succeeded", () => {
  const { state, nodes } = refreshContext();
  nodes.list = { scrollTop: 80 };
  state.selected = "op-0";
  state.loadedPath = "/api/state";
  state.filter = "succeeded";
  state.refresh = () => new Promise(() => {});
  state.loadLocation = () => {};
  vm.runInContext(["select", "selectVisible", "changeFilter"].map(functionSource).join("\n"), state);
  state.changeFilter();
  assert.equal(state.selected, "op-3");
  assert.equal(nodes.list.scrollTop, 0);
});

test("session expiry closes confirmation, stops polling, and locks actions", () => {
  const { state } = context();
  const dialog = { open: true, close() { this.open = false; } };
  const progress = { open: true, close() { this.open = false; } };
  const indicator = { dataset: { state: "valid" } };
  const nodes = { notice: {}, "session-state": indicator, "confirm-dialog": dialog, "approval-progress": progress };
  let clearedTimer;
  let renderCount = 0;
  state.$ = id => nodes[id];
  state.busy = false;
  state.expired = false;
  state.timer = 123;
  state.clearInterval = timer => { clearedTimer = timer; };
  state.render = () => { renderCount += 1; };
  vm.runInContext(["notice", "setSessionState", "locked", "stop"].map(functionSource).join("\n"), state);
  state.stop();
  assert.equal(state.locked(), true);
  assert.equal(dialog.open, false);
  assert.equal(progress.open, false);
  assert.equal(clearedTimer, 123);
  assert.equal(renderCount, 1);
  assert.match(nodes.notice.textContent, /会话失效/);
  assert.equal(indicator.dataset.state, "expired");
  assert.equal(indicator.textContent, "会话失效");
});
