/* 模型卡片上的启用 / 停用：卡片要一眼看出停用状态，按钮要给出重新启用的入口，
   点一下只发 PATCH 翻状态位——画像字段一个都不上传，后端也不会替你重写。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createContext, runInContext } = require("node:vm");

const SRC = path.join(__dirname, "../src/spiritscout/web/static/js/console.js");
const src = fs.readFileSync(SRC, "utf8");

function slice(startMark, endMark) {
  const start = src.indexOf(startMark);
  assert.ok(start >= 0, `console.js 里找不到 ${startMark}`);
  const end = src.indexOf(endMark, start);
  assert.ok(end > start, `console.js 里找不到 ${endMark}`);
  return src.slice(start, end);
}

/* ------------------------------------------------------------ 卡片渲染 */
const tileCtx = createContext({
  esc: v => String(v ?? ""),
  fmtCtx: n => (n ? `${n}` : "—"),
});
runInContext(
  slice("function modelTile(m) {", "async function loadModels()")
    + "\nglobalThis.modelTile = modelTile;",
  tileCtx);
const modelTile = tileCtx.modelTile;

const disabled = modelTile({
  model: "local/small", enabled: false,
  capabilities: ["text"], context_window: 16384,
});
assert.match(disabled, /class="mtile mt-off"/,
  "停用的卡片要带 mt-off 类，靠压暗一眼区分");
assert.match(disabled, /mt-off-tag/, "停用的卡片要有角标");
assert.match(disabled, /已停用/, "角标文案写「已停用」");
assert.match(disabled, /data-mact="toggle"/, "卡片要有启用/停用入口");
assert.match(disabled, />启用</, "停用状态下按钮文案是「启用」");
/* 停用只是不参与选用，编辑和删除仍然可用 */
assert.match(disabled, /data-mact="edit"/);
assert.match(disabled, /data-mact="del"/);

const enabled = modelTile({
  model: "cloud/big", enabled: true,
  capabilities: ["code"], context_window: 131072,
});
assert.match(enabled, /class="mtile"/, "启用的卡片不带 mt-off");
assert.doesNotMatch(enabled, /mt-off-tag/, "启用的卡片没有角标");
assert.doesNotMatch(enabled, /已停用/);
assert.match(enabled, />停用</, "启用状态下按钮文案是「停用」");

/* 老 YAML 里没有 enabled 这个键 → 缺省即启用，不能画成停用 */
const legacy = modelTile({ model: "old/entry" });
assert.doesNotMatch(legacy, /mt-off/, "缺 enabled 字段的条目当作启用");
assert.match(legacy, />停用</);

/* ------------------------------------------------------------ 点击行为 */
async function checkToggle() {
  const ctx = createContext({});
  ctx.S = { models: { models: [
    { model: "local/small", enabled: false },
    { model: "cloud/big", enabled: true },
  ] } };
  const calls = [];
  const toasts = [];
  let reloaded = 0;
  ctx.api = (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve({ ok: true });
  };
  ctx.toast = (msg, isError) => toasts.push({ msg, isError });
  ctx.loadModels = () => { reloaded += 1; };
  ctx.window = {};
  runInContext(
    slice("window.modelToggle = async model => {", "/* 删模型是重操作")
      + "\nglobalThis.modelToggle = window.modelToggle;",
    ctx);

  // 停用中点一下 → 变成启用
  await ctx.modelToggle("local/small");
  assert.equal(calls.length, 1, "点一次只发一个请求");
  assert.equal(calls[0].opts.method, "PATCH", "只翻状态位，用 PATCH 而不是整体覆盖的 PUT");
  assert.deepEqual(JSON.parse(calls[0].opts.body), { enabled: true },
    "请求体只有 enabled，画像字段不上传");
  assert.equal(calls[0].url, "/api/models/local%2Fsmall",
    "模型 ID 含斜杠要转义，否则会被当成子路径");
  assert.equal(reloaded, 1, "改完要重新拉一次列表");
  assert.match(toasts[0].msg, /已启用/);
  assert.ok(!toasts[0].isError);

  // 启用中点一下 → 变成停用
  await ctx.modelToggle("cloud/big");
  assert.deepEqual(JSON.parse(calls[1].opts.body), { enabled: false });
  assert.match(toasts[1].msg, /已停用/);
  assert.match(toasts[1].msg, /配置保留/, "提示里要说清配置没删");

  // 后端报错要弹红条，不能静默吞掉
  ctx.api = () => Promise.reject(new Error("模型不存在: ghost"));
  await ctx.modelToggle("ghost");
  const last = toasts[toasts.length - 1];
  assert.equal(last.isError, true, "失败要标红");
  assert.match(last.msg, /模型不存在/);
}

checkToggle().then(() => {
  console.log("model toggle ui: ok");
}).catch(err => {
  console.error(err);
  process.exit(1);
});
