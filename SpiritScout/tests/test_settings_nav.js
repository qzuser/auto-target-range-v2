/* 设置界面的视图分流：进设置只点亮 #view-settings 与一个分类面板，
   其余顶层视图全部收起；从设置回主界面时反向收起设置，不留残留。
   这里把 core.js 的 show() 原样抽出来在桩 DOM 上跑，验的是真实实现。 */
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

/* ---------------------------------------------- 桩 DOM：只留 hidden / on */
function makeEl(id) {
  const classes = new Set();
  return {
    id,
    hidden: false,
    dataset: {},
    classList: {
      toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
  };
}

const els = new Map();
const get = id => {
  if (!els.has(id)) els.set(id, makeEl(id));
  return els.get(id);
};

const navButtons = ["home", "dash", "agents", "projects", "exp"].map(n => {
  const el = makeEl(`nav-${n}`);
  el.dataset.nav = n;
  els.set(el.id, el);
  return el;
});
const setButtons = ["models", "mcp", "skill", "about"].map(n => {
  const el = makeEl(`set-${n}`);
  el.dataset.set = n;
  els.set(el.id, el);
  return el;
});

const ctx = createContext({
  S: {},
  $: sel => (sel.startsWith("#") ? get(sel.slice(1)) : null),
  document: {
    querySelectorAll(sel) {
      if (sel === ".side > nav button") return navButtons;
      if (sel === ".set-nav button") return setButtons;
      return [];
    },
  },
  /* show() 会顺手触发各页的加载与收尾，这里只要它们别炸 */
  loadAgents() {}, loadModels() {}, renderDash() {},
  stopStreams() {}, SessionHistory: { cancel() {} },
  /* 视图切换后要重算「哪些算在后台」，坞本身另有 test_task_dock.js 专测 */
  renderTaskDock() {},
  console,
});
runInContext(
  pick("const VIEWS = {", '$("#btn-theme-inline")')
    + "\nglobalThis.show = show;",
  ctx);

const show = ctx.show;
/* 只看视图容器；按钮和侧栏那批元素没有 hidden 语义 */
const visible = () => [...els.values()]
  .filter(e => e.id.startsWith("view-") && !e.hidden)
  .map(e => e.id)
  .sort();

/* ------------------------------------------------------------ 设置分类 */
show("models");
assert.deepEqual(visible(), ["view-models", "view-settings"],
  "进设置的模型页：只该看见设置容器和模型面板");
assert.ok(get("btn-settings").classList.contains("on"), "设置入口要高亮");
assert.ok(get("set-models").classList.contains("on"), "当前分类要高亮");
assert.ok(navButtons.every(b => !b.classList.contains("on")),
  "在设置里时主侧栏四项都不高亮，避免误以为还在主界面");

show("mcp");
assert.deepEqual(visible(), ["view-mcp", "view-settings"],
  "切到 MCP：上一个面板要收起来，不能两个都显示");
assert.ok(get("set-mcp").classList.contains("on"));
assert.ok(!get("set-models").classList.contains("on"), "旧的分类高亮要摘掉");

show("about");
assert.deepEqual(visible(), ["view-about", "view-settings"]);

/* --------------------------------- 经验提炼是主界面的一项，不在设置里 */
show("exp");
assert.deepEqual(visible(), ["view-exp"],
  "经验提炼回主界面了：不该带出设置容器，也不必再点分类");
assert.ok(get("nav-exp").classList.contains("on"), "经验这一项要高亮");
assert.ok(!get("btn-settings").classList.contains("on"), "设置入口不该亮");
assert.ok(setButtons.every(b => !b.classList.contains("on")),
  "主界面视图不该点亮设置分类");

/* ---------------------------------------------------------- 回到主界面 */
show("dash");
assert.deepEqual(visible(), ["view-dash"], "回仪表盘：设置容器和面板都要收起");
assert.ok(!get("btn-settings").classList.contains("on"), "设置入口不再高亮");
assert.ok(get("nav-dash").classList.contains("on"), "仪表盘高亮");
assert.ok(setButtons.every(b => !b.classList.contains("on")),
  "离开设置后分类高亮要清掉");

show("projects");
assert.deepEqual(visible(), ["view-projects"]);

/* --------------------------------------------------- 记住上次看的分类 */
show("skill");
ctx.S.setTab = "skill";
show("home");
show("skill");
assert.deepEqual(visible(), ["view-settings", "view-skill"],
  "再次进设置要能回到上次的分类");

console.log("settings nav: ok");
