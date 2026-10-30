"use strict";
// 破坏性操作的确认：轻量两段式（armConfirm）与模态确认（confirmDialog）各管一段。
// 模型/供应商删除走模态 —— 「不够明显」的反馈就是换按钮文字挡不住手滑。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const jsPath = (name) => path.join(__dirname, "../src/spiritscout/web/static/js", name);
const coreSource = fs.readFileSync(jsPath("core.js"), "utf8");
const consoleSource = fs.readFileSync(jsPath("console.js"), "utf8");
const viewsCss = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/css/views.css"), "utf8");

/* ---------------- 一、armConfirm：轻量两段式（会话/经验删除在用） ---------------- */

const armStart = coreSource.indexOf("function armConfirm");
const armEnd = coreSource.indexOf("function armDelete");
assert.ok(armStart > 0 && armEnd > armStart, "core.js 里找不到 armConfirm");
const armSnippet = coreSource.slice(armStart, armEnd);

function loadArm() {
  const timers = [];
  const context = vm.createContext({
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    Promise,
  });
  vm.runInContext(armSnippet, context);
  return { context, timers };
}

function makeButton(html) {
  const classes = new Set();
  return {
    dataset: {},
    disabled: false,
    innerHTML: html,
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
    },
    classes,
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

/* ---------------- 二、confirmDialog：真跑一遍，用最小 DOM 桩 ------------- */

const dialogStart = coreSource.indexOf("function confirmDialog");
/* confirmDialog 排在 armDelete 之后，下一个东西是「自定义下拉」那段大注释 */
const dialogEnd = coreSource.indexOf("/* ================= 自定义下拉", dialogStart);
assert.ok(dialogStart > 0 && dialogEnd > dialogStart, "core.js 里找不到 confirmDialog");
const dialogSnippet = coreSource.slice(dialogStart, dialogEnd);

/* 只实现 confirmDialog 真正用到的那几个 DOM 面：createElement/append/innerHTML/
   querySelector/close/remove/showModal/focus/classList 与事件注册。 */
function makeDialogHarness() {
  const handlers = {};
  const nodes = {};
  /* querySelector 要复用同一个桩节点：confirmDialog 先给 onclick 赋值、后面
     再 focus()，每次新建节点会把前面挂的 onclick 丢掉。 */
  const node = (name) => {
    if (!nodes[name]) {
      nodes[name] = {
        onclick: null,
        focused: false,
        focus() { nodes[name].focused = true; },
      };
    }
    return nodes[name];
  };
  const dlg = {
    className: "",
    innerHTML: "",
    closed: false,
    removed: false,
    focusedEl: null,
    showModal() { dlg.opened = true; },
    opened: false,
    close() { dlg.closed = true; },
    remove() { dlg.removed = true; },
    addEventListener: (type, fn) => { handlers[type] = fn; },
    querySelector(selector) { return node(selector); },
    __handlers: handlers,
    __nodes: nodes,
  };
  let created = 0;
  const document = {
    createElement: () => { created += 1; return dlg; },
    body: { append: () => { dlg.appended = true; } },
  };
  return { dlg, document, handlers, nodes, created: () => created };
}

function loadConfirm() {
  const harness = makeDialogHarness();
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g,
    (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
  const context = vm.createContext({ document: harness.document, esc, Promise });
  vm.runInContext(dialogSnippet, context);
  return { context, ...harness };
}

async function main() {
  // --- armConfirm：首击只上膛，不执行 ---
  {
    const { context } = loadArm();
    const button = makeButton("删除");
    let called = 0;
    context.__btn = button;
    context.__run = () => { called += 1; };
    vm.runInContext("armConfirm(__btn, __run)", context);
    await tick();
    assert.equal(called, 0, "首击不能直接执行删除");
    assert.equal(button.dataset.armed, "1", "首击应进入待确认状态");
    assert.equal(button.innerHTML, "删除?", "首击应把文字换成「删除?」");
  }

  // --- armConfirm：第二击才真的执行 ---
  {
    const { context } = loadArm();
    const button = makeButton("删除");
    let called = 0;
    context.__btn = button;
    context.__run = () => { called += 1; };
    vm.runInContext("armConfirm(__btn, __run)", context);
    vm.runInContext("armConfirm(__btn, __run)", context);
    await tick();
    assert.equal(called, 1, "第二次点击才执行删除");
  }

  // --- armConfirm：图标按钮撤销后图标还在 ---
  {
    const { context, timers } = loadArm();
    const icon = '<svg viewBox="0 0 16 16"><path d="M3 3h10"/></svg>';
    const button = makeButton(icon);
    context.__btn = button;
    context.__run = () => {};
    vm.runInContext("armConfirm(__btn, __run)", context);
    timers[0]();
    assert.equal(button.innerHTML, icon, "图标按钮撤销后要恢复成完整图标，不能变空白");
  }

  // --- confirmDialog：确认给 true，弹窗开过且收尾干净 ---
  {
    const { context, dlg, nodes } = loadConfirm();
    context.__title = "删除这个模型？";
    context.__target = "lmstudio-community/Bonsai-27B-GGUF";
    const pending = vm.runInContext(
      "confirmDialog({title: __title, body: '会牵连 Agent', target: __target, okText: '删除模型'})",
      context);
    assert.equal(dlg.opened, true, "弹窗应以模态方式打开");
    assert.equal(dlg.appended, true, "弹窗应挂到 body 上");
    assert.ok(dlg.innerHTML.includes("删除这个模型？"), "标题应写进弹窗");
    assert.ok(dlg.innerHTML.includes("lmstudio-community/Bonsai-27B-GGUF"),
      "被删对象应单独列出，让人看清删的是哪一个");
    assert.ok(dlg.innerHTML.includes("删除模型"), "确认键文案应可定制");
    assert.equal(nodes["[data-ok]"].focused, true, "焦点应落在确认键上");
    nodes["[data-ok]"].onclick();
    assert.equal(await pending, true, "点确认应返回 true");
    assert.equal(dlg.closed, true, "收尾要 close");
    assert.equal(dlg.removed, true, "收尾要把节点摘掉");
  }

  // --- confirmDialog：取消 / Esc / 点遮罩都返回 false 且只结算一次 ---
  for (const [label, fire] of [
    ["取消", (h) => h.nodes["[data-cancel]"].onclick()],
    ["Esc", (h) => h.handlers.cancel({ preventDefault() {} })],
    ["点遮罩", (h) => h.handlers.click({ target: h.dlg })],
  ]) {
    const harness = loadConfirm();
    const pending = vm.runInContext("confirmDialog({title: 't', okText: '删除'})", harness.context);
    fire(harness);
    assert.equal(await pending, false, `${label} 应返回 false（不删除）`);
    assert.equal(harness.dlg.removed, true, `${label} 之后节点要摘掉`);
  }

  // --- confirmDialog：Esc 要先 preventDefault，否则 close 会被触发两次 ---
  {
    const { context, handlers } = loadConfirm();
    let prevented = 0;
    vm.runInContext("confirmDialog({title: 't'})", context);
    handlers.cancel({ preventDefault() { prevented += 1; } });
    assert.equal(prevented, 1, "cancel 事件应 preventDefault，避免原生关闭重入");
  }

  // --- 接线：模型与供应商删除都改走模态确认 ---
  assert.ok(/window\.modelDel = async model =>/.test(consoleSource),
    "modelDel 应为 async 并接受模型名");
  assert.ok(/window\.providerDel = async name =>/.test(consoleSource),
    "providerDel 应为 async 并接受供应商名");
  assert.equal((consoleSource.match(/await confirmDialog\(/g) || []).length, 2,
    "模型和供应商删除都应 await confirmDialog");
  assert.equal((consoleSource.match(/if \(!ok\) return;/g) || []).length, 2,
    "两处都应在用户取消时直接返回，不发删除请求");
  assert.ok(consoleSource.includes("编队页指派给它的 Agent 会一起失效"),
    "模型删除应说明连带影响");
  assert.ok(consoleSource.includes("个模型</b>"),
    "供应商删除应报出会牵连多少个模型");

  // --- 样式：确认框有自己的尺寸与强调色 ---
  assert.ok(viewsCss.includes(".confirm-dlg {"), "缺少 .confirm-dlg 样式");
  assert.ok(viewsCss.includes(".confirm-dlg .cf-target"), "缺少被删对象的高亮块样式");
  assert.ok(/\.confirm-dlg \.cf-body b \{[^}]*var\(--bad\)/.test(viewsCss),
    "连带影响应使用危险色强调");

  console.log("delete confirm: passed");
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
