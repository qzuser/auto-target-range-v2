"use strict";
// 状态徽标：提炼中 / 询问中 与 运行中/已完成/已中断 同级，且口径与后端一致。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const core = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/core.js"), "utf8");

// 只取需要的那两段：常量表与 statusInfo（整份 core.js 依赖 DOM，不能整体执行）
const cnBlock = core.match(/const STATUS_CN = \{[\s\S]*?\n\s*distilling: "提炼中", asking: "询问中" \};/);
assert.ok(cnBlock, "STATUS_CN 应包含 distilling / asking 两项");
const fnBlock = core.match(/function statusInfo\(s\) \{[\s\S]*?\n\}/);
assert.ok(fnBlock, "core.js 应导出 statusInfo");

const terminal = core.match(/const TERMINAL = new Set\(\[[^\]]*\]\);/);
assert.ok(terminal, "TERMINAL 集合应还在");

const context = vm.createContext({});
vm.runInContext(`${terminal[0]}\n${cnBlock[0]}\n${fnBlock[0]}`, context);
const statusInfo = vm.runInContext("statusInfo", context);

// 提炼中：即便已经 completed，也显示提炼中（自动提炼就在收尾之后）
assert.deepEqual({ ...statusInfo({ status: "completed", distilling: true }) },
  { key: "distilling", text: "提炼中" });
// 询问中：运行中 + 有待答问题
assert.deepEqual({ ...statusInfo({ status: "running", pending_questions: 2 }) },
  { key: "asking", text: "询问中" });
// 提炼中优先于询问中
assert.equal(statusInfo({ status: "running", distilling: true, pending_questions: 1 }).key,
  "distilling");
// 终态残留待答不改成询问中
assert.deepEqual({ ...statusInfo({ status: "completed", pending_questions: 1 }) },
  { key: "completed", text: "已完成" });
// 原有四档不变
for (const [status, text] of [["running", "运行中"], ["completed", "已完成"],
                              ["interrupted", "已中断"], ["failed", "失败"]]) {
  assert.deepEqual({ ...statusInfo({ status }) }, { key: status, text });
}
// 空对象/脏数据兜底
assert.deepEqual({ ...statusInfo({}) }, { key: "", text: "" });
assert.equal(statusInfo(null).key, "");

// 三处渲染点都必须走同一口径，不许再直接写 STATUS_CN[s.status]
for (const [name, pattern] of [
  ["会话列表", /function sessionItemHtml[\s\S]*?statusInfo\(s\)/],
  ["任务坞", /body\.innerHTML = behind\.map[\s\S]*?statusInfo\(s\)/],
]) {
  assert.match(core, pattern, `${name} 应用 statusInfo 取徽标`);
}
assert.doesNotMatch(core, /pill \$\{s\.status\}/,
  "不应再有直接拿 status 当 class 的旧写法");

const views = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/views.js"), "utf8");
assert.match(views, /statusInfo\(s\)[\s\S]*?headStatus\.text/, "会话标题栏也要走 statusInfo");

const css = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/css/base.css"), "utf8");
assert.match(css, /\.pill\.distilling\s*\{/, "提炼中要有独立样式");
assert.match(css, /\.pill\.asking\s*\{/, "询问中要有独立样式");

console.log("test_status_badges.js: 全部通过");
