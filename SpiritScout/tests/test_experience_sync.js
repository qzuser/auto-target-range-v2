"use strict";
// 经验页的跨机器同步按钮：拉取（远端 → 本地）与提交（本地 → 仓库 → 远端）。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/experience.js"), "utf8");

function fakeEl() {
  const children = new Map();
  return {
    dataset: {}, hidden: false, innerHTML: "", textContent: "", disabled: false,
    classList: {toggle() {}, add() {}, remove() {}, contains() { return false; }},
    querySelector(sel) {
      if (!children.has(sel)) children.set(sel, fakeEl());
      return children.get(sel);
    },
    querySelectorAll() { return []; },
  };
}

const page = fakeEl();
const calls = [];
const toasts = [];
let confirmAnswer = true;

const context = vm.createContext({
  $: sel => (sel === "#view-exp" ? page : fakeEl()),
  api: async (url, opts) => {
    calls.push({url, method: (opts && opts.method) || "GET"});
    if (url.startsWith("/api/experience/sync/pull"))
      return {added: 7, skipped: 3, branch: "main", files: 2};
    if (url.startsWith("/api/experience/sync/push"))
      return {submitted: true, count: 42, branch: "main",
              file: "SpiritScout/data/experience/inbox/me-1.json"};
    return {total: 0, items: [], has_more: false, tags: [], sources: 0,
            last_ts: null, history: []};
  },
  esc: s => String(s ?? ""),
  S: {sessions: []},
  openSession: () => {},
  refreshSessions: () => {},
  toast: (text, bad) => toasts.push({text, bad: !!bad}),
  window: {confirm: () => confirmAnswer, localStorage: {getItem: () => null,
          setItem: () => {}}},
  URLSearchParams,
  setTimeout: () => 0, clearTimeout: () => {},
  console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("ExperiencePage", context);

(async () => {
  await Page.load();

  // ① 拉取：打的是 pull 接口，成功后给「新增几条」的实话并刷新列表
  await page.querySelector("[data-sync-pull]").onclick();
  const pull = calls.find(c => c.url === "/api/experience/sync/pull");
  assert.ok(pull, "点「拉取」应调用 /api/experience/sync/pull");
  assert.equal(pull.method, "POST");
  assert.match(toasts.at(-1).text, /新增 7 条/);
  assert.equal(toasts.at(-1).bad, false);

  // ② 提交：确认后打 push 接口，提示里带提交到哪个分支、哪个文件
  await page.querySelector("[data-sync-push]").onclick();
  const push = calls.find(c => c.url === "/api/experience/sync/push");
  assert.ok(push, "点「提交」应调用 /api/experience/sync/push");
  assert.equal(push.method, "POST");
  assert.match(toasts.at(-1).text, /提交 42 条经验/);
  assert.match(toasts.at(-1).text, /me-1\.json/);

  // ③ 取消确认：不发请求，也不弹提示
  confirmAnswer = false;
  const before = calls.filter(c => c.url === "/api/experience/sync/push").length;
  const toastsBefore = toasts.length;
  await page.querySelector("[data-sync-push]").onclick();
  assert.equal(calls.filter(c => c.url === "/api/experience/sync/push").length,
               before, "取消确认后不该发提交请求");
  assert.equal(toasts.length, toastsBefore);

  console.log("经验同步按钮测试通过");
})();
