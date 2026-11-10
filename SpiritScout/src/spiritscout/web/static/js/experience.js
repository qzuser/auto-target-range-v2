/* 经验列表、来源会话和提炼记录。
   二次提炼：先把「极相似」的条目提炼成一条稿子，用户确认保留后才把稿子写入经验库、
   并删除被提炼的原件。相似度阈值页面上可改，默认 90%。 */
const ExperiencePage = (() => {
  const THRESHOLD_KEY = "ss.exp.mergeThreshold";   // 记住上次用的相似度
  const THRESHOLD_DEFAULT = 90;                    // 与后端默认值一致：九成相似
  const THRESHOLD_MIN = 50;
  const THRESHOLD_MAX = 100;
  const PAGE_SIZE = 200;      // 拉全量时的分页块大小（后端上限 500）

  function readThreshold() {
    try {
      const raw = Number(window.localStorage.getItem(THRESHOLD_KEY));
      if (Number.isFinite(raw) && raw >= THRESHOLD_MIN && raw <= THRESHOLD_MAX)
        return Math.round(raw);
    } catch (e) { /* 隐私模式下没有 localStorage：用默认值，不影响功能 */ }
    return THRESHOLD_DEFAULT;
  }

  const state = {items: [], offset: 0, q: "", tag: "", generation: 0, more: false,
                 total: 0, merged: false, mergeOn: false, absorbOn: false,
                 picks: new Set(), groups: [], allItems: [], allLoaded: false,
                 absorbPlan: null, threshold: readThreshold(), preview: null};
  const root = () => $("#view-exp");
  const time = t => t ? new Date(t * 1000).toLocaleString("zh-CN", {hour12: false}) : "未记录";

  /* 阈值按百分比存，发给后端时换成 0.5–1.0 的比例 */
  const clampPercent = value => {
    const n = Number(value);
    if (!Number.isFinite(n)) return THRESHOLD_DEFAULT;
    return Math.min(THRESHOLD_MAX, Math.max(THRESHOLD_MIN, Math.round(n)));
  };
  const thresholdRatio = () => clampPercent(state.threshold) / 100;

  function shell() {
    const el = root();
    if (el.dataset.ready) return;
    el.dataset.ready = "yes";
    el.innerHTML = `
      <header class="resource-head">
        <div>
          <h2>经验提炼</h2>
          <p>查看会话提炼的经验、适用场景和来源；极其相似的可以二次提炼成一条，不合适的条目可以删除。</p>
        </div>
        <div class="resource-head-actions">
          <button class="btn" data-merge-toggle title="把极其相似的经验提炼成一条">二次提炼</button>
          <button class="btn" data-absorb-toggle title="交给 AI 判断能不能并进已有的某条经验（不删任何经验）">合并</button>
          <button class="btn" data-merged-toggle hidden title="显示被合并的原件">显示已合并</button>
          <button class="btn" data-sync-pull title="从仓库远端把经验拉回本地：只补缺，不改也不删本地条目">拉取</button>
          <button class="btn" data-sync-push title="把本地经验导出到仓库并提交推送">提交</button>
          <button class="btn" data-refresh>刷新</button>
        </div>
      </header>
      <div class="exp-tiles" data-tiles></div>
      <div class="exp-toolbar">
        <label class="resource-search">搜索经验<input type="search" data-search placeholder="内容、场景或标签…" maxlength="100"></label>
        <div class="exp-tags" data-tags role="group" aria-label="按标签过滤"></div>
      </div>
      <section class="exp-merge" data-merge-panel hidden aria-label="二次提炼"></section>
      <section class="exp-merge exp-absorb" data-absorb-panel hidden aria-label="合并"></section>
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
    el.querySelector("[data-sync-pull]").onclick = () => syncPull();
    el.querySelector("[data-sync-push]").onclick = () => syncPush();
    el.querySelector("[data-merge-toggle]").onclick = () => toggleMerge();
    el.querySelector("[data-absorb-toggle]").onclick = () => toggleAbsorb();
    el.querySelector("[data-merged-toggle]").onclick = () => {
      state.merged = !state.merged;
      state.picks.clear();
      load();
    };
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
    if (!append) { state.allItems = []; state.allLoaded = false; }   // 筛选变了，全量缓存作废
    const status = root().querySelector("[data-status]");
    if (!append) status.textContent = "正在读取…";
    try {
      const params = {limit: "40", offset: append ? String(state.offset) : "0"};
      if (state.q) params.q = state.q;
      if (state.tag) params.tag = state.tag;
      if (state.merged) params.include_merged = "true";
      const data = await api("/api/experience?" + new URLSearchParams(params));
      if (version !== state.generation) return;
      state.items = append ? [...state.items, ...(data.items || [])] : (data.items || []);
      state.offset = state.items.length;
      state.more = !!data.has_more;
      state.total = data.total || 0;
      state.mergedTotal = data.merged_total || 0;
      state.stats = data;
      status.textContent = state.total
        ? `${state.total} 条经验`
        : (state.q || state.tag ? "没有匹配的经验，请更换关键词或标签。" : "");
      render(data);
    } catch (e) {
      status.textContent = `读取失败：${e.message}。点击刷新重试。`;
    }
  }

  /* ---- 跨机器同步：拉取（远端 → 本地，只补缺）/ 提交（本地 → 仓库 → 远端） ---- */

  /* 按钮忙着的时候给个可见状态，别让人以为没点动 */
  async function withBusy(selector, busyText, work) {
    const btn = root().querySelector(selector);
    const label = btn ? btn.textContent : "";
    if (btn) { btn.disabled = true; btn.textContent = busyText; }
    try {
      return await work();
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = label; }
    }
  }

  async function syncPull() {
    await withBusy("[data-sync-pull]", "拉取中…", async () => {
      try {
        const data = await api("/api/experience/sync/pull", {method: "POST"});
        toast(`已从 ${data.branch} 拉取：新增 ${data.added} 条，本地已有 ${data.skipped} 条跳过`);
        await load(true);
      } catch (e) {
        toast(`拉取失败：${e.message}`, true);
      }
    });
  }

  async function syncPush() {
    const total = Number(state.total || 0);
    if (!window.confirm(`把本地 ${total || ""} 条经验提交到仓库并推送？\n（写成你自己一个文件放进 inbox，不动别人的提交）`))
      return;
    await withBusy("[data-sync-push]", "提交中…", async () => {
      try {
        const data = await api("/api/experience/sync/push", {
          method: "POST", body: JSON.stringify({})});
        toast(`已提交 ${data.count} 条经验到 ${data.branch}：${data.file}`);
      } catch (e) {
        toast(`提交失败：${e.message}`, true);
      }
    });
  }

  /* ---- 二次提炼：候选 → 提炼稿 → 用户确认保留才入库并删原件 ---- */

  function toggleMerge() {
    state.mergeOn = !state.mergeOn;
    state.picks.clear();
    state.preview = null;
    if (!state.mergeOn) state.groups = [];
    if (state.mergeOn) { state.absorbOn = false; state.absorbPlan = null; }
    renderMergePanel();
    renderAbsorbPanel();
    renderList();
    if (state.mergeOn) {
      loadGroups();
      ensureAllItems().then(() => { renderMergePanel(); renderList(); }).catch(() => {});
    }
  }

  /* ---- 合并：交给模型判断能不能并进已有的一条，只更新目标条目、不删任何经验 ---- */

  function toggleAbsorb() {
    state.absorbOn = !state.absorbOn;
    state.picks.clear();
    state.absorbPlan = null;
    if (state.absorbOn) { state.mergeOn = false; state.groups = []; state.preview = null; }
    renderMergePanel();
    renderAbsorbPanel();
    renderList();
    if (state.absorbOn) {
      ensureAllItems().then(() => { renderAbsorbPanel(); renderList(); }).catch(() => {});
    }
  }

  function setThreshold(value) {
    state.threshold = clampPercent(value);
    try { window.localStorage.setItem(THRESHOLD_KEY, String(state.threshold)); }
    catch (e) { /* 存不了就只在本次记住 */ }
    state.preview = null;
    return loadGroups();
  }

  async function loadGroups() {
    try {
      const data = await api(
        `/api/experience/merge/candidates?threshold=${thresholdRatio()}`);
      state.groups = data.groups || [];
      state.groupsError = "";
    } catch (e) {
      state.groups = [];
      state.groupsError = e.message;
    }
    renderMergePanel();
  }

  /* 可提炼/可合并的条目：库里有 id、且不是「已合并」的历史原件。
     列表本身是分页的（40 条一处），但「全选」不能只勾到当前这页——进入提炼或
     合并时先把整库按 PAGE_SIZE 拉全，页面上的条数说明才是真数。 */
  function mergeable() {
    const source = state.allLoaded ? state.allItems : state.items;
    return (source || []).filter(it => String(it.insight_id || "") && !it.merged);
  }

  /* 拉全量（只读、按当前筛选条件），已经拉过就直接返回 */
  async function ensureAllItems() {
    if (state.allLoaded) return state.allItems;
    const params = {limit: String(PAGE_SIZE), offset: "0"};
    if (state.q) params.q = state.q;
    if (state.tag) params.tag = state.tag;
    if (state.merged) params.include_merged = "true";
    const out = [];
    let guard = 0;
    while (guard++ < 200) {
      params.offset = String(out.length);
      const data = await api("/api/experience?" + new URLSearchParams(params));
      const page = data.items || [];
      out.push(...page);
      if (!data.has_more || page.length === 0) break;
    }
    state.allItems = out;
    state.allLoaded = true;
    return out;
  }

  /* 全选 / 取消全选：勾上**整库**可提炼的条目，不是只勾当前这页 */
  async function togglePickAll(checked) {
    if (!checked) {
      state.picks = new Set();
      renderMergePanel();
      renderAbsorbPanel();
      renderList();
      return;
    }
    try {
      await ensureAllItems();
    } catch (e) {
      toast(`读取全部经验失败：${e.message}`, true);
      return;
    }
    state.picks = new Set(mergeable().map(it => String(it.insight_id)));
    renderMergePanel();
    renderAbsorbPanel();
    renderList();
  }

  function renderMergePanel() {
    const box = root().querySelector("[data-merge-panel]");
    const toggle = root().querySelector("[data-merge-toggle]");
    toggle?.classList?.toggle("on", state.mergeOn);
    const mergedBtn = root().querySelector("[data-merged-toggle]");
    if (mergedBtn) mergedBtn.hidden = !(state.merged || (state.mergedTotal || 0) > 0);
    mergedBtn?.classList?.toggle("on", state.merged);
    if (!box) return;
    box.hidden = !state.mergeOn;
    if (!state.mergeOn) { box.innerHTML = ""; return; }
    const groups = state.groups || [];
    const percent = clampPercent(state.threshold);
    const rows = groups.map(group => {
      const ids = (group.ids || []).join(",");
      const items = (group.items || []).map(item =>
        `<li>${esc(item.insight || "")}</li>`).join("");
      return `<article class="exp-merge-group">
        <header>
          <span class="exp-merge-score">相似度 ${Math.round((group.score || 0) * 100)}%</span>
          <span class="muted">${(group.items || []).length} 条</span>
        </header>
        <ul class="exp-merge-items">${items}</ul>
        <button class="btn" data-merge-ids="${esc(ids)}" title="把这 ${(group.items || []).length} 条提炼成一条，先看结果再决定要不要保留">提炼这 ${(group.items || []).length} 条</button>
      </article>`;
    }).join("");
    const all = mergeable();
    const picks = [...state.picks].filter(id => all.some(it => String(it.insight_id) === id));
    const preview = state.preview;
    const previewCard = preview ? `
      <section class="exp-merge-draft" data-preview>
        <header>
          <h4>提炼结果（还没入库）</h4>
          <span class="exp-merge-score">相似度 ${Math.round((preview.score || 0) * 100)}%</span>
        </header>
        <p class="exp-merge-draft-insight">${esc(preview.insight || "")}</p>
        ${preview.context ? `<p class="exp-merge-preview">适用：${esc(preview.context)}</p>` : ""}
        <p class="muted">保留后这条会写进经验库，被提炼的 ${(preview.ids || []).length} 条原件随即删除；不保留就什么都不动。</p>
        <div class="exp-merge-draft-ops">
          <button class="btn primary" data-preview-keep>保留并删除 ${(preview.ids || []).length} 条原件</button>
          <button class="btn" data-preview-cancel>放弃</button>
        </div>
      </section>` : "";
    box.innerHTML = `
      <header class="exp-merge-head">
        <h3>二次提炼</h3>
        <p>只提炼<span class="exp-merge-th">极度相似（≥ ${percent}%）</span>的经验：
           先出提炼稿，<b>你确认保留</b>后才写进经验库并删除被提炼的原件。</p>
        <div class="exp-merge-threshold">
          <label>相似度
            <input type="number" data-threshold min="${THRESHOLD_MIN}" max="${THRESHOLD_MAX}"
                   step="1" value="${percent}" inputmode="numeric"> %
          </label>
          <button class="btn sm" data-threshold-apply>重新查询</button>
          <span class="muted">默认 90%，调低会捞到更多候选，调高只留几乎一样的。</span>
        </div>
      </header>
      ${previewCard}
      <div class="exp-merge-groups" data-groups>${rows || `<p class="muted">${state.groupsError ? `读取失败：${esc(state.groupsError)}` : `没有达到 ${percent}% 相似度的条目——宁可少合，也不合并相似度不够的经验。`}</p>`}</div>
      <footer class="exp-merge-batch">
        <label class="exp-pick exp-pick-all"><input type="checkbox" data-pick-all>全选（${all.length} 条可提炼${state.allLoaded ? "" : "，载入中…"}）</label>
        <span>已选 ${picks.length} 条</span>
        <button class="btn" data-merge-picks ${picks.length < 2 ? "disabled" : ""} title="把勾选的条目提炼成一条">提炼选中</button>
        <button class="btn" data-clear-picks ${picks.length ? "" : "disabled"}>清空勾选</button>
      </footer>`;
    box.querySelectorAll("[data-merge-ids]").forEach(b => {
      b.onclick = () => previewMerge(String(b.dataset.mergeIds || "").split(","));
    });
    const thresholdInput = box.querySelector("[data-threshold]");
    if (thresholdInput) {
      const apply = () => setThreshold(thresholdInput.value);
      thresholdInput.onchange = apply;
      thresholdInput.onkeydown = e => { if (e.key === "Enter") apply(); };
    }
    const thresholdBtn = box.querySelector("[data-threshold-apply]");
    if (thresholdBtn) thresholdBtn.onclick = () =>
      setThreshold(box.querySelector("[data-threshold]")?.value);
    const keepBtn = box.querySelector("[data-preview-keep]");
    if (keepBtn) keepBtn.onclick = () => keepPreview();
    const cancelBtn = box.querySelector("[data-preview-cancel]");
    if (cancelBtn) cancelBtn.onclick = () => discardPreview();
    const pickAll = box.querySelector("[data-pick-all]");
    if (pickAll) {
      pickAll.checked = all.length > 0 && picks.length === all.length;
      pickAll.onchange = () => togglePickAll(!!pickAll.checked);
    }
    const pickBtn = box.querySelector("[data-merge-picks]");
    if (pickBtn) pickBtn.onclick = () => previewMerge(picks);
    const clearBtn = box.querySelector("[data-clear-picks]");
    if (clearBtn) clearBtn.onclick = () => { state.picks.clear(); renderMergePanel(); renderList(); };
  }

  /* ---- 合并面板：选择 → 交给模型 → 只更新目标条目，原件一条不删 ---- */

  function renderAbsorbPanel() {
    const box = root().querySelector("[data-absorb-panel]");
    const toggle = root().querySelector("[data-absorb-toggle]");
    toggle?.classList?.toggle("on", state.absorbOn);
    if (!box) return;
    box.hidden = !state.absorbOn;
    if (!state.absorbOn) { box.innerHTML = ""; return; }
    const all = mergeable();
    const picks = [...state.picks].filter(id => all.some(it => String(it.insight_id) === id));
    const plan = state.absorbPlan;
    const cards = (plan && (plan.groups || []).length)
      ? plan.groups.map((group, index) => `
        <article class="exp-merge-group">
          <header>
            <span class="exp-merge-score">并入已有经验</span>
            <span class="muted">吸收 ${(group.sources || []).length} 条</span>
          </header>
          <p class="muted">目标（现在）：${esc(group.target_insight || "")}</p>
          <p class="exp-merge-draft-insight">${esc(group.insight || "")}</p>
          ${group.context ? `<p class="exp-merge-preview">适用：${esc(group.context)}</p>` : ""}
          <button class="btn primary" data-absorb-apply="${index}" title="把这段写进目标经验；被吸收的条目原样保留">采用这一处</button>
        </article>`).join("")
      : `<p class="muted">${plan ? esc(plan.note || "模型认为没有可以并入的地方，经验库没动。")
        : "勾选要处理的条目，交给 AI 判断能不能并进已有的某一条。"}</p>`;
    box.innerHTML = `
      <header class="exp-merge-head">
        <h3>合并（不删任何经验）</h3>
        <p>把勾选的条目交给模型：如果能并进<span class="exp-merge-th">已有的某一条</span>经验，
           就写进那一条；<b>原件全部保留</b>，库里一行都不会少。</p>
      </header>
      ${plan && (plan.groups || []).length > 1
        ? `<div class="exp-merge-draft-ops"><button class="btn primary" data-absorb-all>全部采用（${plan.groups.length} 处）</button></div>` : ""}
      <div class="exp-merge-groups">${cards}</div>
      <footer class="exp-merge-batch">
        <label class="exp-pick exp-pick-all"><input type="checkbox" data-absorb-pick-all>全选（${all.length} 条可合并${state.allLoaded ? "" : "，载入中…"}）</label>
        <span>已选 ${picks.length} 条</span>
        <button class="btn" data-absorb-plan ${picks.length < 1 ? "disabled" : ""} title="把这些条目交给 AI，看能不能并进已有经验">交给 AI 合并</button>
        <button class="btn" data-absorb-clear ${picks.length ? "" : "disabled"}>清空勾选</button>
      </footer>`;
    const pickAll = box.querySelector("[data-absorb-pick-all]");
    if (pickAll) {
      pickAll.checked = all.length > 0 && picks.length === all.length;
      pickAll.onchange = () => togglePickAll(!!pickAll.checked);
    }
    box.querySelectorAll("[data-absorb-apply]").forEach(b => {
      b.onclick = () => applyAbsorb(
        [(state.absorbPlan?.groups || [])[Number(b.dataset.absorbApply)]]);
    });
    const allBtn = box.querySelector("[data-absorb-all]");
    if (allBtn) allBtn.onclick = () => applyAbsorb(state.absorbPlan?.groups || []);
    const planBtn = box.querySelector("[data-absorb-plan]");
    if (planBtn) planBtn.onclick = () => planAbsorb(picks);
    const clearBtn = box.querySelector("[data-absorb-clear]");
    if (clearBtn) clearBtn.onclick = () => {
      state.picks.clear();
      state.absorbPlan = null;
      renderAbsorbPanel();
      renderList();
    };
  }

  /* 交给模型：只出方案，不动库 */
  async function planAbsorb(ids) {
    const list = (ids || []).map(id => String(id || "")).filter(Boolean);
    if (!list.length) { toast("先勾选要合并的经验", true); return; }
    toast(`正在交给 AI 判断（${list.length} 条）…`);
    try {
      const data = await api("/api/experience/absorb/preview", {
        method: "POST", body: JSON.stringify({ids: list})});
      state.absorbPlan = data;
      renderAbsorbPanel();
      toast(data.note || "合并方案已生成");
    } catch (e) {
      toast(e.message, true);
    }
  }

  /* 采用：只更新目标条目，被吸收的条目原样保留（后端保证不删） */
  async function applyAbsorb(groups) {
    const usable = (groups || []).filter(g => g && g.target_id && g.insight);
    if (!usable.length) return;
    try {
      const data = await api("/api/experience/absorb/apply", {
        method: "POST", body: JSON.stringify({groups: usable})});
      state.absorbPlan = null;
      state.picks.clear();
      toast(`已并入 ${data.applied || usable.length} 条目标经验，原件全部保留（删除 ${data.deleted || 0} 条）`);
      await load();
      if (state.absorbOn) await ensureAllItems().catch(() => {});
      renderAbsorbPanel();
      renderList();
    } catch (e) {
      toast(e.message, true);
    }
  }


  /* 第一步：只提炼，不动库。让用户先看提炼稿 */
  async function previewMerge(ids) {
    const list = (ids || []).map(id => String(id || "")).filter(Boolean);
    if (list.length < 2) { toast("二次提炼至少要选两条经验", true); return; }
    try {
      const res = await api("/api/experience/merge/preview", {
        method: "POST", body: JSON.stringify({ids: list, threshold: thresholdRatio()})});
      state.preview = {...res, ids: list};
      renderMergePanel();
    } catch (e) {
      toast(e.message, true);
    }
  }

  function discardPreview() {
    state.preview = null;
    renderMergePanel();
    toast("已放弃这次提炼，经验库没动");
  }

  async function keepPreview() {
    const preview = state.preview;
    if (!preview) return;
    await applyMerge(preview.ids || []);
  }

  /* 第二步：用户确认保留之后才真正入库（写结果 + 删原件） */
  async function applyMerge(ids) {
    const list = (ids || []).map(id => String(id || "")).filter(Boolean);
    if (list.length < 2) return;
    try {
      await api("/api/experience/merge", {
        method: "POST", body: JSON.stringify({ids: list, threshold: thresholdRatio()})});
      state.preview = null;
      state.picks.clear();
      toast(`已保留提炼结果，删除这 ${list.length} 条原经验`);
      await load();
      if (state.mergeOn) await loadGroups();
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function restoreMerge(mergedId) {
    try {
      await api("/api/experience/merge/restore", {
        method: "POST", body: JSON.stringify({merged_id: mergedId})});
      toast("已还原这次合并");
      await load();
      if (state.mergeOn) await loadGroups();
    } catch (e) { toast(e.message, true); }
  }

  function render(data) {
    const el = root();
    renderTiles(data);
    renderTags(data);
    renderList(data);
    renderMergePanel();
    renderAbsorbPanel();
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
      const picked = state.picks.has(iid);
      const pick = (state.mergeOn || state.absorbOn) && iid && !item.merged
        ? `<label class="exp-pick"><input type="checkbox" data-pick="${esc(iid)}"${picked ? " checked" : ""}>选这条</label>`
        : "";
      const parent = (item.merged_from || []).length > 0;
      const badge = item.merged
        ? `<span class="exp-badge exp-badge-merged" title="旧口径合并留下的原件（仍在库里，可还原）">已合并</span>`
        : (parent ? `<span class="exp-badge exp-badge-merge" title="由多条极相似经验提炼而来">二次提炼 · ${(item.merged_from || []).length} 条</span>` : "");
      const restore = item.merged && item.merged_into
        ? `<button class="btn exp-restore" data-restore="${esc(String(item.merged_into))}" title="把这次合并还原，原件全部恢复">还原</button>`
        : "";
      return `<article class="exp-card${item.merged ? " merged" : ""}">
        <div class="exp-card-tags">${tags || '<span class="exp-ins-tag muted">未打标签</span>'}${badge}</div>
        <p class="exp-insight">${esc(item.insight || "")}</p>
        ${item.context ? `<p class="exp-context">适用：${esc(item.context)}</p>` : ""}
        <footer>${source}<span class="exp-card-ops">
          ${pick}
          ${restore}
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
    box.querySelectorAll("[data-restore]").forEach(b =>
      b.onclick = () => armConfirm(b, () => restoreMerge(b.dataset.restore)));
    box.querySelectorAll("[data-pick]").forEach(b => b.onchange = () => {
      const id = String(b.dataset.pick || "");
      if (!id) return;
      if (b.checked) state.picks.add(id); else state.picks.delete(id);
      renderMergePanel();
      renderAbsorbPanel();
    });
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

  return {open, load, toggleMerge, loadGroups, applyMerge, restoreMerge,
          previewMerge, keepPreview, discardPreview, setThreshold, togglePickAll,
          renderMergePanel, toggleAbsorb, planAbsorb, applyAbsorb,
          renderAbsorbPanel, ensureAllItems, state};
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
                 duplicate: ["与库里重复", "skipped"],
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
                     Number(h.duplicates || 0) ? `跳过 ${h.duplicates} 条重复` : "",
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
      const dup = Number(data.duplicates || 0);          // 与库里高度重复、已取消的条数
      const skipNote = dup ? `，跳过 ${dup} 条与库里高度重复的` : "";
      if (data.result === "ok") toast(`提炼完成，新增 ${added} 条经验${skipNote}`);
      else if (data.result === "duplicate") toast(`这次提炼出的 ${dup} 条都与库里高度重复，未重复存储`);
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
