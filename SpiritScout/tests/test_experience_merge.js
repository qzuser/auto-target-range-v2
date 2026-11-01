"use strict";
// 二次提炼（合并压缩）：只能合并极度相似的，且原件不许消失、可还原。
// 这里把 experience.js 的 ExperiencePage 整段装进 vm 跑真实实现。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/experience.js"), "utf8");

function fakeEl() {
  const children = new Map();
  const el = {
    dataset: {}, hidden: false, innerHTML: "", textContent: "", checked: false,
    classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }},
    querySelector(sel) {
      if (!children.has(sel)) children.set(sel, fakeEl());
      return children.get(sel);
    },
    querySelectorAll() { return []; },
    setAttribute() {}, getAttribute() { return null; },
  };
  return el;
}

const page = fakeEl();
const world = {calls: [], toasts: [], list: null, groups: null, error: null,
               mergeResponse: null, restoreResponse: null};

const context = vm.createContext({
  $: sel => (sel === "#view-exp" ? page : fakeEl()),
  api: async (url, opt = {}) => {
    world.calls.push({url, opt});
    if (url.startsWith("/api/experience/merge/candidates")) return world.groups;
    if (url === "/api/experience/merge") {
      if (world.error) throw Object.assign(new Error(world.error), {status: 400});
      return world.mergeResponse;
    }
    if (url === "/api/experience/merge/restore") {
      if (world.error) throw new Error(world.error);
      return world.restoreResponse;
    }
    return world.list;
  },
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])),
  S: {sessions: [{session_id: "sess-live"}]},
  openSession: () => {},
  refreshSessions: () => {},
  armConfirm: (el, run) => run(),          // 第一次点击直接确认，好走通流程
  toast: (msg, bad) => world.toasts.push({msg, bad: !!bad}),
  URLSearchParams,
  setTimeout: () => 0, clearTimeout: () => {},
  console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("ExperiencePage", context);
const panel = () => page.querySelector("[data-merge-panel]");
const listEl = () => page.querySelector("[data-list]");
const lastCall = () => world.calls[world.calls.length - 1];

const item = (extra = {}) => ({
  insight_id: "exp-a", insight: "登录接口错误文案不一致说明存在用户名枚举",
  context: "登录", tags: ["web"], source_session: "sess-live",
  source_model: "master", ts: 1760000000, merged: false, merged_from: [],
  merged_into: "", ...extra,
});

(async () => {
  world.list = {total: 2, items: [item(), item({insight_id: "exp-b"})],
                has_more: false, tags: [], sources: 1, last_ts: 1760000000,
                merged_total: 3, history: []};
  await Page.load();

  // ① 有已合并条目时露出「显示已合并」入口
  assert.equal(page.querySelector("[data-merged-toggle]").hidden, false,
    "有已合并条目就该能切换查看");

  // ② 打开二次提炼：拉候选，并明确写出阈值与「原件不删」
  world.groups = {threshold: 0.85, count: 1, groups: [{
    ids: ["exp-a", "exp-b"], score: 0.94,
    items: [{insight_id: "exp-a", insight: "表述甲", tags: ["web"]},
            {insight_id: "exp-b", insight: "表述乙", tags: ["web"]}],
    preview: {insight: "合并后的说法"}, }]};
  Page.toggleMerge();
  await Page.loadGroups();
  assert.equal(panel().hidden, false, "面板要展开");
  assert.match(lastCall().url, /\/api\/experience\/merge\/candidates/);
  assert.match(lastCall().url, /threshold=0\.85/, "阈值随请求走，不写死在服务端");
  assert.match(panel().innerHTML, /极度相似/);
  assert.match(panel().innerHTML, /85%/);
  assert.match(panel().innerHTML, /原件不会删除/);
  assert.match(panel().innerHTML, /data-merge-ids="exp-a,exp-b"/);
  assert.match(panel().innerHTML, /相似度 94%/);
  assert.match(panel().innerHTML, /合并后：合并后的说法/);

  // ③ 合并一组：POST 带阈值，成功后刷新列表与候选
  world.mergeResponse = {merged_id: "exp-m", absorbed: ["exp-a", "exp-b"],
                         insight: "合并后的说法"};
  world.calls = [];
  await Page.applyMerge(["exp-a", "exp-b"]);
  const post = world.calls.find(c => c.url === "/api/experience/merge");
  assert.ok(post, "合并要发 POST");
  const body = JSON.parse(post.opt.body);
  assert.deepEqual(body.ids, ["exp-a", "exp-b"]);
  assert.equal(body.threshold, 0.85);
  assert.ok(world.calls.some(c => c.url.startsWith("/api/experience?")),
    "合并完要重载列表");
  assert.equal(world.toasts.at(-1).bad, false);

  // ④ 只选一条不算合并
  world.calls = [];
  await Page.applyMerge(["exp-a"]);
  assert.equal(world.calls.length, 0, "单条不发起合并");

  // ⑤ 服务端拒绝（不够相似）要原样告诉用户，不能假装成功
  world.error = "这几条不够相似（最低 0.62 < 阈值 0.85），为免丢掉有用信息，不合并";
  await Page.applyMerge(["exp-a", "exp-b"]);
  assert.equal(world.toasts.at(-1).bad, true);
  assert.match(world.toasts.at(-1).msg, /不够相似/);
  world.error = null;

  // ⑥ 已合并的原件：灰卡 + 「已合并」+ 还原按钮；合并产物标「二次提炼」
  world.list = {total: 3, has_more: false, tags: [], sources: 1, last_ts: 1760000000,
                merged_total: 2, history: [], items: [
    item({insight_id: "exp-m", insight: "合并后的说法", source_model: "merge",
          merged_from: ["exp-a", "exp-b"]}),
    item({insight_id: "exp-a", merged: true, merged_into: "exp-m"}),
  ]};
  await Page.load();
  const html = listEl().innerHTML;
  assert.match(html, /二次提炼 · 2 条/);
  assert.match(html, /已合并/);
  assert.match(html, /data-restore="exp-m"/, "被合并项要能还原");
  assert.match(html, /exp-card merged/, "已合并项样式要区分");

  // ⑦ 还原
  world.restoreResponse = {merged_id: "exp-m", restored: ["exp-a", "exp-b"]};
  world.calls = [];
  await Page.restoreMerge("exp-m");
  const restore = world.calls.find(c => c.url === "/api/experience/merge/restore");
  assert.ok(restore, "还原要发 POST");
  assert.equal(JSON.parse(restore.opt.body).merged_id, "exp-m");

  // ⑧ 勾选模式下卡片带勾选框；查看已合并时请求带 include_merged
  Page.state.mergeOn = false; Page.state.picks.clear(); Page.state.merged = false;
  Page.toggleMerge();
  assert.match(listEl().innerHTML, /data-pick="exp-m"/, "勾选模式给出勾选框");
  Page.toggleMerge();
  Page.state.merged = true;
  world.calls = [];
  await Page.load();
  assert.match(lastCall().url, /include_merged=true/);

  console.log("test_experience_merge.js: 全部通过");
})().catch(err => { console.error(err); process.exit(1); });
