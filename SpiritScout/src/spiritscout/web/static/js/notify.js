"use strict";
/* 控制台提醒：解出题、灵枢需要你拍板时，弹一条系统通知。
   做成注入式工厂，node 里能脱离浏览器跑单测（见 tests/test_notify.js）。

   设计取舍：
   * 服务端只回答「此刻有什么值得提醒」，已读留在浏览器（localStorage），
     所以多标签页、刷新页面都不会重复响；
   * 系统通知发不出去（没授权 / 浏览器不支持）就退化成页面内 toast 加标题
     计数，不静默——最怕的是「以为它在提醒你」；
   * 正看着那个会话、且页面在前台时不弹通知：屏幕上已经有提问卡或结果，
     再弹一次是骚扰。 */
const ConsoleNotify = (() => {
  const ENABLED_KEY = "ss.notify.enabled", SEEN_KEY = "ss.notify.seen", SEEN_MAX = 400;
  /* 一轮最多弹几条：隔一天回来可能有十几条积压，一次性糊一屏通知不如折成
     三条加一句「还有 N 条」，剩下的在控制台里逐条看 */
  const MAX_BURST = 3;
  const KIND_TITLE = {solved: "解出一道题", question: "灵枢在等你回答"};
  const PERM_CN = {granted: "已允许", denied: "已被浏览器拒绝", default: "尚未授权",
                   unsupported: "此浏览器不支持"};

  function create(deps) {
    const {fetchItems, storage, notifyCtor, doc, win, toastFn,
           isCurrent = () => false, openSession = () => {}} = deps;
    const baseTitle = String(doc.title || "");
    let seen = loadSeen(), flashCount = 0, lastItems = [], lastCounts = {};

    function loadSeen() {
      try {
        const raw = JSON.parse(storage.getItem(SEEN_KEY) || "[]");
        return new Set(Array.isArray(raw) ? raw.filter(x => typeof x === "string") : []);
      } catch { return new Set(); }
    }
    function persistSeen() {
      try {
        // 有界：只留最近的一批 id，读不出来的旧记录不重要——服务端只会推
        // 当前还在的条目，太老的 id 不会再来
        storage.setItem(SEEN_KEY, JSON.stringify([...seen].slice(-SEEN_MAX)));
      } catch { /* 隐私模式写不进去：这一轮照常提醒，只是下次会重复 */ }
    }
    function enabled() { return storage.getItem(ENABLED_KEY) !== "off"; }
    function setEnabled(on) {
      try { storage.setItem(ENABLED_KEY, on ? "on" : "off"); } catch {}
    }
    function permission() {
      return notifyCtor && typeof notifyCtor.permission === "string"
        ? notifyCtor.permission : "unsupported";
    }
    function requestPermission() {
      if (!notifyCtor || typeof notifyCtor.requestPermission !== "function") {
        return Promise.resolve("unsupported");
      }
      return Promise.resolve(notifyCtor.requestPermission()).catch(() => permission());
    }
    function bodyOf(item) {
      const body = String(item.body || "").trim();
      const name = String(item.session_title || "").trim();
      if (body && name) return `${body}（${name}）`;
      return body || name || "点击查看详情";
    }
    function raise(item) {
      const title = KIND_TITLE[item.kind] || String(item.title || "灵枢");
      const body = bodyOf(item);
      if (permission() === "granted") {
        try {
          const note = new notifyCtor(title, {body, tag: item.id});
          note.onclick = () => {
            try { win.focus(); } catch {}
            openSession(item.session_id);
            if (typeof note.close === "function") note.close();
          };
          return "system";
        } catch { /* 构造失败就落到页面内提示 */ }
      }
      toastFn(`${title}：${body}`);
      flash();
      return "inline";
    }
    function flash() {
      flashCount += 1;
      doc.title = `(${flashCount}) ${baseTitle}`;
    }
    function clearFlash() {
      if (!flashCount) return;
      flashCount = 0;
      doc.title = baseTitle;
    }
    async function check() {
      let data;
      try { data = await fetchItems(); } catch { return []; }
      const items = data && Array.isArray(data.items) ? data.items : [];
      lastItems = items;
      lastCounts = (data && data.counts) || {};
      const fresh = items.filter(item => item && typeof item.id === "string"
        && !seen.has(item.id));
      for (const item of fresh) seen.add(item.id);
      const raised = [];
      let overflow = 0;
      for (const item of fresh) {
        if (!enabled()) continue;
        if (isCurrent(item.session_id) && doc.visibilityState === "visible") continue;
        if (raised.length >= MAX_BURST) { overflow += 1; continue; }
        if (raise(item)) raised.push(item);
      }
      if (overflow) {
        // 汇总条不进 seen：它只是个计数，条目本身各自已经记过了
        const note = raise({id: "burst", kind: "burst", session_id: "",
          title: "还有几条提醒",
          body: `另有 ${overflow} 条提醒，点开控制台逐条看`});
        if (note) raised.push({kind: "burst", overflow});
      }
      /* 无论有没有真弹出来都记已读：开关关着、页面正看着的时候也不该攒着，
         等打开了再一股脑补一遍历史提醒。 */
      if (fresh.length) persistSeen();
      return raised;
    }
    function selfTest() {
      return raise({id: "selftest", kind: "question", session_id: "",
                    session_title: "", title: KIND_TITLE.question,
                    body: "这是一条测试通知：以后解出题或需要你回答时会这样提醒。"})
        === "system";
    }
    function clearSeen() {
      seen = new Set();
      persistSeen();
    }
    return {check, enabled, setEnabled, permission, requestPermission,
            clearFlash, flashCount: () => flashCount, selfTest, clearSeen,
            items: () => lastItems.slice(), counts: () => ({...lastCounts}),
            seenCount: () => seen.size, baseTitle};
  }

  /* ---------------- 浏览器侧接线 ---------------- */
  let instance = null;
  function init() {
    if (instance) return instance;
    instance = create({
      fetchItems: () => api("/api/notifications"),
      storage: window.localStorage,
      notifyCtor: window.Notification,
      doc: document,
      win: window,
      toastFn: msg => toast(msg),
      isCurrent: id => S.view === "session" && !!S.cur && S.cur === id,
      openSession: id => { if (id) openSession(id); },
    });
    // 回到页面就撤掉标题上的计数：人已经看见了
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") instance.clearFlash();
    });
    window.addEventListener("focus", () => instance.clearFlash());
    return instance;
  }
  function check() { return init().check(); }
  function clearFlash() { if (instance) instance.clearFlash(); }

  function permissionText(state) { return PERM_CN[state] || state; }

  /* 「最近提醒」那一行：把快照里最新几条压成一句话，设置页才看得出真有什么 */
  function briefOf(item) {
    const body = String((item && item.body) || "").trim();
    const name = String((item && item.session_title) || "").trim();
    const text = body && name ? `${body}（${name}）` : (body || name || "点击查看");
    const kind = (item && (KIND_TITLE[item.kind] || item.title)) || "提醒";
    return `${kind}：${text}`;
  }

  function render(root, ctl) {
    root.innerHTML = `<div class="set-card">
      <h2>通知</h2>
      <p class="muted">解出一道题、或灵枢卡在需要你拍板的问题上时，弹一条系统通知——
        页面在后台、甚至切到别的窗口也能收到。</p>
      <dl class="set-facts">
        <div><dt>系统权限</dt><dd data-notify-perm>—</dd></div>
        <div><dt>提醒开关</dt><dd data-notify-switch>—</dd></div>
        <div><dt>待提醒</dt><dd data-notify-pending>—</dd></div>
        <div><dt>已读记录</dt><dd data-notify-seen>—</dd></div>
      </dl>
      <p class="set-note" data-notify-recent>—</p>
      <label class="set-check"><input type="checkbox" data-notify-toggle> 解出题目或需要我回答时提醒我</label>      <div class="set-about-actions">
        <button class="btn primary" type="button" data-notify-allow>允许系统通知</button>
        <button class="btn" type="button" data-notify-test>发一条测试通知</button>
        <button class="btn" type="button" data-notify-clear>清空已读记录</button>
      </div>
      <p class="set-note" data-notify-note></p>
    </div>`;
    const box = root.querySelector("[data-notify-toggle]");
    box.checked = ctl.enabled();
    box.onchange = () => {
      ctl.setEnabled(box.checked);
      paint();
      if (box.checked && ctl.permission() === "default") {
        ctl.requestPermission().then(paint);
      }
    };
    root.querySelector("[data-notify-allow]").onclick = async event => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        const state = await ctl.requestPermission();
        if (state === "granted") ctl.selfTest();
      } finally { button.disabled = false; paint(); }
    };
    root.querySelector("[data-notify-test]").onclick = () => {
      if (!ctl.selfTest()) toast("通知被浏览器拦下了，检查系统通知设置", true);
    };
    root.querySelector("[data-notify-clear]").onclick = () => { ctl.clearSeen(); paint(); };

    function paint() {
      const perm = ctl.permission(), counts = ctl.counts();
      root.querySelector("[data-notify-perm]").textContent =
        permissionText(perm) + (perm === "default" ? "（点下面按钮申请）"
          : perm === "denied" ? "（到地址栏的站点设置里改）" : "");
      root.querySelector("[data-notify-switch]").textContent =
        ctl.enabled() ? "已开启" : "已关闭";
      const solved = Number(counts.solved || 0), asked = Number(counts.question || 0);
      root.querySelector("[data-notify-pending]").textContent =
        `解出 ${solved} 条 · 待答 ${asked} 条`;
      root.querySelector("[data-notify-seen]").textContent = `${ctl.seenCount()} 条已提醒`;
      const recent = ctl.items().slice(0, 3).map(briefOf);
      root.querySelector("[data-notify-recent]").textContent = recent.length
        ? `最近：${recent.join("；")}` : "最近还没有需要提醒的事。";
      root.querySelector("[data-notify-note]").textContent = perm === "granted"
        ? "系统通知已可用。点「发一条测试通知」看效果；正看着某个会话时不会重复弹。"
        : "浏览器没给通知权限时会退化成页面内提示 + 标签页标题计数，不会漏掉。";
      box.checked = ctl.enabled();
    }
    return paint;
  }

  let painter = null;
  function open() {
    const engine = init();
    const root = $("#view-notify");
    if (!root) return;
    if (!painter) painter = render(root, engine);
    painter();
    // 进设置页顺手拉一次：「待提醒」显示的是此刻的状态，不是上次轮询的旧数
    engine.check().then(() => { if (painter) painter(); }).catch(() => {});
  }

  return {create, init, check, open, clearFlash, brief: briefOf};
})();
