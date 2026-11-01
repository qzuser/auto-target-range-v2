"use strict";
// 用量页：按模型出账、空态诚实、期间切换会重新拉数。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/usage.js"), "utf8");

function fakeEl() {
  const children = new Map();
  return {
    dataset: {}, hidden: false, innerHTML: "", textContent: "",
    querySelector(sel) {
      if (!children.has(sel)) children.set(sel, fakeEl());
      return children.get(sel);
    },
    querySelectorAll() { return []; },
  };
}

const page = fakeEl();
const state = { payload: null, urls: [] };
const context = vm.createContext({
  $: sel => (sel === "#view-usage" ? page : fakeEl()),
  api: async url => { state.urls.push(url); return state.payload; },
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])),
  encodeURIComponent,
  console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("UsagePage", context);
assert.equal(typeof Page.load, "function", "模块应导出 load");
assert.equal(typeof Page.open, "function", "模块应导出 open");

const fixture = {
  period: "7d", ledgers: 3,
  totals: { calls: 12, tokens: 45000, input: 30000, output: 15000, cached: 2000,
            usd: 0.42, cny_min: 1.2, cny_max: 1.6, models: 2, unpriced_calls: 1 },
  models: [
    { model: "cn:glm-5.3-flash", calls: 9, tokens: 40000, input: 26000, output: 14000,
      cached: 2000, usd: 0.42, cny_min: 1.2, cny_max: 1.6, share: 0.8889,
      last_at: "2026-11-01 23:10" },
    { model: "prism-ml/bonsai-27b", calls: 3, tokens: 5000, input: 4000, output: 1000,
      cached: 0, usd: 0, cny_min: 0, cny_max: 0, share: 0.1111,
      last_at: "2026-11-01 22:50" },
  ],
  daily: [{ date: "2026-11-01", tokens: 45000, calls: 12, input: 30000, output: 15000 }],
};

(async () => {
  state.payload = fixture;
  await Page.load();
  const html = page.innerHTML;
  assert.ok(html.includes("cn:glm-5.3-flash"), "模型名要出现");
  assert.ok(html.includes("prism-ml/bonsai-27b"), "第二个模型也要出现");
  assert.ok(html.includes("4.0 万"), "合计 token 要按万显示");
  assert.ok(html.includes("88.9%"), "占比要显示");
  assert.ok(html.includes("¥1.20~1.60"), "人民币区间要显示");
  assert.ok(html.includes("没有价格信息"), "未定价调用要说明");
  assert.ok(state.urls.some(u => u.includes("period=7d")), "默认近 7 天");
  assert.ok(state.urls.some(u => u.includes("/api/usage/stats")), "走统计接口");

  // 空数据：给指引而不是空白表格
  state.payload = {
    period: "today", ledgers: 0,
    totals: { calls: 0, tokens: 0, input: 0, output: 0, cached: 0, usd: 0,
              cny_min: 0, cny_max: 0, models: 0, unpriced_calls: 0 },
    models: [], daily: [],
  };
  await Page.load();
  assert.ok(page.innerHTML.includes("还没有用量记录"), "空态要给指引");

  // 接口失败：原样显示原因，不假装有数据
  const failing = vm.createContext({
    $: sel => (sel === "#view-usage" ? page : fakeEl()),
    api: async () => { throw new Error("网络断了"); },
    esc: s => String(s ?? ""),
    encodeURIComponent,
    console,
  });
  vm.runInContext(source, failing);
  const Failing = vm.runInContext("UsagePage", failing);
  await Failing.load();
  assert.ok(page.innerHTML.includes("网络断了"), "错误原因要显示出来");

  console.log("test_usage_page.js: 全部通过");
})();
