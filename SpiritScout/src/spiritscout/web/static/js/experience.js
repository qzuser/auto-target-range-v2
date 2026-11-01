/* 经验列表、来源会话和提炼记录。 */
const ExperiencePage = (() => {
  const state = {items: [], offset: 0, q: "", tag: "", generation: 0, more: false, total: 0};
  const root = () => $("#view-exp");
  const time = t => t ? new Date(t * 1000).toLocaleString("zh-CN", {hour12: false}) : "未记录";

  function shell() {
    const el = root();
    if (el.dataset.ready) return;
    el.dataset.ready = "yes";
    el.innerHTML = `
      <header class="resource-head">
        <div>
          <h2>经验提炼</h2>
          <p>查看会话提炼的经验、适用场景和来源；不合适的条目可以删除。</p>
        </div>
        <div class="resource-head-actions"><button class="btn" data-refresh>刷新</button></div>
      </header>
      <div class="exp-tiles" data-tiles></div>
      <div class="exp-toolbar">
        <label class="resource-search">搜索经验<input type="search" data-search placeholder="内容、场景或标签…" maxlength="100"></label>
        <div class="exp-tags" data-tags role="group" aria-label="按标签过滤"></div>
      </div>
      <div class="exp-layout">
        <section aria-label="经验列表">
          <div class="resource-list-status" data-status role="status"></div>
          <div class="exp-list" data-list></div>
          <button class="btn resource-more" data-more hidden>加载更多</button>
        </section>
        <aside class="exp-history" aria-label="提炼过程记录">
          <h3>提炼记录</h3>
          <p class="exp-history-note">查看各次提炼的结果和失败原因。</p>
          <div data-hist></div>
        </aside>
      </div>`;
    el.querySelector("[data-refresh]").onclick = () => load(true);
    let timer;
    el.querySelector("[data-search]").oninput = e => {
      state.q = e.target.value.trim();
      clearTimeout(timer);
      timer = setTimeout(() => load(), 250);
    };
    el.querySelector("[data-more]").onclick = () => load(false, true);
  }

  async function load(resetTags = false, append = false) {
    shell();
    if (resetTags) state.tag = "";
    const version = ++state.generation;
    const status = root().querySelector("[data-status]");
    if (!append) status.textContent = "正在读取…";
    try {
      const params = {limit: "40", offset: append ? String(state.offset) : "0"};
      if (state.q) params.q = state.q;
      if (state.tag) params.tag = state.tag;
      const data = await api("/api/experience?" + new URLSearchParams(params));
      if (version !== state.generation) return;
      state.items = append ? [...state.items, ...(data.items || [])] : (data.items || []);
      state.offset = state.items.length;
      state.more = !!data.has_more;
      state.total = data.total || 0;
      state.stats = data;
      status.textContent = state.total
        ? `${state.total} 条经验`
        : (state.q || state.tag ? "没有匹配的经验，请更换关键词或标签。" : "");
      render(data);
    } catch (e) {
      status.textContent = `读取失败：${e.message}。点击刷新重试。`;
    }
  }

  function render(data) {
    const el = root();
    renderTiles(data);
    renderTags(data);
    renderList(data);
    renderHistory(data.history || []);
  }

  function renderTiles(data) {
    const last = data.last_ts ? time(data.last_ts).slice(5, 16) : "—";
    root().querySelector("[data-tiles]").innerHTML = `
      <div class="exp-tile"><span>经验</span><b>${Number(data.total || 0).toLocaleString("zh-CN")}</b><small>筛选结果</small></div>
      <div class="exp-tile"><span>来源会话</span><b>${Number(data.sources || 0).toLocaleString("zh-CN")}</b></div>
      <div class="exp-tile"><span>标签</span><b>${(data.tags || []).length}</b></div>
      <div class="exp-tile"><span>最近提炼</span><b class="exp-tile-time">${esc(last)}</b></div>`;
  }

  function renderTags(data) {
    const box = root().querySelector("[data-tags]");
    const tags = data.tags || [];
    const chips = [`<button class="resource-chip ${!state.tag ? "on" : ""}" data-tag="">全部</button>`];
    for (const t of tags.slice(0, 18))
      chips.push(`<button class="resource-chip ${state.tag === t.tag ? "on" : ""}" data-tag="${esc(t.tag)}">${esc(t.tag)} ${t.count}</button>`);
    box.innerHTML = chips.join("");
    box.querySelectorAll("[data-tag]").forEach(b => b.onclick = () => {
      state.tag = b.dataset.tag || "";
      load();
    });
  }

  function renderList() {
    const box = root().querySelector("[data-list]");
    box.innerHTML = state.items.map(item => {
      const tags = (item.tags || []).map(t => `<span class="exp-ins-tag">${esc(t)}</span>`).join("");
      const sid = String(item.source_session || "");
      const known = sid.startsWith("sess-") && (S.sessions || []).some(s => s.session_id === sid);
      const source = sid
        ? (known
          ? `<button class="exp-source" data-open-session="${esc(sid)}" title="打开来源会话">${esc(item.source_title || sid)}</button>`
          : `<span class="exp-source muted">${esc(item.source_title || sid)}</span>`)
        : `<span class="exp-source muted">来源未记录</span>`;
      const iid = String(item.insight_id || "");
      return `<article class="exp-card">
        <div class="exp-card-tags">${tags || '<span class="exp-ins-tag muted">未打标签</span>'}</div>
        <p class="exp-insight">${esc(item.insight || "")}</p>
        ${item.context ? `<p class="exp-context">适用：${esc(item.context)}</p>` : ""}
        <footer>${source}<span class="exp-card-ops">
          <span class="exp-meta">${esc(item.source_model || "")} · ${esc(time(item.ts))}</span>
          ${iid ? `<button class="btn exp-del" data-del="${esc(iid)}" title="删除这条经验">删除</button>` : ""}
        </span></footer>
      </article>`;
    }).join("") || (state.q || state.tag ? "" : `
      <div class="resource-empty">
        暂无经验
        <p>会话结束后自动提炼，可在「提炼记录」查看处理进度。</p>
      </div>`);
    box.querySelectorAll("[data-open-session]").forEach(b =>
      b.onclick = () => openSession(b.dataset.openSession));
    box.querySelectorAll("[data-del]").forEach(b =>
      b.onclick = () => armConfirm(b, () => removeItem(b.dataset.del)));
    root().querySelector("[data-more]").hidden = !state.more;
  }

  /* 人工审核删除：本地就地移除并修正统计，服务端在系统审计留痕 */
  async function removeItem(id) {
    try {
      await api(`/api/experience/${encodeURIComponent(id)}`, {method: "DELETE"});
      state.items = state.items.filter(it => String(it.insight_id || "") !== id);
      state.offset = state.items.length;
      state.total = Math.max(0, (state.total || 1) - 1);
      if (state.stats) state.stats.total = state.total;
      renderTiles(state.stats || {});
      renderList();
      const status = root().querySelector("[data-status]");
      status.textContent = state.total
        ? `${state.total} 条经验`
        : (state.q || state.tag ? "没有匹配的经验，请更换关键词或标签。" : "");
      toast("已删除这条经验");
    } catch (e) { toast(e.message, true); }
  }

  function renderHistory(rows) {
    const box = root().querySelector("[data-hist]");
    const label = {ok: ["成功", "ok"], empty: ["无新增经验", "empty"], error: ["失败", "error"], skipped: ["跳过", "skipped"]};
    box.innerHTML = rows.map(h => {
      const [text, cls] = label[h.result] || [h.result || "未知", ""];
      const sid = String(h.session_id || "");
      const known = sid.startsWith("sess-") && (S.sessions || []).some(s => s.session_id === sid);
      return `<article class="exp-hist-row ${cls}">
        <header>
          <span class="exp-hist-badge">${esc(text)}</span>
          ${known ? `<button class="exp-source" data-open-session="${esc(sid)}">${esc(sid)}</button>` : `<span class="muted mono">${esc(sid)}</span>`}
          <small>${esc((h.ts || "").replace("T", " ").slice(0, 19))}</small>
        </header>
        <p>${esc(h.outcome || "")}${h.insights ? ` · 新增 ${h.insights} 条` : ""}${h.error ? ` · ${esc(h.error)}` : ""}</p>
      </article>`;
    }).join("") || `<p class="muted">暂无提炼记录，会话结束后可在这里查看。</p>`;
    box.querySelectorAll("[data-open-session]").forEach(b =>
      b.onclick = () => openSession(b.dataset.openSession));
  }

  function open() {
    shell();
    refreshSessions?.();
    load(true);
  }

  return {open, load};
})();

/* 会话页「经验」页签：这次会话产出了哪些经验，没有就手动补一次。
   数据源是 /api/sessions/<id>/experience；手动提炼与收尾提炼共用同一段
   提示词，结果照实显示（ok / empty / unparsed / error 各是各的）。 */
const SessionExperience = (() => {
  const FRESH_MS = 20000;
  const state = {session: "", items: [], history: [], view: null, at: 0, busy: false};
  const stamp = t => t ? new Date(t * 1000).toLocaleString("zh-CN", {hour12: false}) : "未记录";
  const root = () => $("#tab-experience");

  function shell() {
    const el = root();
    if (!el || el.dataset.ready) return el;
    el.dataset.ready = "yes";
    el.innerHTML = `
      <header class="exp-head">
        <div>
          <h3>这次产出的经验</h3>
          <p data-state role="status">正在读取…</p>
        </div>
        <div class="exp-head-ops">
          <button class="btn primary" type="button" data-distill>手动提炼</button>
          <button class="btn sm" type="button" data-refresh>刷新</button>
        </div>
      </header>
      <div class="exp-layout">
        <section aria-label="本次会话的经验">
          <div class="exp-list" data-list></div>
        </section>
        <aside class="exp-history" aria-label="提炼记录">
          <h3>提炼记录</h3>
          <p class="exp-history-note">自动提炼在会话收尾时跑；这里也会出现手动提炼。</p>
          <div data-hist></div>
        </aside>
      </div>`;
    el.querySelector("[data-refresh]").onclick = () => load(S.cur, true);
    el.querySelector("[data-distill]").onclick = () => distill();
    return el;
  }

  const badge = {ok: ["成功", "ok"], empty: ["无新增经验", "empty"],
                 unparsed: ["没按格式返回", "skip"], error: ["失败", "error"],
                 skipped: ["跳过", "skipped"]};
  const triggerName = h => (String(h.trigger || "auto") === "manual" ? "手动" : "自动");

  function render() {
    const el = shell();
    if (!el) return;
    const view = state.view || {};
    const items = state.items || [], history = state.history || [];
    const canDistill = !!view.state?.can_distill;      // 没读到数据前一律不可点
    const button = el.querySelector("[data-distill]");
    const distilling = state.busy || !!view.state?.distilling;
    button.disabled = distilling || !canDistill;
    button.textContent = distilling ? "正在提炼…" : "手动提炼";
    const reason = String(view.state?.reason || "");
    el.querySelector("[data-state]").textContent = !state.session
      ? "先选一个会话"
      : (items.length ? `本次产出 ${items.length} 条经验` : "这次还没有提炼出经验")
        + (distilling ? " · 正在提炼" : "")
        + (reason && !distilling ? ` · ${reason}` : "");

    el.querySelector("[data-list]").innerHTML = items.map(item => {
      const tags = (item.tags || []).map(t => `<span class="exp-ins-tag">${esc(t)}</span>`).join("");
      const iid = String(item.insight_id || "");
      return `<article class="exp-card">
        <div class="exp-card-tags">${tags || '<span class="exp-ins-tag muted">未打标签</span>'}</div>
        <p class="exp-insight">${esc(item.insight || "")}</p>
        ${item.context ? `<p class="exp-context">适用：${esc(item.context)}</p>` : ""}
        <footer><span class="exp-meta">${esc(item.source_model || "")} · ${esc(stamp(item.ts))}</span>
          <span class="exp-card-ops">${iid ? `<button class="btn exp-del" type="button" data-del="${esc(iid)}" title="删除这条经验">删除</button>` : ""}</span>
        </footer>
      </article>`;
    }).join("") || `<div class="resource-empty">
        这次还没有经验
        <p>${reason ? esc(reason) : "会话收尾会自动提炼；也可以点右上角「手动提炼」现在补一次。"}</p>
      </div>`;
    el.querySelectorAll("[data-del]").forEach(b =>
      b.onclick = () => armConfirm(b, () => removeItem(b.dataset.del)));

    el.querySelector("[data-hist]").innerHTML = history.map(h => {
      const [text, cls] = badge[h.result] || [h.result || "未知", ""];
      const extra = [h.insights ? `新增 ${h.insights} 条` : "",
                     h.error ? esc(h.error) : ""].filter(Boolean).join(" · ");
      return `<article class="exp-hist-row ${cls}">
        <header><span class="exp-hist-badge">${esc(text)}</span>
          <small>${esc(String(h.ts || "").replace("T", " ").slice(0, 19))}</small></header>
        <p>${esc(triggerName(h))} · ${esc(h.outcome || "—")}${extra ? ` · ${extra}` : ""}</p>
      </article>`;
    }).join("") || `<p class="muted">还没有提炼记录。会话收尾时自动提炼，失败原因也会记在这里。</p>`;
  }

  function apply(data) {
    state.view = data;
    state.items = data.items || [];
    state.history = data.history || [];
    state.at = Date.now();
    render();
  }

  async function load(sessionId, force = false) {
    if (!sessionId) { state.session = ""; state.items = []; render(); return; }
    if (!force && state.session === sessionId && Date.now() - state.at < FRESH_MS) return;
    state.session = sessionId;
    shell();
    try {
      const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/experience`);
      if (S.cur !== sessionId) return;          // 换了会话：这轮结果作废
      apply(data);
    } catch (e) {
      const el = root();
      if (el) el.querySelector("[data-state]").textContent = `读取失败：${e.message}`;
    }
  }

  async function distill() {
    const sessionId = S.cur;
    if (!sessionId || state.busy) return;
    state.busy = true;
    render();
    try {
      const data = await api(`/api/sessions/${encodeURIComponent(sessionId)}/experience/distill`,
                             {method: "POST"});
      if (S.cur !== sessionId) return;
      state.busy = false;
      apply({...data, state: (state.view?.state || {})});
      const added = Number(data.insights || 0);
      if (data.result === "ok") toast(`提炼完成，新增 ${added} 条经验`);
      else if (data.result === "empty") toast("这次没有值得沉淀的新经验");
      else if (data.result === "unparsed") toast("模型没按格式返回，本次没有新增经验", true);
      else toast(data.error || "提炼失败，原因已记在提炼记录里", true);
      await load(sessionId, true);              // 结论行要以服务端口径为准
    } catch (e) {
      state.busy = false;
      render();
      toast(e.message, true);
    }
  }

  async function removeItem(id) {
    try {
      await api(`/api/experience/${encodeURIComponent(id)}`, {method: "DELETE"});
      state.items = state.items.filter(it => String(it.insight_id || "") !== id);
      render();
      toast("已删除这条经验");
    } catch (e) { toast(e.message, true); }
  }

  function refreshIfStale() {
    if (!S.cur || state.session !== S.cur) return;
    if (state.busy) return;
    load(S.cur);
  }

  function reset() {
    state.session = "";
    state.items = [];
    state.history = [];
    state.view = null;
    state.at = 0;
    state.busy = false;
  }

  return {load, refreshIfStale, reset, distill};
})();
