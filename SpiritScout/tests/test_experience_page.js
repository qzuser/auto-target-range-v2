"use strict";
// 经验提炼页：空态诚实指引、经验卡按在册会话回链、提炼失败原样留痕。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/experience.js"), "utf8");

// 最小 DOM 桩：同选择器返回同一子元素，innerHTML 写进桩里可断言
function fakeEl() {
  const children = new Map();
  return {
    dataset: {}, hidden: false, innerHTML: "", textContent: "",
    classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }},
    querySelector(sel) {
      if (!children.has(sel)) children.set(sel, fakeEl());
      return children.get(sel);
    },
    querySelectorAll() { return []; },
  };
}

const page = fakeEl();
const state = {fixture: null, opened: []};
const context = vm.createContext({
  $: sel => (sel === "#view-exp" ? page : fakeEl()),
  api: async () => state.fixture,
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])),
  S: {sessions: [{session_id: "sess-live"}, {session_id: "sess-other"}]},
  openSession: id => state.opened.push(id),
  refreshSessions: () => {},
  URLSearchParams,
  setTimeout: () => 0, clearTimeout: () => {},
  console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("ExperiencePage", context);
assert.equal(typeof Page.load, "function", "模块应导出 load");

const listEl = () => page.querySelector("[data-list]");
const histEl = () => page.querySelector("[data-hist]");
const moreEl = () => page.querySelector("[data-more]");

(async () => {
  // ① 空库：诚实说明经验从哪来、指向提炼记录，而不是一片空白
  state.fixture = {total: 0, items: [], has_more: false, tags: [],
                   sources: 0, last_ts: null, history: []};
  await Page.load();
  assert.match(listEl().innerHTML, /暂无经验/);
  assert.match(listEl().innerHTML, /提炼记录/);
  assert.equal(moreEl().hidden, true, "无更多数据时隐藏加载更多");

  // ② 有经验：在册会话回链可点，失联来源只展示不可点
  state.fixture = {
    total: 2, has_more: true, sources: 2, last_ts: 1760000000,
    tags: [{tag: "web", count: 2}, {tag: "越权", count: 1}],
    items: [
      {insight: "越权先比业务字段再下结论", context: "会员接口", tags: ["web", "越权"],
       source_session: "sess-live", source_title: "会员接口越权测试",
       source_model: "master", ts: 1760000000},
      {insight: "老会话的经验", context: "历史", tags: ["历史"],
       source_session: "sess-gone", source_title: "",
       source_model: "master", ts: 1759000000},
    ],
    history: [
      {session_id: "sess-gone", ts: "2026-10-17T10:00:00", result: "error",
       outcome: "failed", error: "ValueError: 模型输出为空"},
      {session_id: "sess-live", ts: "2026-10-17T09:00:00", result: "ok",
       outcome: "completed", insights: 2},
    ],
  };
  await Page.load();
  const cards = listEl().innerHTML;
  assert.match(cards, /data-open-session="sess-live"/);
  assert.doesNotMatch(cards, /data-open-session="sess-gone"/,
                      "失联会话不给点击回链");
  assert.match(cards, /会员接口越权测试/);
  assert.match(cards, /适用：会员接口/);
  // 提炼记录：失败徽标 + 原因原样呈现
  const hist = histEl().innerHTML;
  assert.match(hist, /失败/);
  assert.match(hist, /模型输出为空/);
  assert.match(hist, /data-open-session="sess-live"/);
  assert.doesNotMatch(hist, /data-open-session="sess-gone"/);
  assert.equal(moreEl().hidden, false, "还有下一页时展示加载更多");

  console.log("test_experience_page: 全部通过");
})().catch(err => { console.error(err); process.exit(1); });

// 会话页「经验」页签：本次产出、提炼记录、没有经验时的手动提炼。
const tabEl = fakeEl();
const tabState = {page: null, distill: null, calls: [], toasts: [], open: []};
const tabContext = vm.createContext({
  $: sel => (sel === "#tab-experience" ? tabEl : fakeEl()),
  api: async (url, options) => {
    const method = (options && options.method) || "GET";
    tabState.calls.push([url, method]);
    if (method === "POST") {
      if (tabState.distill instanceof Error) throw tabState.distill;
      return tabState.distill;
    }
    return tabState.page;
  },
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])),
  S: {cur: "sess-exp", sessions: [{session_id: "sess-exp"}]},
  toast: (msg, bad) => tabState.toasts.push([msg, !!bad]),
  armConfirm: (_el, run) => run(),
  URLSearchParams,
  setTimeout: () => 0, clearTimeout: () => {},
  console,
});
vm.runInContext(source, tabContext);
const Tab = vm.runInContext("SessionExperience", tabContext);
assert.equal(typeof Tab.load, "function", "页签模块应导出 load");
assert.equal(typeof Tab.distill, "function", "页签模块应导出 distill");

const listOf = () => tabEl.querySelector("[data-list]");
const histOf = () => tabEl.querySelector("[data-hist]");
const stateOf = () => tabEl.querySelector("[data-state]");
const distillBtn = () => tabEl.querySelector("[data-distill]");

(async () => {
  // ① 有经验：卡片带标签/适用场景/删除入口，状态行给条数
  tabState.page = {
    session_id: "sess-exp", total: 1,
    items: [{insight_id: "exp-1", insight: "缺少错误文案的登录接口也能枚举账号",
             context: "登录接口", tags: ["web", "枚举"], source_model: "master",
             ts: 1762000000}],
    history: [{ts: "2026-11-01T19:00:00", result: "ok", insights: 1,
               outcome: "completed", trigger: "manual"}],
    state: {status: "completed", can_distill: true, distilling: false, reason: ""},
    distill: {timeout: 45},
  };
  await Tab.load("sess-exp", true);
  assert.match(listOf().innerHTML, /枚举账号/);
  assert.match(listOf().innerHTML, /data-del="exp-1"/);
  assert.match(listOf().innerHTML, /适用：登录接口/);
  assert.match(stateOf().textContent, /本次产出 1 条经验/);
  assert.equal(distillBtn().disabled, false, "可以提炼时按钮可用");
  assert.match(histOf().innerHTML, /手动/, "提炼记录要区分手动还是自动");

  // ② 空会话但允许提炼：给按钮，并说清自动提炼什么时候跑
  tabState.page = {...tabState.page, total: 0, items: [], history: [],
                   state: {status: "completed", can_distill: true, distilling: false, reason: ""}};
  await Tab.load("sess-exp", true);
  assert.match(listOf().innerHTML, /这次还没有经验/);
  assert.match(listOf().innerHTML, /手动提炼/);
  assert.equal(distillBtn().disabled, false);

  // ③ 会话还在跑：按钮禁用，原因写在状态行
  tabState.page = {...tabState.page,
                   state: {status: "running", can_distill: false, distilling: false,
                           reason: "会话还在执行，等它收尾时自动提炼（也可以停了再手动提炼）"}};
  await Tab.load("sess-exp", true);
  assert.equal(distillBtn().disabled, true, "跑着的时候不给点");
  assert.match(stateOf().textContent, /还在执行/);

  // ④ 手动提炼：POST 一次，成功文案按服务端条数说话，列表/记录用返回的数据重画
  tabState.page = {...tabState.page,
                   state: {status: "completed", can_distill: true, distilling: false, reason: ""}};
  await Tab.load("sess-exp", true);
  tabState.calls = [];
  tabState.toasts = [];
  tabState.distill = {
    result: "ok", insights: 2, trigger: "manual", total: 2,
    items: [{insight_id: "exp-1", insight: "第一条", tags: ["web"], ts: 1762000000},
            {insight_id: "exp-2", insight: "第二条", tags: [], ts: 1762000100}],
    history: [{ts: "2026-11-01T20:10:00", result: "ok", insights: 2,
               outcome: "completed", trigger: "manual"}],
  };
  tabState.page = {...tabState.distill,
                   state: {status: "completed", can_distill: true, distilling: false, reason: ""}};
  await Tab.distill();
  assert.deepEqual(tabState.calls[0],
                   ["/api/sessions/sess-exp/experience/distill", "POST"]);
  assert.equal(tabState.toasts[0][0], "提炼完成，新增 2 条经验");
  assert.equal(tabState.toasts[0][1], false, "成功不该当错误提示");
  assert.match(listOf().innerHTML, /第二条/);
  assert.equal(distillBtn().disabled, false, "提炼完按钮要恢复");

  // ⑤ 提炼被拒（409）：错误原样提示，按钮回到可用状态
  tabState.toasts = [];
  tabState.distill = Object.assign(new Error("会话还在执行，等它收尾时自动提炼"), {status: 409});
  await Tab.distill();
  assert.equal(tabState.toasts[0][1], true, "失败要标红");
  assert.match(tabState.toasts[0][0], /还在执行/);
  assert.equal(distillBtn().textContent, "手动提炼", "失败后按钮文案要还原");

  console.log("test_session_experience_tab: 全部通过");
})().catch(err => { console.error(err); process.exit(1); });
