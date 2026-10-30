/* 后台任务坞：任务跑着而你没在看它时，会话页左下角要浮出来并说清有几个；
   展开能列出每条并点回去。这里把 core.js 的三个函数原样抽出来在桩 DOM 上跑，
   验的是真实实现，不是复述一遍逻辑。

   坞挂在 body 下，是唯一能盖在所有页面上的浮层——所以它只该在会话页出现，
   切到仪表盘/资源/设置时收起，切回来再出现，免得挡住别的页面。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createContext, runInContext } = require("node:vm");

const SRC = path.join(__dirname, "../src/spiritscout/web/static/js/core.js");
const src = fs.readFileSync(SRC, "utf8");

function pick(startMark, endMark) {
  const start = src.indexOf(startMark);
  assert.ok(start >= 0, `core.js 里找不到 ${startMark}`);
  const end = src.indexOf(endMark, start);
  assert.ok(end > start, `core.js 里找不到 ${endMark}`);
  return src.slice(start, end);
}

/* 桩 DOM：只需 hidden / innerHTML / classList / onclick / querySelectorAll。
   querySelectorAll(".dock-row") 按 innerHTML 造行元素并缓存——真实 DOM 里
   同一个节点会被反复取到，renderTaskDock 绑上去的 onclick 得能被再取出来，
   所以不能每次都新建。 */
function makeEl(id) {
  const classes = new Set();
  let html = "";
  let rowsFor = null;
  let rows = [];
  const el = {
    id,
    hidden: false,
    textContent: "",
    dataset: {},
    classList: {
      toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    setAttribute(name, value) { el[name] = value; },
    getAttribute(name) { return el[name]; },
    querySelectorAll(sel) {
      if (sel !== ".dock-row") return [];
      if (rowsFor !== html) {
        const ids = [...html.matchAll(/data-id="([^"]+)"/g)].map(m => m[1]);
        rows = ids.map(rowId => ({dataset: {id: rowId}, onclick: null}));
        rowsFor = html;
      }
      return rows;
    },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return html; },
    set(v) { html = String(v); },
  });
  return el;
}

function build() {
  const els = new Map();
  const get = id => {
    if (!els.has(id)) els.set(id, makeEl(id));
    return els.get(id);
  };
  const opened = [];
  const sandbox = {
    els, get, opened,
    TERMINAL: new Set(["completed", "failed", "stopped", "interrupted"]),
    STATUS_CN: {created: "排队中", running: "运行中", completed: "已完成",
                failed: "失败", stopped: "已停止", interrupted: "已中断"},
    S: {view: "home", cur: null, sessions: []},
    $: sel => (typeof sel === "string" && sel.startsWith("#") ? get(sel.slice(1)) : null),
    esc: v => String(v == null ? "" : v),
    openSession: id => opened.push(id),
  };
  sandbox.window = sandbox;
  const ctx = createContext(sandbox);
  runInContext(
    pick("function backgroundTasks()", "/* 重命名：就地编辑") +
      "\nthis.backgroundTasks = backgroundTasks;" +
      "this.renderTaskDock = renderTaskDock;" +
      "this.initTaskDock = initTaskDock;",
    ctx,
  );
  return {ctx, get, opened, S: sandbox.S};
}

function session(id, status, extra = {}) {
  return {session_id: id, status, title: `任务 ${id}`, target: "example.com", ...extra};
}

/* ------------------------------------------------------------ 用例 */

{
  const {ctx, get, S} = build();
  S.sessions = [];
  ctx.renderTaskDock();
  assert.equal(get("task-dock").hidden, true, "没有任务时坞要收起来");
  console.log("  空列表 → 隐藏: ok");
}

{
  const {ctx, get, S} = build();
  S.sessions = [session("s-1", "running")];
  S.view = "session";
  S.cur = "s-1";
  ctx.renderTaskDock();
  assert.equal(get("task-dock").hidden, true,
    "正在看的那一条不算「后台」，不该弹坞");
  console.log("  正在看的任务 → 不弹: ok");
}

{
  const {ctx, get, S} = build();
  S.sessions = [session("s-1", "running"), session("s-2", "completed")];
  S.view = "session";
  S.cur = null;
  ctx.renderTaskDock();
  const dock = get("task-dock");
  assert.equal(dock.hidden, false, "别处有任务在跑就该冒出来");
  assert.equal(get("dock-count").textContent, "1 个任务在后台运行",
    "已完成的会话不该算进去");
  console.log("  后台单任务 → 计数正确: ok");
}

{
  const {ctx, get, S} = build();
  S.sessions = [session("s-1", "running"), session("s-2", "created")];
  S.view = "session";
  S.cur = "s-1";   // 正在看 s-1，s-2 还在排队
  ctx.renderTaskDock();
  assert.equal(get("dock-count").textContent, "1 个任务在后台（0 个运行中）",
    "排队中的也要报，但要说清不是运行中");
  console.log("  排队中的任务 → 文案区分: ok");
}

{
  const {ctx, get, S} = build();
  S.sessions = [session("s-1", "running"), session("s-2", "running")];
  S.view = "session";
  ctx.renderTaskDock();
  assert.equal(get("dock-count").textContent, "2 个任务在后台运行");
  assert.ok(get("dock-body").innerHTML.includes("s-1"), "展开区要列出每一条");
  assert.ok(get("dock-body").innerHTML.includes("s-2"));
  console.log("  多个任务 → 全列出来: ok");
}

{
  const {ctx, get, S} = build();
  const dock = get("task-dock"), body = get("dock-body");
  ctx.initTaskDock();
  S.sessions = [session("s-1", "running")];
  S.view = "session";
  ctx.renderTaskDock();
  assert.equal(body.hidden, true, "默认收起");
  get("dock-toggle").onclick();
  assert.equal(body.hidden, false, "点一下展开");
  assert.equal(dock.classList.contains("open"), true);
  get("dock-toggle").onclick();
  assert.equal(body.hidden, true, "再点一下收起");
  console.log("  展开 / 收起: ok");
}

{
  const {ctx, get, S, opened} = build();
  ctx.initTaskDock();
  S.sessions = [session("s-1", "running")];
  S.view = "session";
  ctx.renderTaskDock();
  get("dock-toggle").onclick();
  const rows = get("dock-body").querySelectorAll(".dock-row");
  assert.equal(rows.length, 1, "渲染后应有一行");
  rows[0].onclick();
  assert.deepEqual(opened, ["s-1"], "点行要切到那个会话");
  console.log("  点行 → 跳转: ok");
}

{
  const {ctx, get, S} = build();
  S.sessions = [session("s-1", "running")];
  S.view = "session";
  ctx.renderTaskDock();
  assert.equal(get("task-dock").hidden, false);
  S.sessions = [session("s-1", "completed")];
  ctx.renderTaskDock();
  assert.equal(get("task-dock").hidden, true, "全部结束 → 自动收起");
  console.log("  任务收尾 → 自动隐藏: ok");
}

{
  /* 坞挂在 body 下，能盖在所有页面上。它回答的是「会话这边还有谁在跑」，
     不是全局通知——切到别的页面就得让开位置。 */
  const {ctx, get, S} = build();
  S.sessions = [session("s-1", "running")];
  S.view = "session";
  ctx.renderTaskDock();
  assert.equal(get("task-dock").hidden, false, "会话页该显示");
  for (const page of ["home", "dash", "settings", "projects", "exp"]) {
    S.view = page;
    ctx.renderTaskDock();
    assert.equal(get("task-dock").hidden, true, `切到 ${page} 页要收起`);
  }
  S.view = "session";
  ctx.renderTaskDock();
  assert.equal(get("task-dock").hidden, false, "切回会话页要重新出现");
  console.log("  切页收起 / 切回恢复: ok");
}

{
  /* 有提问等你回答的会话也不是终态，但提问本身不是「后台任务」——
     在别的页面上更不该冒出来挡路。 */
  const {ctx, get, S} = build();
  S.sessions = [session("s-1", "awaiting")];
  S.view = "dash";
  ctx.renderTaskDock();
  assert.equal(get("task-dock").hidden, true,
    "别的页面上即使有等待回答的会话也要收起");
  console.log("  等待回答的会话 → 别页不弹: ok");
}

console.log("task dock: ok");
