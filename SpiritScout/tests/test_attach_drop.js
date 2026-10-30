/* 附件输入区支持直接拖入文件，同时保留点击选取。

   验的是 console.js 里的真实实现：bindAttach 绑的拖放处理器有没有把文件收进
   调用方的数组、拖拽高亮会不会在离开时消掉、纯文本拖拽该不该被接住。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createContext, runInContext } = require("node:vm");

const SRC = path.join(__dirname, "../src/spiritscout/web/static/js/console.js");
const src = fs.readFileSync(SRC, "utf8");

function pick(startMark, endMark) {
  const start = src.indexOf(startMark);
  assert.ok(start >= 0, `console.js 里找不到 ${startMark}`);
  const at = src.indexOf(endMark, start);
  assert.ok(at > start, `console.js 里找不到 ${endMark}`);
  const end = src.indexOf(");", at + endMark.length) + 2;
  return src.slice(start, end);
}

function makeEl(name) {
  const handlers = {};
  const classes = new Set();
  const el = {
    name, handlers, classes, clicked: 0, value: "", files: [],
    innerHTML: "", onclick: null,
    classList: {
      toggle: (c, on) => { if (on === undefined ? !classes.has(c) : on) classes.add(c); else classes.delete(c); },
      add: c => classes.add(c),
      remove: c => classes.delete(c),
      contains: c => classes.has(c),
    },
    addEventListener(t, fn) { (handlers[t] ||= []).push(fn); },
    fire(t, ev) {
      /* 生产代码里 onclick / onchange 是属性赋值，拖放走 addEventListener，
         两条路都要触发，否则测不到真实行为 */
      const prop = el["on" + t];
      if (typeof prop === "function") prop(ev);
      for (const fn of handlers[t] || []) fn(ev);
    },
    querySelectorAll: () => [],
    click() { this.clicked++; this.fire("click", { target: this }); },
    focus() {},
  };
  return el;
}

function build() {
  const els = {
    "#home-attach": makeEl("home-attach"),
    "#home-file": makeEl("home-file"),
    "#home-files": makeEl("home-files"),
    "#view-home .composer": makeEl("home-zone"),
    "#comp-attach": makeEl("comp-attach"),
    "#comp-file": makeEl("comp-file"),
    "#comp-files": makeEl("comp-files"),
    "#view-session .comp": makeEl("comp-zone"),
    "#c-go": makeEl("c-go"),
    "#comp-send": makeEl("comp-send"),
    "#c-mission": makeEl("c-mission"),
    "#c-mode": makeEl("c-mode"),
  };
  els["#c-mode"].value = "ctf";
  const S = { compFiles: [], homeFiles: [] };
  const seen = { onChange: 0 };
  const ctx = createContext({
    S, seen,
    $: sel => els[sel] || null,
    esc: s => String(s ?? ""),
    fmtSize: n => `${n}B`,
    compInput: makeEl("comp-input"),
    homeSync: () => { seen.onChange++; },
  });
  runInContext(
    pick("function renderFileChips", "bindAttach(\"#home-attach\"") +
      "\nthis.bindAttach = bindAttach; this.syncCompSend = syncCompSend;",
    ctx,
  );
  return { ctx, els, S, seen };
}

const file = (name, size = 100) => ({ name, size });
const dropEvent = (files, extraTypes = []) => ({
  preventDefaultCalled: false,
  dataTransfer: { types: ["Files", ...extraTypes], files, dropEffect: "" },
  preventDefault() { this.preventDefaultCalled = true; },
});

/* ------------------------------------------------------------ 用例 */

{
  /* 拖进来 → 进数组、画 chip、高亮收掉、通知调用方 */
  const { els, S, seen } = build();
  const zone = els["#view-home .composer"];
  const ev = dropEvent([file("a.png"), file("b.txt")]);
  zone.fire("dragenter", ev);
  assert.ok(zone.classList.contains("drop-on"), "拖到输入区上方要亮起来");
  zone.fire("drop", ev);
  assert.equal(S.homeFiles.length, 2, "两个文件都要收进附件列表");
  assert.equal(S.homeFiles[0].name, "a.png");
  assert.equal(ev.preventDefaultCalled, true, "不拦默认行为浏览器会直接打开文件");
  assert.ok(!zone.classList.contains("drop-on"), "松手后高亮要收掉");
  assert.ok(seen.onChange >= 1, "要通知调用方刷新发送键状态");
  console.log("  首页拖入两个文件 → 收进列表并高亮收掉: ok");
}

{
  /* 选取功能必须还在：点按钮开文件选择器，选完照样进数组 */
  const { els, S } = build();
  els["#home-attach"].fire("click");
  assert.equal(els["#home-file"].clicked, 1, "点附件按钮要打开文件选择器");
  els["#home-file"].files = [file("picked.zip", 2048)];
  els["#home-file"].fire("change");
  assert.equal(S.homeFiles.length, 1, "选中的文件也要进列表");
  assert.equal(S.homeFiles[0].name, "picked.zip");
  assert.equal(els["#home-file"].value, "", "要清空 input，才能重复选同一个文件");
  console.log("  点按钮选取 → 仍然可用: ok");
}

{
  /* 子元素之间来回移动不该把高亮闪掉：进出计数要正确 */
  const { els } = build();
  const zone = els["#home-zone"] || els["#view-home .composer"];
  const ev = dropEvent([file("x.png")]);
  zone.fire("dragenter", ev);      // 进外层
  zone.fire("dragenter", ev);      // 进子元素，又多一层
  zone.fire("dragleave", ev);      // 离开子元素，还剩一层
  assert.ok(zone.classList.contains("drop-on"), "还在区域内部时不该取消高亮");
  zone.fire("dragleave", ev);      // 真离开
  assert.ok(!zone.classList.contains("drop-on"), "真离开才取消高亮");
  console.log("  子元素间移动 → 高亮不闪: ok");
}

{
  /* 拖一段选中的文字不该被输入区接住，否则粘贴文本会被当成上传 */
  const { els, S } = build();
  const zone = els["#view-home .composer"];
  const ev = dropEvent([], ["text/plain"]);
  ev.dataTransfer.types = ["text/plain"];
  zone.fire("dragenter", ev);
  assert.ok(!zone.classList.contains("drop-on"), "纯文本拖拽不该亮");
  zone.fire("drop", ev);
  assert.equal(S.homeFiles.length, 0, "纯文本不该进附件列表");
  assert.equal(ev.preventDefaultCalled, false, "纯文本要留给浏览器原生处理");
  console.log("  拖文本 → 不拦截: ok");
}

{
  /* 会话页那套也要能拖——两处 composer 共用 bindAttach */
  const { els, S } = build();
  const zone = els["#view-session .comp"];
  const ev = dropEvent([file("shot.jpg")]);
  zone.fire("dragenter", ev);
  zone.fire("drop", ev);
  assert.equal(S.compFiles.length, 1, "会话输入坞同样要支持拖入");
  assert.equal(S.compFiles[0].name, "shot.jpg");
  console.log("  会话页输入坞拖入 → 同样生效: ok");
}

{
  /* 只拖文件不写字，发送键也要亮；清空后要回落 */
  const { ctx, els, S } = build();
  S.homeFiles = [file("only.png")];
  els["#c-mission"].value = "";
  ctx.syncCompSend();
  assert.ok(els["#c-go"].classList.contains("ready"),
    "只带附件也该能发——以前只看文本，按钮是灰的");
  S.homeFiles = [];
  ctx.syncCompSend();
  assert.ok(!els["#c-go"].classList.contains("ready"), "什么都没有时要回落成灰");
  S.compFiles = [file("c.png")];
  ctx.syncCompSend();
  assert.ok(els["#comp-send"].classList.contains("ready"), "会话输入坞同理");
  console.log("  只带附件不写字 → 发送键也亮: ok");
}

console.log("attach drop: ok");
