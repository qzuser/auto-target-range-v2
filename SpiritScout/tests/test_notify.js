"use strict";
/* 提醒引擎：系统通知、退化提示、去重与「正看着就别弹」的口径。
   notify.js 是注入式工厂，这里用假的 Notification / localStorage 驱动，
   全部断言都能在 node 里跑，不需要浏览器。 */
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm'), path = require('node:path');

function loadModule() {
  const context = vm.createContext({console});
  const source = fs.readFileSync(
    path.join(__dirname, '../src/spiritscout/web/static/js/notify.js'), 'utf8');
  vm.runInContext(source, context);
  return vm.runInContext('ConsoleNotify', context);
}

function fakeStorage(initial) {
  const map = new Map(Object.entries(initial || {}));
  return {
    getItem: key => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key),
    dump: () => Object.fromEntries(map),
  };
}

class FakeNotification {
  constructor(title, options) {
    this.title = title;
    this.options = options || {};
    this.closed = false;
    FakeNotification.created.push(this);
  }
  close() { this.closed = true; }
  static reset(permission) {
    FakeNotification.created = [];
    FakeNotification.permission = permission || "granted";
  }
  static requestPermission() { return Promise.resolve(FakeNotification.permission); }
}
FakeNotification.created = [];
FakeNotification.permission = "granted";

function harness(options) {
  const opt = options || {};
  const doc = {title: "灵枢 · SpiritScout", visibilityState: opt.visibilityState || "hidden"};
  const win = {focused: 0, focus() { win.focused += 1; }};
  const toasts = [], opened = [];
  const storage = fakeStorage(opt.storage);
  FakeNotification.reset(opt.permission || "granted");
  const engine = loadModule().create({
    fetchItems: opt.fetchItems || (async () => ({items: [], counts: {}})),
    storage,
    notifyCtor: FakeNotification,
    doc,
    win,
    toastFn: message => toasts.push(message),
    isCurrent: id => (opt.current || "") === id,
    openSession: id => opened.push(id),
  });
  return {engine, doc, win, toasts, opened, storage};
}

const solved = (id, at) => ({id: `flag:sess-a:${id}`, kind: "solved", session_id: "sess-a",
  session_title: "打一台 Web", title: "解出一道题", body: `web-1 · flag{${id}}`, at: at || 1});
const asked = (id, at) => ({id: `ask:sess-b:${id}`, kind: "question", session_id: "sess-b",
  session_title: "授权确认", title: "灵枢在等你回答", body: "要加入 example.com 吗？", at: at || 2});

(async () => {
  // 1) 有权限：一条一条弹系统通知，绝不会重复
  {
    let payload = {items: [solved("a"), asked("q1")], counts: {solved: 1, question: 1}};
    const box = harness({fetchItems: async () => payload});
    const raised = await box.engine.check();
    assert.equal(raised.length, 2);
    assert.equal(FakeNotification.created.length, 2, "两条都该弹系统通知");
    assert.equal(FakeNotification.created[0].title, "解出一道题");
    assert.equal(FakeNotification.created[1].title, "灵枢在等你回答");
    assert.match(FakeNotification.created[0].options.body, /打一台 Web/,
      "通知正文要带会话名，不然切回来不知道是哪一个");
    assert.equal(JSON.parse(box.storage.getItem("ss.notify.seen")).length, 2);
    assert.equal((await box.engine.check()).length, 0, "同一批条目再拉一次不能再响");
    payload = {items: [solved("a"), asked("q1"), solved("b")], counts: {solved: 2, question: 1}};
    const second = await box.engine.check();
    assert.equal(second.length, 1, "只有新增的那条才提醒");
    assert.equal(box.engine.counts().question, 1);
    assert.equal(box.engine.items().length, 3);
  }

  // 2) 点通知：窗口聚焦 + 跳回那个会话 + 关掉通知
  {
    const box = harness({fetchItems: async () => ({items: [asked("q9")]})});
    await box.engine.check();
    const note = FakeNotification.created[0];
    note.onclick();
    assert.equal(box.win.focused, 1, "点通知要把控制台窗口拉回前台");
    assert.deepEqual(box.opened, ["sess-b"], "点通知要跳到对应会话");
    assert.equal(note.closed, true, "点完把通知关掉");
  }

  // 3) 没权限：退化成页面内提示 + 标题计数，clearFlash 复原
  {
    const box = harness({permission: "default", fetchItems: async () => ({items: [asked("q2")]})});
    await box.engine.check();
    assert.equal(FakeNotification.created.length, 0, "没权限不该硬发系统通知");
    assert.equal(box.toasts.length, 1, "退化提示必须落到页面上");
    assert.match(box.toasts[0], /灵枢在等你回答/);
    assert.equal(box.doc.title, "(1) 灵枢 · SpiritScout", "标题上要能看见计数");
    box.engine.clearFlash();
    assert.equal(box.doc.title, "灵枢 · SpiritScout");
  }

  // 4) 正看着那个会话且页面在前台：不打扰，但算已读
  {
    const box = harness({current: "sess-b", visibilityState: "visible",
      fetchItems: async () => ({items: [asked("q3")]})});
    assert.equal((await box.engine.check()).length, 0);
    assert.equal(FakeNotification.created.length, 0);
    assert.equal(box.toasts.length, 0, "屏幕上已经有提问卡，不该再弹");
    assert.equal(JSON.parse(box.storage.getItem("ss.notify.seen")).length, 1);
  }

  // 5) 开关关着：不提醒也不攒着，开了之后旧条目不会再补一遍
  {
    const box = harness({storage: {"ss.notify.enabled": "off"},
      fetchItems: async () => ({items: [solved("old")]})});
    await box.engine.check();
    assert.equal(FakeNotification.created.length, 0);
    assert.equal(box.toasts.length, 0);
    box.engine.setEnabled(true);
    await box.engine.check();
    assert.equal(FakeNotification.created.length, 0, "关着的时候不该攒着等开了再补");
  }

  // 6) 后端拉不到：静默放弃，不污染已读
  {
    const box = harness({fetchItems: async () => { throw new Error("502"); }});
    assert.equal((await box.engine.check()).length, 0);
    assert.equal(box.storage.getItem("ss.notify.seen"), null);
    assert.equal(box.doc.title, "灵枢 · SpiritScout");
  }

  // 7) 本地记录损坏：照常工作
  {
    const box = harness({storage: {"ss.notify.seen": "{not json"},
      fetchItems: async () => ({items: [solved("x1")]})});
    assert.equal(box.engine.seenCount(), 0);
    assert.equal((await box.engine.check()).length, 1);
  }

  // 8) 已读记录有界：不会把 localStorage 撑爆
  {
    const many = Array.from({length: 900}, (_, i) => `flag:old:${i}`);
    const box = harness({storage: {"ss.notify.seen": JSON.stringify(many)},
      fetchItems: async () => ({items: [solved("new")]})});
    await box.engine.check();
    const stored = JSON.parse(box.storage.getItem("ss.notify.seen"));
    assert.ok(stored.length <= 400, `已读记录应封顶，实际 ${stored.length}`);
    assert.equal(stored[stored.length - 1], "flag:sess-a:new");
  }

  // 9) 设置页的「发一条测试通知」按权限如实反馈
  {
    const granted = harness({permission: "granted"});
    assert.equal(granted.engine.selfTest(), true);
    const blocked = harness({permission: "default"});
    assert.equal(blocked.engine.selfTest(), false);
    assert.equal(blocked.toasts.length, 1);
  }

  console.log('notify: system notification, dedupe, focus-click, fallback toast, '
    + 'current-session quiet, switch, corrupt storage, bounded seen and self-test passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
