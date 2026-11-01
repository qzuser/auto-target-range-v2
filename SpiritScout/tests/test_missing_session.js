/* 会话在别处被删掉之后，前端不能继续把它当活的：
   - 点侧栏那一行不该切进一个 404 的会话页；
   - 已经停在死会话上时，要摘掉记录、停流、退回首页，而不是按轮询节奏
     反复弹「会话不存在」。

   这里把 views.js 的 dropMissingSession / openSession 原样抽出来跑，
   桩掉它们依赖的渲染与路由函数，验的是真实实现。 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createContext, runInContext } = require("node:vm");

const SRC = path.join(__dirname, "../src/spiritscout/web/static/js/views.js");
const src = fs.readFileSync(SRC, "utf8");

function pick(startMark, endMark) {
  const start = src.indexOf(startMark);
  assert.ok(start >= 0, `views.js 里找不到 ${startMark}`);
  /* 文件是 CRLF，不能拿 "\n}" 当边界；endMark 之后收下一个右括号即为函数体结尾。
     dropMissingSession 里没有 startStreams()，openSession 里只有一处。 */
  const at = src.indexOf(endMark, start);
  assert.ok(at > start, `views.js 里找不到 ${endMark}`);
  const end = src.indexOf("}", at + endMark.length) + 1;
  return src.slice(start, end);
}

function build({ sessions = [], cur = null } = {}) {
  const calls = { renderSessions: 0, renderTaskDock: 0, stopStreams: 0, show: [], toast: [], refreshState: 0, startStreams: 0 };
  const el = () => ({
    dataset: {},
    replaceChildren() {},
    classList: { toggle() {}, remove() {}, add() {}, contains: () => false },
    setAttribute() {},
  });
  const S = { view: "session", cur, tab: "chat", sessions: sessions.slice(), state: { session: {} }, evSeen: 0, topoView: null };
  const sandbox = {
    S, calls,
    TABS: ["chat"],
    $: () => el(),
    document: { querySelectorAll: () => [], querySelector: () => el() },
    window: { innerWidth: 1200 },
    renderSessions: () => { calls.renderSessions++; },
    renderTaskDock: () => { calls.renderTaskDock++; },
    stopStreams: () => { calls.stopStreams++; },
    show: v => { calls.show.push(v); },
    toast: (m, e) => { calls.toast.push([m, !!e]); },
    renderChallenges: () => {},
    updateSessionActions: () => {},
    refreshState: () => { calls.refreshState++; },
    startStreams: () => { calls.startStreams++; },
    SessionArchive: { reset() {} },
    ToolParameters: { reset() {} },
    WriteUp: { reset() {} },
    SessionExperience: { reset() {} },
  };
  sandbox.window.$ = sandbox.$;
  sandbox.window.document = sandbox.document;
  const ctx = createContext(sandbox);
  runInContext(
    pick("function dropMissingSession", "startStreams();") +
      "\nthis.dropMissingSession = dropMissingSession;" +
      "this.openSession = openSession;",
    ctx,
  );
  return { ctx, S, calls };
}

const sess = id => ({ session_id: id, status: "running", title: id });

/* ------------------------------------------------------------ 用例 */

{
  const { ctx, S, calls } = build({ sessions: [sess("s-1"), sess("s-2")], cur: "s-1" });
  const dropped = ctx.dropMissingSession("s-1");
  assert.equal(dropped, true, "清的是当前会话就返回 true");
  assert.equal(S.cur, null, "当前会话要清空");
  assert.equal(S.state, null, "旧快照要丢掉，否则页面还显示着死会话的内容");
  assert.equal(calls.stopStreams, 1, "要停掉 SSE/轮询");
  assert.deepEqual(calls.show, ["home"], "退回首页");
  assert.deepEqual(S.sessions.map(s => s.session_id), ["s-2"], "本地列表摘掉这一条");
  assert.equal(calls.renderSessions, 1, "侧栏要重绘，那一行才会消失");
  assert.equal(calls.toast.length, 1, "要告诉用户发生了什么");
  console.log("  删掉的是当前会话 → 清空并退回首页: ok");
}

{
  const { ctx, S, calls } = build({ sessions: [sess("s-1"), sess("s-2")], cur: "s-2" });
  const dropped = ctx.dropMissingSession("s-1");
  assert.equal(dropped, false, "删的不是当前会话就不该动正在看的页");
  assert.equal(S.cur, "s-2", "当前会话保持不变");
  assert.equal(calls.stopStreams, 0, "别停别人的流");
  assert.deepEqual(calls.show, [], "别切页面");
  assert.deepEqual(S.sessions.map(s => s.session_id), ["s-2"], "但那一条要从列表里摘掉");
  console.log("  删掉的是别的会话 → 只摘列表不动当前页: ok");
}

{
  const { ctx, S, calls } = build({ sessions: [sess("s-1")], cur: null });
  assert.equal(ctx.dropMissingSession("ghost"), false, "本来就没有的 id 返回 false");
  assert.equal(calls.toast.length, 0, "没人在看它，不用打扰");
  console.log("  幽灵 id 且无当前会话 → 静默: ok");
}

{
  /* 刚创建完的会话、从仪表盘/项目页进来的已归档会话，都可能还不在 S.sessions 里。
     这时必须照常打开，否则「开始执行」后进不了自己的新会话。真被删掉的由
     refreshState 的 404 兜底。 */
  const { ctx, S, calls } = build({ sessions: [sess("s-1"), sess("s-2")], cur: "s-2" });
  ctx.openSession("s-lost");
  assert.equal(S.cur, "s-lost", "列表里没有也要切过去——不能挡住刚创建的会话");
  assert.deepEqual(calls.show, ["session"]);
  assert.equal(calls.refreshState, 1, "进入后由 refreshState 去问后端，404 再收口");
  assert.equal(calls.toast.length, 0, "这里不该先报错");
  console.log("  列表里暂时没有的会话 → 照常打开: ok");
}

{
  const { ctx, S, calls } = build({ sessions: [sess("s-1"), sess("s-2")], cur: null });
  ctx.openSession("s-2");
  assert.equal(S.cur, "s-2", "列表里有的会话要正常打开");
  assert.deepEqual(calls.show, ["session"]);
  assert.equal(calls.refreshState, 1);
  assert.equal(calls.startStreams, 1);
  console.log("  点正常会话 → 照常打开: ok");
}

{
  /* 列表还没加载完（空数组）时不能做「不存在」判断，否则会把合法会话挡在门外 */
  const { ctx, S } = build({ sessions: [], cur: null });
  ctx.openSession("s-new");
  assert.equal(S.cur, "s-new", "列表未加载时不做存在性判断");
  console.log("  列表尚未加载 → 不误挡: ok");
}

{
  /* 连开两个会话：以后打开的为准，前一个不留残余 */
  const { ctx, S, calls } = build({ sessions: [sess("s-1"), sess("s-2")], cur: null });
  calls.toast.length = 0;
  ctx.openSession("s-gone");
  ctx.openSession("s-1");
  assert.equal(S.cur, "s-1", "以后打开的为准");
  assert.equal(calls.refreshState, 2, "每次打开都要去问一次后端");
  assert.equal(calls.toast.length, 0, "打开本身不报错");
  console.log("  连开两个会话 → 以后者为准: ok");
}

console.log("missing session: ok");
