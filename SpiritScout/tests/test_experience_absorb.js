"use strict";
// 合并（交给 AI）：按钮与二次提炼同级、两面板互斥、方案只出稿不落库、
// 采用后只 POST 分组、提示「原件全部保留」。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/experience.js"), "utf8");

function fakeEl() {
  const children = new Map();
  return {
    dataset: {}, hidden: false, innerHTML: "", textContent: "", checked: false,
    classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }},
    querySelector(sel) {
      if (!children.has(sel)) children.set(sel, fakeEl());
      return children.get(sel);
    },
    querySelectorAll() { return []; },
    setAttribute() {}, getAttribute() { return null; },
  };
}

const page = fakeEl();
const store = {};
const world = {calls: [], toasts: [], plan: null, apply: null, list: null};

const context = vm.createContext({
  $: sel => (sel === "#view-exp" ? page : fakeEl()),
  api: async (url, opt = {}) => {
    world.calls.push({url, opt});
    if (url.startsWith("/api/experience/absorb/preview")) {
      if (world.planError) throw Object.assign(new Error(world.planError), {status: 400});
      return world.plan;
    }
    if (url === "/api/experience/absorb/apply") {
      if (world.applyError) throw Object.assign(new Error(world.applyError), {status: 400});
      return world.apply;
    }
    if (url.startsWith("/api/experience?")) return world.list;
    return world.list;
  },
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])),
  S: {sessions: []},
  openSession: () => {},
  refreshSessions: () => {},
  armConfirm: (el, run) => run(),
  toast: (msg, bad) => world.toasts.push({msg, bad: !!bad}),
  URLSearchParams,
  setTimeout: () => 0, clearTimeout: () => {},
  window: {localStorage: {
    getItem: key => (key in store ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
  }},
  console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("ExperiencePage", context);
const panel = () => page.querySelector("[data-absorb-panel]");
const mergePanel = () => page.querySelector("[data-merge-panel]");

const item = (extra = {}) => ({
  insight_id: "exp-a", insight: "登录接口错误文案不一致说明存在用户名枚举",
  context: "登录", tags: ["web"], source_session: "", source_model: "master",
  ts: 1760000000, merged: false, merged_from: [], merged_into: "", ...extra,
});
const ONE = () => ({total: 2, items: [item(), item({insight_id: "exp-b"})],
                    has_more: false, tags: [], sources: 0, last_ts: 1760000000,
                    merged_total: 0, history: []});

(async () => {
  world.list = ONE();
  await Page.load();

  // ① 合并按钮存在，点开后展开自己的面板；与二次提炼互斥
  Page.toggleMerge();
  assert.equal(mergePanel().hidden, false, "二次提炼面板先打开");
  Page.toggleAbsorb();
  assert.equal(Page.state.absorbOn, true, "合并面板打开");
  assert.equal(Page.state.mergeOn, false, "两个面板不能同时开着");
  assert.equal(panel().hidden, false);
  assert.equal(mergePanel().hidden, true, "二次提炼面板要收起");
  assert.match(panel().innerHTML, /合并（不删任何经验）/);
  assert.match(panel().innerHTML, /原件全部保留/);

  // ② 勾选框在合并模式里也要出现
  assert.match(page.querySelector("[data-list]").innerHTML, /data-pick="exp-a"/);

  // ③ 交给 AI：只发 preview，仓库一个字不动
  world.calls = [];
  world.plan = {
    checked: 2, candidates: 1, note: "找到 1 处可以并入的地方",
    groups: [{target_id: "exp-b", target_insight: "目标原文", insight: "合并后的说法",
              context: "登录接口", sources: ["exp-a"], tags: ["web"]}],
  };
  await Page.planAbsorb(["exp-a"]);
  assert.equal(world.calls.filter(c => c.url === "/api/experience/absorb/apply").length,
    0, "出方案阶段不许落库");
  const post = world.calls.find(c => c.url.startsWith("/api/experience/absorb/preview"));
  assert.ok(post, "要走 absorb/preview");
  assert.equal(post.opt.method, "POST");
  assert.deepEqual(JSON.parse(post.opt.body), {ids: ["exp-a"]});
  assert.match(panel().innerHTML, /目标（现在）：目标原文/);
  assert.match(panel().innerHTML, /合并后的说法/);
  assert.match(panel().innerHTML, /采用这一处/);

  // ④ 采用：只把分组 POST 过去，提示写明原件保留
  world.calls = [];
  world.apply = {applied: 1, deleted: 0, groups: [{target_id: "exp-b", sources: ["exp-a"]}]};
  await Page.applyAbsorb(world.plan.groups);
  const apply = world.calls.find(c => c.url === "/api/experience/absorb/apply");
  assert.ok(apply, "要走 absorb/apply");
  const body = JSON.parse(apply.opt.body);
  assert.equal(body.groups.length, 1);
  assert.equal(body.groups[0].target_id, "exp-b");
  assert.match(world.toasts.at(-1).msg, /原件全部保留/);

  // ⑤ 空选择不发请求
  world.calls = [];
  await Page.planAbsorb([]);
  assert.equal(world.calls.length, 0);
  assert.match(world.toasts.at(-1).msg, /先勾选/);

  // ⑥ 模型说没得合并非错：如实展示，不落库
  world.plan = {checked: 1, candidates: 3, note: "没有可以并入同一条经验的内容",
                groups: []};
  world.calls = [];
  await Page.planAbsorb(["exp-a"]);
  assert.match(panel().innerHTML, /没有可以并入同一条经验的内容/);
  assert.equal(world.calls.filter(c => c.url === "/api/experience/absorb/apply").length, 0);

  // ⑦ 接口报错：toast 说清楚，面板不残留假方案
  world.planError = "没有配了 API Key 的渠道";
  await Page.planAbsorb(["exp-a"]);
  assert.match(world.toasts.at(-1).msg, /API Key/);
  assert.equal(world.toasts.at(-1).bad, true);
  world.planError = null;

  // ⑧ 关掉再打开：方案清空，不把上一轮的结果带过来
  Page.toggleAbsorb();
  Page.toggleAbsorb();
  assert.equal(Page.state.absorbPlan, null);
  assert.equal(Page.state.picks.size, 0);

  console.log("test_experience_absorb.js: 全部通过");
})().catch(err => { console.error(err); process.exit(1); });
