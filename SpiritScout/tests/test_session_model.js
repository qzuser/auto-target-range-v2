"use strict";
// 会话页模型选择：自动/已选/已下线三种选项形态、请求体、缓存与状态回写。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../src/spiritscout/web/static/js/views.js"), "utf8");

// 从大文件里按函数名切出完整函数体（大括号配平，跳过字符串里的括号不追求完美，
// 这些函数体内没有裸括号字面量）
function sliceFn(name) {
  const head = source.indexOf(`async function ${name}(`) >= 0
    ? `async function ${name}(` : `function ${name}(`;
  const start = source.indexOf(head);
  assert.ok(start >= 0, `views.js 里找不到 ${name}`);
  let depth = 0, seen = false;
  for (let i = start; i < source.length; i += 1) {
    const ch = source[i];
    if (ch === "{") { depth += 1; seen = true; }
    else if (ch === "}") {
      depth -= 1;
      if (seen && depth === 0) return source.slice(start, i + 1);
    }
  }
  throw new Error(`${name} 没闭合`);
}

const asyncNames = ["loadSessionModels", "saveSessionModel"];
const body = ["sessionModelOptions", "sessionModelChip", ...asyncNames]
  .map(n => sliceFn(n) + "\n").join("");

const state = {list: [], calls: [], fetchCount: 0, failNext: false};
const context = vm.createContext({
  esc: s => String(s ?? "").replace(/[&<>"]/g,
    c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c])),
  S: {state: {session: {session_id: "sess-1", model: ""}}},
  api: async (p, opt) => {
    state.calls.push({path: p, opt});
    if (p === "/api/models") {
      state.fetchCount += 1;
      if (state.failNext) throw new Error("boom");
      return {models: state.list};
    }
    return {model: JSON.parse(opt.body).model};
  },
  JSON, console,
});
vm.runInContext(body, context);
const options = vm.runInContext("sessionModelOptions", context);
const chip = vm.runInContext("sessionModelChip", context);
const load = vm.runInContext("loadSessionModels", context);
const save = vm.runInContext("saveSessionModel", context);

const models = [{model: "m-a", provider_ref: "local"}, {model: "m-b", provider_ref: "local"}];

(async () => {
  // ① 没选：默认项选中，其余模型都列出来
  let html = options({model: ""}, models);
  assert.match(html, /自动 · 跟随全局优先级/, "空值要说明「自动」的含义");
  assert.match(html, /<option value="m-a">/);
  assert.match(html, /<option value="m-b">/);
  assert.doesNotMatch(html, /selected/, "没选时不该有任何模型被选中");

  // ② 选了 m-b：该项 selected，且只选中一个
  html = options({model: "m-b"}, models);
  assert.match(html, /<option value="m-b" selected>/);
  assert.equal((html.match(/selected/g) || []).length, 1);

  // ③ 选过但已从注册表消失：如实列出「已下线」，让用户看得见现状
  html = options({model: "gone"}, models);
  assert.match(html, /gone（已下线）/, "下线的模型不能静默消失");
  assert.match(html, /gone（已下线）<\/option>/);

  // ④ 只给字符串列表也认（/api/models 精简形态）
  html = options({model: "m-a"}, ["m-a", "m-c"]);
  assert.match(html, /<option value="m-a" selected>/);
  assert.match(html, /<option value="m-c">/);

  // ⑤ chip：空值不亮，选中后带 on 类，标题说明「自动」含义
  assert.match(chip({model: ""}, models), /id="s-model"/);
  assert.doesNotMatch(chip({model: ""}, models), /model-chip on/);
  const picked = chip({model: "m-b"}, models);
  assert.match(picked, /model-chip on/);
  assert.match(picked, /优先级链/);

  // ⑥ 保存：POST 到会话模型端点，请求体只带 model，并回写本地状态
  await save("sess-1", "m-b");
  const post = state.calls.find(c => c.path === "/api/sessions/sess-1/model");
  assert.ok(post, "应调用 /api/sessions/{id}/model");
  assert.equal(post.opt.method, "POST");
  assert.deepEqual(JSON.parse(post.opt.body), {model: "m-b"});
  assert.equal(context.S.state.session.model, "m-b", "保存后本地状态跟着改");

  // ⑦ 撤销走同一个端点、body 为空串
  await save("sess-1", "");
  const cleared = state.calls[state.calls.length - 1];
  assert.deepEqual(JSON.parse(cleared.opt.body), {model: ""});

  // ⑧ 模型列表拉一次就缓存，轮询重绘不再打接口
  state.list = models;
  const first = await load();
  assert.equal(first.length, 2);
  const before = state.fetchCount;
  await load();
  assert.equal(state.fetchCount, before, "第二次应直接用缓存");

  // ⑨ 接口挂了：不抛（会话页照常渲染），退化成只有「自动」一项
  context.S.sessionModels = null;
  state.failNext = true;
  const fallback = await load();
  assert.equal(fallback.length, 0, "接口挂了就当没有可选模型");
  assert.match(options({model: ""}, fallback), /自动 · 跟随全局优先级/);

  console.log("test_session_model.js 通过");
})().catch(err => { console.error(err); process.exit(1); });
