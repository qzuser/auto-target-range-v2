/* 本地工具索引：设置存放工具的目录，让 Agent 能检索并运行，且用完还原原目录。 */
const LocalToolsPage = (() => {
  let data = null, busy = false, error = "", mounted = false, query = "";

  const size = n => {
    const v = Number(n) || 0;
    if (v >= 1048576) return (v / 1048576).toFixed(1) + " MB";
    if (v >= 1024) return (v / 1024).toFixed(0) + " KB";
    return v + " B";
  };
  const when = ts => {
    if (!ts) return "还没扫过";
    const diff = Math.max(0, Math.floor(Date.now() / 1000 - Number(ts)));
    return diff < 60 ? `${diff} 秒前扫描` : diff < 3600 ? `${Math.floor(diff / 60)} 分钟前扫描`
      : `${Math.floor(diff / 3600)} 小时前扫描`;
  };

  function shell() {
    const cfg = data?.config || {};
    const dirs = cfg.dirs || [];
    const tools = data?.tools || [];
    const summary = data?.summary || {};
    return `
      <div class="set-card">
        <h2>本地工具索引</h2>
        <p class="muted">把本机现成的工具（exe / 脚本）编进索引，Agent 能按名字检索并运行。
          运行时工具目录会先复制到工作区暂存副本，跑完核对并还原原目录、销毁副本——
          用完之后不留残留文件。</p>
        <label class="set-toggle">
          <input type="checkbox" id="lt-enabled" ${cfg.enabled ? "checked" : ""}>
          <span>允许 Agent 使用本地工具</span>
        </label>
        <div class="lt-dirs">
          <h3>工具目录</h3>
          ${dirs.length ? dirs.map(d => `<div class="lt-dir"><code>${esc(d)}</code>
            <button type="button" class="ghost" data-lt-remove="${esc(d)}">移除</button></div>`).join("")
            : '<p class="muted">还没有目录。加上存放工具的文件夹，例如 D:\\tools。</p>'}
          <div class="lt-add">
            <input type="text" id="lt-dir-input" placeholder="D:\\tools（绝对路径）" autocomplete="off">
            <button type="button" id="lt-dir-add">添加</button>
          </div>
        </div>
        <div class="lt-actions">
          <button type="button" id="lt-save" ${busy ? "disabled" : ""}>保存并扫描</button>
          <button type="button" class="ghost" id="lt-refresh" ${busy ? "disabled" : ""}>重新扫描</button>
          <button type="button" class="ghost" id="lt-cleanup" ${busy ? "disabled" : ""}>清理暂存目录</button>
          <span class="muted">${esc(when(summary.scanned_at))} · ${esc(String(summary.tools || 0))} 个工具</span>
        </div>
        ${error ? `<p class="lt-error">${esc(error)}</p>` : ""}
        <p class="muted">${esc(data?.notice || "")}</p>
        <div class="lt-search">
          <input type="search" id="lt-query" value="${esc(query)}" placeholder="按名字或路径过滤" autocomplete="off">
        </div>
        ${tools.length ? `<div class="lt-table-wrap"><table class="list lt-table">
          <thead><tr><th>工具</th><th>类型</th><th>大小</th><th>所在目录</th></tr></thead>
          <tbody>${tools.map(t => `<tr>
            <td><strong>${esc(t.name)}</strong><small>${esc(t.file)}</small></td>
            <td>${esc(t.ext || "—")}</td>
            <td>${size(t.size)}</td>
            <td><code>${esc(t.dir)}</code></td>
          </tr>`).join("")}</tbody></table></div>`
          : `<p class="muted">${cfg.dirs?.length ? "这些目录里还没扫到可执行工具。" : "加一个目录再扫描。"}</p>`}
      </div>`;
  }

  function render() {
    const box = $("#view-localtools");
    if (!box) return;
    box.innerHTML = shell();
    bind(box);
  }

  async function send(path, opt = {}) {
    busy = true; error = ""; render();
    try {
      data = await api(path, opt);
    } catch (e) {
      error = e.message || "操作失败";
    } finally {
      busy = false;
      render();
    }
  }

  function dirs() { return [...(data?.config?.dirs || [])]; }

  function bind(box) {
    box.querySelector("#lt-enabled")?.addEventListener("change", e =>
      send("/api/local-tools", { method: "PUT", body: JSON.stringify({ enabled: e.target.checked }) }));
    box.querySelector("#lt-save")?.addEventListener("click", () =>
      send("/api/local-tools", { method: "PUT",
        body: JSON.stringify({ dirs: dirs(), enabled: box.querySelector("#lt-enabled")?.checked }) }));
    box.querySelector("#lt-refresh")?.addEventListener("click", () =>
      send("/api/local-tools/refresh", { method: "POST" }));
    box.querySelector("#lt-cleanup")?.addEventListener("click", async () => {
      await send("/api/local-tools/cleanup", { method: "POST" });
      await send("/api/local-tools");
    });
    box.querySelector("#lt-dir-add")?.addEventListener("click", () => {
      const input = box.querySelector("#lt-dir-input");
      const value = (input?.value || "").trim();
      if (!value) return;
      const next = [...dirs(), value];
      send("/api/local-tools", { method: "PUT",
        body: JSON.stringify({ dirs: next, enabled: box.querySelector("#lt-enabled")?.checked }) });
    });
    box.querySelectorAll("[data-lt-remove]").forEach(btn =>
      btn.addEventListener("click", () => {
        const target = btn.dataset.ltRemove;
        const next = dirs().filter(d => d !== target);
        send("/api/local-tools", { method: "PUT", body: JSON.stringify({ dirs: next }) });
      }));
    box.querySelector("#lt-query")?.addEventListener("input", e => {
      query = e.target.value;
      clearTimeout(bind.timer);
      bind.timer = setTimeout(() => send(`/api/local-tools?q=${encodeURIComponent(query)}`), 220);
    });
  }

  async function open() {
    if (!mounted) mounted = true;
    await send(`/api/local-tools?q=${encodeURIComponent(query)}`);
  }

  return { open, render, get data() { return data; } };
})();
