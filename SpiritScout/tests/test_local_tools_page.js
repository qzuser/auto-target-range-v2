"use strict";
// 本地工具面板：整页宽布局、目录可加可删、过滤不打断输入、错误要说话。
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
    focus() { el.focused = true; },
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
const state = { calls: [], payload: null, throwOn: new Set() };

const context = vm.createContext({
  $: sel => (sel === "#view-localtools" ? page : page.querySelector(sel)),
  api: async (url, opt = {}) => {
    state.calls.push({ url, method: opt.method || "GET", body: opt.body });
    if (state.throwOn.has(url)) throw new Error("后端连接失败");
    return state.payload;
  },
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])),
  encodeURIComponent,
  setTimeout, clearTimeout, console,
});

vm.runInContext(source, context);
const Page = vm.runInContext("LocalToolsPage", context);

const fixture = {
  config: { enabled: true, dirs: ["D:\\tools"], timeout_seconds: 180 },
  summary: { dirs: 1, tools: 2, scanned_at: Math.floor(Date.now() / 1000) - 30 },
  runs_dir: "D:\\work\\local-tools\\runs",
  tools: [
    { name: "fscan", file: "fscan.exe", ext: ".exe", size: 3 * 1024 * 1024,
      dir: "D:\\tools\\fscan", path: "D:\\tools\\fscan\\fscan.exe" },
    { name: "nmap", file: "nmap.py", ext: ".py", size: 2048,
      dir: "D:\\tools", path: "D:\\tools\\nmap.py" },
  ],
};

(async () => {
  assert.equal(typeof Page.open, "function", "模块应导出 open");

  state.payload = fixture;
  await Page.open();
  const html = page.innerHTML;
  assert.match(html, /<h2>本地工具<\/h2>/, "标题应渲染");
  assert.match(html, /local_tool/, "应说明 Agent 怎么用");
  assert.match(html, /用完不留残留文件/, "应说明运行后还原");
  assert.match(html, /fscan/, "应列出扫描到的工具");
  assert.match(html, /3\.0 MB/, "应显示体积");
  assert.match(html, /D:\\tools/, "应列出已设置的目录");
  assert.doesNotMatch(html, /set-card/, "不该再套 720px 的窄卡片");
  assert.equal(state.calls[0].url, "/api/local-tools", "打开时拉一次配置");

  // 过滤在本地做：输入不该再打接口，也不该重绘整块（光标不跳）
  const before = state.calls.length;
  const query = page.querySelector("#lt-query");
  query.value = "nmap";
  query.fire("input", { target: { value: "nmap" } });
  assert.equal(state.calls.length, before, "过滤不应发请求");
  const toolsHtml = page.querySelector("#lt-tools").innerHTML;
  assert.match(toolsHtml, /nmap/, "过滤后应只剩 nmap");
  assert.doesNotMatch(toolsHtml, /fscan/, "过滤应把不匹配的藏起来");
  query.value = "";
  query.fire("input", { target: { value: "" } });
  assert.match(page.querySelector("#lt-tools").innerHTML, /fscan/, "清空关键词应恢复全部");

  // 开关：改一次提交一次
  const toggle = page.querySelector("#lt-enabled");
  toggle.checked = false;
  toggle.fire("change", { target: { checked: false } });
  await new Promise(resolve => setImmediate(resolve));
  const put = state.calls.filter(call => call.method === "PUT").pop();
  assert.equal(JSON.parse(put.body).enabled, false, "开关状态应提交到后端");

  // 添加目录：追加在已有目录后面
  const input = page.querySelector("#lt-dir-input");
  input.value = "E:\\kit";
  page.querySelector("#lt-dir-add").fire("click");
  await new Promise(resolve => setImmediate(resolve));
  const addPut = state.calls.filter(call => call.method === "PUT").pop();
  assert.deepEqual(JSON.parse(addPut.body).dirs, ["D:\\tools", "E:\\kit"]);

  // 清理暂存返回 {count}，不能把面板数据冲掉（显示错乱就是这么来的）
  state.payload = { count: 0, removed: [], runs_dir: "D:\\work\\local-tools\\runs" };
  page.querySelector("#lt-cleanup").fire("click");
  await new Promise(resolve => setImmediate(resolve));
  await new Promise(resolve => setImmediate(resolve));
  assert.match(page.innerHTML, /使用开关/, "清理后面板结构仍在");
  assert.match(page.innerHTML, /D:\\tools/, "清理后目录仍在");
  state.payload = fixture;

  // 失败要说清楚，而不是白屏
  state.throwOn.add("/api/local-tools");
  await Page.open();
  assert.match(page.innerHTML, /后端连接失败/, "接口失败要在面板上说清楚");
  assert.match(page.innerHTML, /使用开关|索引结果/, "失败也不能把布局抹掉");

  console.log("test_local_tools_page.js OK");
})().catch(error => {
  console.error(error);
  process.exit(1);
});
