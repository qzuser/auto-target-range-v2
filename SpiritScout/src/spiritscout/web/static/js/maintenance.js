/* 一键清理无用缓存：把放久了的会话产物、暂存上传、构建与解释器缓存收掉。
   口径由服务端 maintenance.py 把关——工具、venv、配置、密钥、经验库都不删。 */
const Maintenance = (() => {
  const PRESETS = [7, 30, 90];
  let days = 30, plan = null, busy = false, mounted = false, error = "";

  const fmtBytes = n => {
    const v = Number(n) || 0;
    if (v >= 1024 ** 3) return (v / 1024 ** 3).toFixed(1) + " GB";
    if (v >= 1024 ** 2) return (v / 1024 ** 2).toFixed(1) + " MB";
    if (v >= 1024) return (v / 1024).toFixed(0) + " KB";
    return v + " B";
  };

  function rows() {
    const items = plan?.items || [];
    if (!items.length) return `<p class="cache-empty">没有可清理的内容。</p>`;
    return items.map(it => `
      <li class="cache-row${it.removable ? "" : " keep"}">
        <span class="cache-name">${esc(it.label)}</span>
        <span class="cache-size">${fmtBytes(it.bytes)} · ${it.files} 个文件</span>
        <span class="cache-time">${esc(it.last_used || "—")}</span>
        <span class="cache-why">${it.removable ? "可清理" : esc(it.reason || "保留")}</span>
      </li>`).join("");
  }

  function html() {
    const can = (plan?.removable_count || 0) > 0;
    return `
      <h2>清理无用缓存</h2>
      <p class="muted">只清「放久了没用、丢了能重建」的东西：旧会话产物、暂存上传、
        构建与解释器缓存。本地装好的工具、虚拟环境、配置、密钥、经验库都不会动。</p>
      <div class="cache-bar">
        <label>保留最近
          <select data-cache-days>${PRESETS.map(d =>
            `<option value="${d}"${d === days ? " selected" : ""}>${d} 天</option>`).join("")}
          </select>内使用过的内容</label>
        <button class="btn sm" type="button" data-cache-refresh${busy ? " disabled" : ""}>重新盘点</button>
      </div>
      <div class="cache-summary">${plan
        ? `共 ${plan.total_files} 个文件 · ${fmtBytes(plan.total_bytes)}；其中可清理
           ${plan.removable_count} 项 · <b>${fmtBytes(plan.removable_bytes)}</b>`
        : "正在盘点…"}</div>
      <ul class="cache-list">${rows()}</ul>
      ${error ? `<p class="cache-error">${esc(error)}</p>` : ""}
      <div class="cache-actions">
        <button class="btn danger" type="button" data-cache-purge${(!can || busy) ? " disabled" : ""}>
          ${busy ? "清理中…" : "一键清理"}
        </button>
        <small>清理不可撤销；正在运行中的会话永远跳过。</small>
      </div>`;
  }

  function mount(host) {
    if (!host) return;
    if (!mounted) {
      host.innerHTML = `<section class="set-card cache-card" aria-label="缓存清理">${html()}</section>`;
      host.querySelector("[data-cache-days]").onchange = e => {
        days = Number(e.target.value) || 30; load();
      };
      host.querySelector("[data-cache-refresh]").onclick = () => load();
      host.querySelector("[data-cache-purge]").onclick = () => purge();
      mounted = true;
      return;
    }
    host.querySelector(".cache-card").innerHTML = html();
    host.querySelector("[data-cache-days]").onchange = e => {
      days = Number(e.target.value) || 30; load();
    };
    host.querySelector("[data-cache-refresh]").onclick = () => load();
    const btn = host.querySelector("[data-cache-purge]");
    if (btn) btn.onclick = () => purge();
  }

  async function load() {
    const host = document.querySelector("[data-maintenance]");
    if (!host) return;
    error = "";
    try {
      plan = await api(`/api/maintenance/cache?days=${days}`);
    } catch (e) {
      error = e.message || "盘点失败";
      plan = null;
    }
    mount(host);
  }

  async function purge() {
    if (busy) return;
    const can = plan?.removable_count || 0;
    if (!can) return;
    const size = fmtBytes(plan.removable_bytes);
    if (!confirm(`清理 ${can} 项、约 ${size}？此操作不可撤销（工具与配置不受影响）。`)) return;
    busy = true; error = "";
    mount(document.querySelector("[data-maintenance]"));
    try {
      const res = await api("/api/maintenance/cache/purge", {
        method: "POST",
        body: JSON.stringify({ days }),
      });
      busy = false;
      plan = await api(`/api/maintenance/cache?days=${days}`);
      mount(document.querySelector("[data-maintenance]"));
      alert(`已清理 ${res.removed.length} 项，释放 ${fmtBytes(res.freed_bytes)}。`
        + (res.kept.length ? `\n保留 ${res.kept.length} 项（占用中或仍在保留期）。` : ""));
      if (typeof refreshSessions === "function") refreshSessions();
    } catch (e) {
      busy = false;
      error = e.message || "清理失败";
      mount(document.querySelector("[data-maintenance]"));
    }
  }

  function open() {
    mounted = false;
    load();
  }

  return { open, load, purge };
})();
