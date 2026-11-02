"use strict";
// 二次提炼：相似度可自定义（默认 90%）、可全选、先提炼再确认保留，
// 确认后才入库并删除被提炼的原件。这里把 experience.js 整段装进 vm 跑真实实现。
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
const store = {};                       // 假 localStorage：验证阈值会被记住
const world = {calls: [], toasts: [], list: null, groups: null, error: null,
               previewResponse: null, mergeResponse: null, restoreResponse: null};

const context = vm.createContext({
  $: sel => (sel === "#view-exp" ? page : fakeEl()),
  api: async (url, opt = {}) => {
    world.calls.push({url, opt});
    if (url.startsWith("/api/experience/merge/candidates")) return world.groups;
    if (url === "/api/experience/merge/preview") {
      if (world.error) throw Object.assign(new Error(world.error), {status: 400});
      return world.previewResponse;
    }
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
  window: {localStorage: {
    getItem: key => (key in store ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
  }},
  console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("ExperiencePage", context);
const panel = () => page.querySelector("[data-merge-panel]");
const listEl = () => page.querySelector("[data-list]");
const lastCall = () => world.calls[world.calls.length - 1];
const posts = url => world.calls.filter(c => c.url === url);

const item = (extra = {}) => ({
  insight_id: "exp-a", insight: "登录接口错误文案不一致说明存在用户名枚举",
  context: "登录", tags: ["web"], source_session: "sess-live",
  source_model: "master", ts: 1760000000, merged: false, merged_from: [],
  merged_into: "", ...extra,
});

const GROUPS = {threshold: 0.9, count: 1, groups: [{
  ids: ["exp-a", "exp-b"], score: 0.94,
  items: [{insight_id: "exp-a", insight: "表述甲", tags: ["web"]},
          {insight_id: "exp-b", insight: "表述乙", tags: ["web"]}],
  preview: {insight: "合并后的说法"}}]};

const TWO = () => ({total: 2, items: [item(), item({insight_id: "exp-b"})],
                    has_more: false, tags: [], sources: 1, last_ts: 1760000000,
                    merged_total: 0, history: []});

(async () => {
  world.list = TWO();
  await Page.load();

  // ① 默认相似度 90%：候选查询直接带 0.9，页面上能看到这个数字
  assert.equal(Page.state.threshold, 90, "默认阈值 90%");
  world.groups = GROUPS;
  Page.toggleMerge();
  await Page.loadGroups();
  assert.equal(panel().hidden, false, "面板要展开");
  assert.match(lastCall().url, /\/api\/experience\/merge\/candidates/);
  assert.match(lastCall().url, /threshold=0\.9(&|$)/, "默认按 0.9 查询");
  assert.match(panel().innerHTML, /相似度\s*<input type="number" data-threshold/,
    "阈值是可改的输入框");
  assert.match(panel().innerHTML, /value="90"/);
  assert.match(panel().innerHTML, /默认 90%/);
  assert.match(panel().innerHTML, /≥ 90%/);
  assert.match(panel().innerHTML, /data-merge-ids="exp-a,exp-b"/);
  assert.match(panel().innerHTML, /提炼这 2 条/);
  assert.doesNotMatch(panel().innerHTML, /原件不会删除/,
    "旧口径的「原件不删」提示必须消失");

  // ② 改相似度：请求按新值走，并记住这次的设置
  world.calls = [];
  await Page.setThreshold(80);
  assert.match(lastCall().url, /threshold=0\.8(&|$)/);
  assert.equal(store["ss.exp.mergeThreshold"], "80", "阈值要记住，下次打开还是它");
  assert.equal(Page.state.threshold, 80);
  assert.match(panel().innerHTML, /value="80"/);
  // 越界值按边界收口，不让它把查询算飞
  await Page.setThreshold(500);
  assert.equal(Page.state.threshold, 100);
  await Page.setThreshold(1);
  assert.equal(Page.state.threshold, 50);
  await Page.setThreshold(90);

  // ③ 全选：一次勾上当前列表里所有可提炼的条目，再点一次全清
  Page.togglePickAll(true);
  assert.deepEqual([...Page.state.picks].sort(), ["exp-a", "exp-b"]);
  assert.match(panel().innerHTML, /全选（2 条可提炼）/);
  assert.match(panel().innerHTML, /已选 2 条/);
  Page.togglePickAll(false);
  assert.equal(Page.state.picks.size, 0);
  assert.match(panel().innerHTML, /已选 0 条/);

  // ④ 第一步：提炼只出稿子，绝不落库（不能碰 /api/experience/merge）
  world.previewResponse = {applied: false, absorbed: ["exp-a", "exp-b"], removed: [],
                           score: 0.94, insight: "合并后的说法", context: "登录接口",
                           tags: ["web"], merged_from: ["exp-a", "exp-b"]};
  world.calls = [];
  await Page.previewMerge(["exp-a", "exp-b"]);
  assert.equal(posts("/api/experience/merge").length, 0, "预览阶段不许动库");
  const pre = posts("/api/experience/merge/preview");
  assert.equal(pre.length, 1, "要走 preview 接口");
  const preBody = JSON.parse(pre[0].opt.body);
  assert.deepEqual(preBody.ids, ["exp-a", "exp-b"]);
  assert.equal(preBody.threshold, 0.9);
  assert.match(panel().innerHTML, /提炼结果（还没入库）/);
  assert.match(panel().innerHTML, /合并后的说法/);
  assert.match(panel().innerHTML, /保留并删除 2 条原件/);
  assert.match(panel().innerHTML, /data-preview-cancel>放弃/);

  // ⑤ 放弃：稿子清掉，库还是原样
  Page.discardPreview();
  assert.equal(Page.state.preview, null);
  assert.doesNotMatch(panel().innerHTML, /提炼结果（还没入库）/);
  assert.equal(posts("/api/experience/merge").length, 0);

  // ⑥ 确认保留：这一步才 POST /api/experience/merge（写结果 + 删原件）
  world.mergeResponse = {applied: true, merged_id: "exp-m", removed: ["exp-a", "exp-b"],
                         absorbed: ["exp-a", "exp-b"], insight: "合并后的说法"};
  await Page.previewMerge(["exp-a", "exp-b"]);
  world.calls = [];
  world.list = {total: 2, items: [item({insight_id: "exp-m", insight: "合并后的说法",
                                       source_model: "merge",
                                       merged_from: ["exp-a", "exp-b"]})],
                has_more: false, tags: [], sources: 1, last_ts: 1760000000,
                merged_total: 0, history: []};
  await Page.keepPreview();
  const commit = posts("/api/experience/merge");
  assert.equal(commit.length, 1, "确认保留才提交");
  assert.deepEqual(JSON.parse(commit[0].opt.body).ids, ["exp-a", "exp-b"]);
  assert.ok(world.calls.some(c => c.url.startsWith("/api/experience?")),
    "确认后要重载列表");
  assert.match(world.toasts.at(-1).msg, /已保留提炼结果/);
  assert.equal(world.toasts.at(-1).bad, false);
  assert.equal(Page.state.preview, null);
  assert.match(listEl().innerHTML, /二次提炼 · 2 条/);

  // ⑦ 只选一条不是提炼
  world.calls = [];
  await Page.previewMerge(["exp-a"]);
  assert.equal(world.calls.length, 0, "单条不发起请求");
  assert.equal(world.toasts.at(-1).bad, true);

  // ⑧ 服务端拒绝（不够相似）要原样告诉用户，不能假装成功
  world.error = "这几条不够相似（最低 0.62 < 阈值 0.90），为免丢掉有用信息，不合并";
  await Page.previewMerge(["exp-a", "exp-b"]);
  assert.equal(world.toasts.at(-1).bad, true);
  assert.match(world.toasts.at(-1).msg, /不够相似/);
  world.error = null;

  // ⑨ 旧口径的「已合并」原件仍可查看与还原
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
  assert.match(html, /data-restore="exp-m"/, "旧数据的合并项要能还原");
  assert.match(html, /exp-card merged/, "已合并项样式要区分");
  world.restoreResponse = {merged_id: "exp-m", restored: ["exp-a", "exp-b"]};
  world.calls = [];
  await Page.restoreMerge("exp-m");
  assert.equal(posts("/api/experience/merge/restore").length, 1, "还原要发 POST");

  // ⑩ 勾选模式下卡片带勾选框；查看已合并时请求带 include_merged
  Page.state.mergeOn = false; Page.state.picks.clear(); Page.state.merged = false;
  Page.toggleMerge();
  assert.match(listEl().innerHTML, /data-pick="exp-m"/, "勾选模式给出勾选框");
  Page.toggleMerge();
  Page.state.merged = true;
  world.calls = [];
  await Page.load();
  assert.match(lastCall().url, /include_merged=true/);

  // ⑪ 一次超过 20 条：不发请求、直接提示分批（后端也是这个上限）
  const many = Array.from({length: 21}, (_, i) => `exp-${i}`);
  world.calls = [];
  await Page.previewMerge(many);
  assert.equal(world.calls.length, 0, "超上限不发请求");
  assert.match(world.toasts.at(-1).msg, /一次最多/);
  Page.state.mergeOn = true;
  Page.state.items = many.map(id => item({insight_id: id}));
  Page.renderMergePanel();
  assert.match(panel().innerHTML, /全选（21 条可提炼，一次最多 20 条）/);
  Page.togglePickAll(true);
  assert.equal(Page.state.picks.size, 21, "全选照勾，按钮自己禁用");
  assert.match(panel().innerHTML, /请分批/);
  Page.togglePickAll(false);

  console.log("test_experience_merge.js: 全部通过");
})().catch(err => { console.error(err); process.exit(1); });
