const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

/* WP 页签的前端三件事：
   1) 空态给"生成"入口，有成文给预览与下载；
   2) 点生成先弹信息页（团队信息 + 每题分章），提交时把这些原样带上；
   3) 信息页可以取消、可以带出上次填的那套。
   另外盯住接线——writeup.js 必须在 views.js 之前加载，页签切换与重置这两处挂钩
   断掉的话，功能会静默消失。 */

const fields = {
  "[data-f='name']": "灵枢战队",
  "[data-f='members']": "张三、李四，王五",
  "[data-f='affiliation']": "某某大学",
  "[data-f='contest']": "2026 练习赛",
  "[data-f='notes']": "只用题面给的入口",
};
let dirSelects = [];

const box = {
  innerHTML: "",
  dataset: {},
  querySelector(selector) {
    return selector in fields ? { value: fields[selector], focus() {} } : null;
  },
  querySelectorAll(selector) {
    if (selector !== "select[data-cid]") return [];
    return dirSelects.map((item) => ({ dataset: { cid: item.cid }, value: item.value }));
  },
};

const calls = [];
const listeners = [];
let saved = { path: null, markdown: null, updated_at: null };

const OPTIONS = {
  first_time: false,
  directions: ["WEB", "PWN", "REVERSE", "MISC", "CRYPTO", "DS", "IOT"],
  profile: { name: "灵枢战队", members: ["张三", "李四"], affiliation: "某某大学",
             contest: "2026 练习赛", notes: "只用题面给的入口" },
  challenges: [
    { id: "web-01", title: "登录绕过", raw: "web", chapter: "WEB", solved: true },
    { id: "pwn-01", title: "栈溢出", raw: "", chapter: "MISC", solved: false },
  ],
};

const sandbox = {
  $: (selector) => (selector === "#tab-writeup" ? box : null),
  esc: (value) => String(value).replace(/[<>&"]/g,
    (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c])),
  mdRender: (markdown) => `<md>${markdown}</md>`,
  api: async (path, opt) => {
    calls.push([path, opt]);
    if (path.endsWith("/writeup/options")) return OPTIONS;
    if (path.endsWith("/writeup") && opt?.method === "POST") {
      saved = { path: "wp-1.md", markdown: "# 灵枢战队-解题思路\n\n## 具体WP",
                updated_at: "2026-10-29 15:30:00" };
      return saved;
    }
    return saved;
  },
  toast: (message, bad) => calls.push(["toast", message, Boolean(bad)]),
  S: { cur: "sess-wp" },
  document: {
    addEventListener: (name, fn) => listeners.push([name, fn]),
    createElement: () => ({ className: "", textContent: "", remove() {} }),
  },
  console,
};
vm.runInNewContext(
  `${fs.readFileSync('src/spiritscout/web/static/js/writeup.js', 'utf8')}
   globalThis.__WriteUp = WriteUp;`, sandbox);
const WriteUp = sandbox.__WriteUp;

const tick = () => new Promise((resolve) => setTimeout(resolve, 20));
const click = (want) => {
  const btn = { textContent: "开始生成", disabled: false, after() {}, remove() {} };
  listeners[0][1]({ target: { closest: (sel) => (sel === want ? btn : null) } });
  return btn;
};

(async () => {
  assert.equal(typeof WriteUp.load, "function");
  assert.equal(typeof WriteUp.reset, "function");
  assert.equal(listeners.length, 1, '点击代理应当挂上');
  assert.equal(listeners[0][0], "click");

  // 空态：还没有 WP 时要给生成入口
  await WriteUp.load();
  assert.deepEqual(calls.at(-1)[0], "/api/sessions/sess-wp/writeup");
  assert.match(box.innerHTML, /生成 WP/);
  assert.match(box.innerHTML, /data-wp="open"/);

  // 点生成 → 先出信息页，并把上次那套带出来
  click("[data-wp='open']");
  await tick();
  assert.deepEqual(calls.at(-1)[0], "/api/sessions/sess-wp/writeup/options");
  assert.match(box.innerHTML, /写 WP 前确认一下信息/);
  assert.match(box.innerHTML, /data-f="name"[^>]*value="灵枢战队"/, "团队名称要带出来");
  assert.match(box.innerHTML, /value="张三、李四"/, "队员用顿号回填");
  assert.match(box.innerHTML, /<option value="WEB" selected>/, "自动判定的方向要选中");
  assert.match(box.innerHTML, /<option value="MISC" selected>/, "没标注的题默认 MISC");
  assert.match(box.innerHTML, /data-cid="web-01"/);
  assert.match(box.innerHTML, /已带出上次填的信息/);
  assert.match(box.innerHTML, /data-wp="submit"/);
  assert.match(box.innerHTML, /data-wp="cancel"/);
  assert.equal(calls.filter((c) => c[0] === "/api/sessions/sess-wp/writeup/options").length,
               1, "信息页取过一次就别重复请求");

  // 取消 → 回到原来的空态/预览，不发生成请求
  click("[data-wp='cancel']");
  await tick();
  assert.match(box.innerHTML, /生成 WP/);
  assert.equal(calls.filter((c) => c[1]?.method === "POST").length, 0);

  // 再点开 → 重新取一次（可能刚改过信息）
  click("[data-wp='open']");
  await tick();

  // 提交 → 带着填的表单与分章发 POST
  dirSelects = [{ cid: "web-01", value: "PWN" }, { cid: "pwn-01", value: "PWN" }];
  click("[data-wp='submit']");
  await tick();
  const post = calls.find((item) => item[1]?.method === "POST");
  assert.ok(post, "点开始生成必须发 POST");
  const body = JSON.parse(post[1].body);
  assert.deepEqual(body.team, {
    name: "灵枢战队", members: ["张三", "李四", "王五"],
    affiliation: "某某大学", contest: "2026 练习赛", notes: "只用题面给的入口",
  }, "队员要按逗号/顿号拆开");
  assert.deepEqual(body.directions, { "web-01": "PWN", "pwn-01": "PWN" },
                   "手改的分章要带上");
  assert.match(box.innerHTML, /<md># 灵枢战队-解题思路/);
  assert.match(box.innerHTML, /下载 Markdown/);
  assert.ok(calls.some((item) => item[0] === "toast" && /已生成/.test(item[1])));

  // 重新打开时清空，避免上一个会话的 WP 留在新会话里
  WriteUp.reset();
  assert.equal(box.innerHTML, "");

  // 接线：页签、分发、重置、脚本加载顺序，缺一项功能就点不到
  const views = fs.readFileSync('src/spiritscout/web/static/js/views.js', 'utf8');
  assert.match(views, /const TABS = \[[^\]]*"writeup"/);
  assert.ok(views.includes('if (S.tab === "writeup") WriteUp.load();'));
  assert.ok(views.includes('renderWriteUpTab();'));
  assert.ok(views.includes('WriteUp.reset();'));
  assert.match(views, /function renderWriteUpTab\(\)[\s\S]{0,400}button\.hidden = !ctf/);

  const html = fs.readFileSync('src/spiritscout/web/static/index.html', 'utf8');
  assert.ok(html.includes('data-tab="writeup"'), '页签按钮要在页面上');
  assert.ok(html.includes('id="tab-writeup"'), '页签容器要在页面上');
  const writeupAt = html.indexOf('/static/js/writeup.js');
  const viewsAt = html.indexOf('/static/js/views.js');
  assert.ok(writeupAt > 0 && writeupAt < viewsAt, 'writeup.js 必须先于 views.js 加载');

  console.log('writeup tab: empty state, info form, submit body, cancel, reset and wiring passed');
})().catch((error) => { console.error(error); process.exit(1); });
