/* Flag 页的复制按钮：点一下把值拿走，按钮当场变「已复制」再自己复原。

   两件事容易写错，这里各钉一条：
   1. navigator.clipboard 只在安全上下文（HTTPS / localhost）可用，从局域网 IP
      打开控制台时是 undefined——必须有 textarea + execCommand 的退路，否则按钮
      点了没反应；
   2. 复制是异步的，等待期间列表可能被 SSE 重渲染，此时改的必须是那颗旧按钮，
      不能串到别的卡片上。
*/
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createContext, runInContext } = require("node:vm");

const SRC = path.join(__dirname, "../src/spiritscout/web/static/js/views.js");
const src = fs.readFileSync(SRC, "utf8");

function pick(startMark, endMark) {
  const start = src.indexOf(startMark);
  assert.ok(start >= 0, `views.js 里找不到 ${startMark}`);
  const end = src.indexOf(endMark, start);
  assert.ok(end > start, `views.js 里找不到 ${endMark}`);
  return src.slice(start, end);
}

/* ------------------------------------------------ 桩 DOM */
function makeButton(index) {
  const classes = new Set();
  const label = {textContent: "复制"};
  return {
    dataset: {flag: String(index)},
    disabled: false,
    onclick: null,
    classList: {
      toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
      remove(name) { classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    querySelector(sel) { return sel === "span" ? label : null; },
    label,
  };
}

function build({secure = true, clipboardWorks = true, execWorks = true, flags = []} = {}) {
  const buttons = flags.map((_, i) => makeButton(i));
  const body = [];
  const written = [];
  const execCalls = [];

  const box = {
    innerHTML: "",
    querySelectorAll(sel) {
      return sel === ".flag-copy" ? buttons : [];
    },
  };

  const sandbox = {
    S: {state: {flags: flags.length ? {items: flags} : {items: []}}},
    $: sel => (sel === "#tab-flags" ? box : null),
    esc: v => String(v == null ? "" : v),
    buttons,
    body,
    written,
    execCalls,
    window: {isSecureContext: secure},
    navigator: clipboardWorks
      ? {clipboard: {writeText: async text => { written.push(text); }}}
      : {},
    document: {
      createElement: () => ({
        value: "",
        style: {cssText: ""},
        setAttribute() {},
        select() {},
        remove() { body.pop(); },
      }),
      get body() {
        return {append: el => body.push(el)};
      },
      execCommand(cmd) {
        execCalls.push(cmd);
        return execWorks;
      },
    },
    /* 同步跑回调，省掉 1.4 秒等待；恢复逻辑本身照验 */
    setTimeout: fn => fn(),
  };
  sandbox.window = Object.assign(sandbox.window, {navigator: sandbox.navigator});
  const ctx = createContext(sandbox);
  runInContext(
    pick("async function copyText(", "function renderFlags()") +
      pick("function renderFlags()", "/* ---- 解题轨迹") +
      "\nthis.copyText = copyText;" +
      "this.copyFlagByIndex = copyFlagByIndex;" +
      "this.renderFlags = renderFlags;",
    ctx,
  );
  return {ctx, box, buttons, body, written, execCalls};
}

/* ------------------------------------------------ 渲染 */
{
  const {ctx, box, buttons} = build({
    flags: [
      {value: "flag{one}", challenge_id: "web-1", submitted: false, accepted: false},
      {value: "flag{two}", challenge_id: "pwn-2", submitted: true, accepted: false},
      {value: "flag{three}", challenge_id: "crypto-3", submitted: true, accepted: true},
    ],
  });
  ctx.renderFlags();
  const html = box.innerHTML;
  assert.equal(buttons.length, 3, "三条 Flag 应各有一颗复制按钮");
  assert.ok(html.includes('data-flag="0"') && html.includes('data-flag="2"'),
    "按钮要带下标，点了才知道复制哪一条");
  assert.ok(html.includes("flag{one}") && html.includes("flag{three}"), "值要照原样渲染");
  assert.ok(html.includes("已判定") && html.includes("已提交") && html.includes("已提取"),
    "三种状态的标签都要在");
  assert.ok(buttons.every(b => typeof b.onclick === "function"), "每颗按钮都要绑上点击");
  console.log("  渲染：按钮 + 下标 + 状态标签: ok");
}

{
  const {ctx, box} = build({flags: []});
  ctx.renderFlags();
  assert.ok(box.innerHTML.includes("尚无 Flag 记录"), "空列表给空态，不留一堆空卡片");
  assert.ok(!box.innerHTML.includes("flag-copy"), "空列表不该渲染按钮");
  console.log("  空列表：空态: ok");
}

/* ------------------------------------------------ 复制通路 */
(async () => {
  {
    const {ctx, written, execCalls} = build({secure: true, clipboardWorks: true});
    const ok = await ctx.copyText("flag{abc}");
    assert.equal(ok, true);
    assert.deepEqual(written, ["flag{abc}"], "安全上下文应走 navigator.clipboard");
    assert.deepEqual(execCalls, [], "走了 clipboard 就不该再碰 execCommand");
    console.log("  安全上下文：用 clipboard API: ok");
  }

  {
    // 局域网 IP 打开时 isSecureContext 是 false → 必须退回 textarea 方案
    const {ctx, written, execCalls, body} = build({secure: false, clipboardWorks: true});
    const ok = await ctx.copyText("flag{lan}");
    assert.equal(ok, true, "非安全上下文也得能复制");
    assert.deepEqual(written, [], "非安全上下文拿不到 clipboard");
    assert.deepEqual(execCalls, ["copy"], "应退回 execCommand('copy')");
    assert.equal(body.length, 0, "临时 textarea 用完要摘掉，不能留在 DOM 里");
    console.log("  非安全上下文：退回 execCommand: ok");
  }

  {
    const {ctx, body} = build({secure: false, execWorks: false});
    const ok = await ctx.copyText("flag{x}");
    assert.equal(ok, false, "两条路都失败要如实返回 false");
    assert.equal(body.length, 0, "失败也不能把 textarea 留在页面上");
    console.log("  两条路都失败：返回 false 且清理干净: ok");
  }

  /* ------------------------------------------------ 按钮反馈 */
  {
    const {ctx, buttons} = build({
      secure: true, clipboardWorks: true,
      flags: [{value: "flag{one}", challenge_id: "a"}],
    });
    ctx.renderFlags();
    const btn = buttons[0];
    await ctx.copyFlagByIndex(btn, {value: "flag{one}"});
    // setTimeout 在桩里同步执行，所以这里看到的是「已经复原」之后的状态
    assert.equal(btn.label.textContent, "复制", "复原后回到「复制」");
    assert.equal(btn.disabled, false, "复原后要能再点");
    assert.equal(btn.classList.contains("copied"), false, "复原后摘掉成功样式");
    console.log("  复制后复原: ok");
  }

  {
    const {ctx} = build({secure: true, clipboardWorks: true});
    const btn = makeButton(0);
    let textDuring;
    const realSetTimeout = ctx.setTimeout;
    ctx.setTimeout = fn => { textDuring = btn.label.textContent; /* 先不跑复原 */ };
    await ctx.copyFlagByIndex(btn, {value: "flag{one}"});
    assert.equal(textDuring, "已复制", "复制成功当场应变「已复制」");
    assert.ok(btn.classList.contains("copied"), "成功时挂上 .copied");
    assert.equal(btn.disabled, true, "等待复原期间要禁用，防连点");
    ctx.setTimeout = realSetTimeout;
    console.log("  成功当场反馈: ok");
  }

  {
    const {ctx} = build({secure: false, execWorks: false});
    const btn = makeButton(0);
    let seen;
    ctx.setTimeout = fn => { seen = btn.label.textContent; };
    await ctx.copyFlagByIndex(btn, {value: "flag{one}"});
    assert.equal(seen, "复制失败", "复制失败要说失败，不能假装成功");
    assert.equal(btn.classList.contains("copied"), false, "失败不挂成功样式");
    console.log("  失败如实反馈: ok");
  }

  console.log("flag copy: ok");
})().catch(err => { console.error(err); process.exit(1); });
