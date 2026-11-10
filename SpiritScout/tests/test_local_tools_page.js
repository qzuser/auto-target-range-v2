"use strict";
// 本地工具面板：目录清单可加可删、扫描结果成表、动作都走对应接口。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/local-tools.js"), "utf8");

function fakeEl(id) {
  const children = new Map();
  const el = {
    id, dataset: {}, hidden: false, innerHTML: "", value: "", checked: false,
    handlers: {},
    addEventListener(type, fn) { (el.handlers[type] = el.handlers[type] || []).push(fn); },
    fire(type, event = {}) { (el.handlers[type] || []).forEach(fn => fn(event)); },
    querySelector(sel) {
      if (!children.has(sel)) children.set(sel, fakeEl(sel));
      return children.get(sel);
    },
    querySelectorAll(sel) {
      if (sel !== "[data-lt-remove]") return [];
      return el.removers || [];
    },
    removeButtons(dirs) {
      el.removers = dirs.map(dir => {
        const button = fakeEl(`remove:${dir}`);
        button.dataset.ltRemove = dir;
        return button;
      });
      return el.removers;
    },
  };
  return el;
}

const page = fakeEl("#view-localtools");
const state = { calls: [], payload: null, inflight: 0 };

const context = vm.createContext({
  $: sel => (sel === "#view-localtools" ? page : fakeEl(sel)),
  api: async (url, opt = {}) => {
    state.calls.push({ url, method: opt.method || "GET", body: opt.body });
    state.inflight += 1;
    try {
      return state.payload;
    } finally {
      state.inflight -= 1;
    }
  },
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
  encodeURIComponent,
  setTimeout: fn => { fn(); return 0; },
  clearTimeout: () => {},
  console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("LocalToolsPage", context);

const fixture = {
  config: { enabled: true, dirs: ["D:\\tools"], timeout_seconds: 180 },
  summary: { dirs: 1, tools: 1, scanned_at: Math.floor(Date.now() / 1000) - 30 },
  notice: "运行由 Agent 发起：工具目录先复制到暂存副本，跑完还原原目录并删除副本。",
  tools: [{ name: "fscan", file: "fscan.exe", ext: ".exe", size: 3 * 1024 * 1024,
            dir: "D:\\tools\\fscan", path: "D:\\tools\\fscan\\fscan.exe" }],
};
state.payload = fixture;

(async () => {
  assert.equal(typeof Page.open, "function", "模块应导出 open");

  await Page.open();
  const html = page.innerHTML;
  assert.match(html, /本地工具索引/, "应渲染面板标题");
  assert.match(html, /后不留残留文件|跑完核对并还原原目录/, "应说明运行后还原");
  assert.match(html, /fscan/, "应列出扫描到的工具");
  assert.match(html, /3\.0 MB/, "应显示体积");
  assert.match(html, /D:\\tools/, "应列出已设置的目录");
  assert.equal(state.calls[0].url, "/api/local-tools?q=", "打开时按默认查询拉数");

  // 开关：改一次就往 PUT 提交一次
  const toggle = page.querySelector("#lt-enabled");
  toggle.checked = false;
  toggle.fire("change", { target: { checked: false } });
  await new Promise(resolve => setImmediate(resolve));
  const put = state.calls.filter(call => call.method === "PUT").pop();
  assert.ok(put, "应发过 PUT");
  assert.equal(JSON.parse(put.body).enabled, false, "开关状态应提交到后端");

  // 保存目录：把新目录并进去
  const input = page.querySelector("#lt-dir-input");
  input.value = "E:\\kit";
  page.querySelector("#lt-dir-add").fire("click");
  await new Promise(resolve => setImmediate(resolve));
  const addPut = state.calls.filter(call => call.method === "PUT").pop();
  assert.deepEqual(JSON.parse(addPut.body).dirs, ["D:\\tools", "E:\\kit"],
    "新目录应追加到已有目录后面");

  // 过滤：输入关键词会用 q 重新拉数
  const query = page.querySelector("#lt-query");
  query.value = "fsc";
  query.fire("input", { target: { value: "fsc" } });
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(state.calls.some(call => call.url === "/api/local-tools?q=fsc"),
    "过滤应带 q 参数重新拉数");

  // 失败：给出错误提示而不是静默吞掉
  state.payload = null;
  context.api = async () => { throw new Error("后端连接失败"); };
  vm.runInContext("api = () => { throw new Error('后端连接失败'); }", context);
  await Page.open();
  assert.match(page.innerHTML, /后端连接失败/, "接口失败要在面板上说清楚");

  console.log("test_local_tools_page.js OK");
})().catch(error => {
  console.error(error);
  process.exit(1);
});
