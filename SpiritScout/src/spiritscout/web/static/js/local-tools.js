/* 本地工具索引：设置目录，让 Agent 检索并运行本机工具，且用完还原原目录。 */
const LocalToolsPage = (() => {
  const EMPTY = { config: { enabled: false, dirs: [] }, tools: [], summary: {} };
  let data = EMPTY, query = "", busy = false, error = "", loaded = false;

  const size = n => {
    const v = Number(n) || 0;
    if (v >= 1048576) return (v / 1048576).toFixed(1) + " MB";
    if (v >= 1024) return (v / 1024).toFixed(0) + " KB";
    return v + " B";
  };
  const ago = ts => {
    if (!ts) return "还没扫过";
    const diff = Math.max(0, Math.floor(Date.now() / 1000 - Number(ts)));
    if (diff < 60) return `${diff} 秒前扫描`;
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前扫描`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前扫描`;
    return `${Math.floor(diff / 86400)} 天前扫描`;
  };
  const hits = () => {
    const q = query.trim().toLowerCase();
    const tools = data?.tools || [];
    if (!q) return tools;
    return tools.filter(t => `${t.name} ${t.path || ""} ${t.dir || ""}`.toLowerCase().includes(q));
  };

  function rows() {
    const tools = hits();
    const dirs = data?.config?.dirs || [];
    if (!dirs.length) {
      return '<p class="lt-empty">还没有工具目录。上面加一个文件夹，比如 <code>D:\\tools</code>，再点「保存并扫描」。</p>';
    }
    if (!tools.length) {
      return `<p class="lt-empty">${query.trim()
        ? `没有匹配「${esc(query.trim())}」的工具。`
        : "这些目录里还没扫到可执行文件（exe / py / ps1 / cmd / bat / sh / jar）。"}</p>`;
    }
    return `<div class="lt-table-wrap"><table class="lt-table">
      <thead><tr><th>工具</th><th>类型</th><th class="lt-num">大小</th><th>所在目录</th></tr></thead>
      <tbody>${tools.map(t => `<tr>
        <td><b>${esc(t.name)}</b><small>${esc(t.file)}</small></td>
        <td>${esc(t.ext || "—")}</td>
        <td class="lt-num">${size(t.size)}</td>
        <td><code>${esc(t.dir)}</code></td>
      </tr>`).join("")}</tbody></table></div>`;
  }

  function shell() {
    const cfg = data?.config || {};
    const dirs = cfg.dirs || [];
    const summary = data?.summary || {};
    const total = Number(summary.tools ?? (data?.tools || []).length) || 0;
    return `
      <div class="lt-head">
        <div>
          <h2>本地工具</h2>
          <p class="lt-sub">把本机现成的工具（exe / 脚本）编进索引，Agent 用 <code>local_tool</code> 按名字检索并运行。
            每次运行先把工具目录复制到工作区暂存副本、隔离临时目录与 HOME，跑完对账（新增删掉、改动还原）、
            核对清单一致后销毁副本——<b>用完不留残留文件</b>。</p>
        </div>
        <div class="lt-head-actions">
          <button type="button" class="btn sm" id="lt-refresh" ${busy ? "disabled" : ""}>重新扫描</button>
          <button type="button" class="btn sm tinted" id="lt-cleanup" ${busy ? "disabled" : ""}>清理暂存目录</button>
        </div>
      </div>

      <section class="lt-block">
        <div class="lt-block-head">
          <b>使用开关</b>
          <span class="lt-meta">${cfg.enabled ? "已开启" : "已关闭（Agent 会被告知不可用）"}</span>
        </div>
        <label class="lt-toggle">
          <input type="checkbox" id="lt-enabled" ${cfg.enabled ? "checked" : ""}>
          <span>允许 Agent 使用本地工具</span>
        </label>

        <h3 class="lt-sub-title">工具目录</h3>
        <div class="lt-dirs">${dirs.length
          ? dirs.map(dir => `<div class="lt-dir"><code>${esc(dir)}</code>
              <button type="button" class="btn sm ghost" data-lt-remove="${esc(dir)}">移除</button></div>`).join("")
          : '<p class="lt-empty">还没有目录。</p>'}</div>
        <div class="lt-add">
          <input type="text" id="lt-dir-input" placeholder="D:\\tools（绝对路径，别用盘符根）"
                 autocomplete="off" spellcheck="false">
          <button type="button" class="btn sm primary" id="lt-dir-add" ${busy ? "disabled" : ""}>添加</button>
        </div>
        <div class="lt-actions">
          <button type="button" class="btn sm primary" id="lt-save" ${busy ? "disabled" : ""}>保存并扫描</button>
          <span class="lt-meta">${esc(ago(summary.scanned_at))} · 索引 ${total} 个工具</span>
        </div>
        ${error ? `<p class="lt-error">${esc(error)}</p>` : ""}
      </section>

      <section class="lt-block">
        <div class="lt-block-head">
          <b>索引结果</b>
          <input type="search" id="lt-query" value="${esc(query)}" placeholder="按名字或路径过滤" autocomplete="off">
        </div>
        <div id="lt-tools">${rows()}</div>
        <p class="lt-note">运行由 Agent 发起；暂存目录在 <code>${esc(data?.runs_dir || "local-tools/runs")}</code>，
          正常运行结束即销毁，异常残留可用「清理暂存目录」收掉。</p>
      </section>`;
  }

  function render() {
    const box = $("#view-localtools");
    if (!box) return;
    box.innerHTML = shell();
    bind(box);
  }

  function renderTools() {
    const box = $("#lt-tools");
    if (box) box.innerHTML = rows();
  }

  /* 只有带 config 的响应才是「面板数据」；清理接口之类的返回不能顶掉现成状态 */
  async function send(path, opt = {}) {
    busy = true; error = "";
    render();
    try {
      const next = await api(path, opt);
      if (next && next.config) data = next;
    } catch (e) {
      error = e.message || "操作失败";
    } finally {
      busy = false;
      render();
    }
  }

  const dirs = () => [...(data?.config?.dirs || [])];

  function bind(box) {
    const enabled = () => box.querySelector("#lt-enabled")?.checked;
    box.querySelector("#lt-enabled")?.addEventListener("change", ev =>
      send("/api/local-tools", { method: "PUT", body: JSON.stringify({ enabled: ev.target.checked }) }));
    box.querySelector("#lt-save")?.addEventListener("click", () =>
      send("/api/local-tools", { method: "PUT",
        body: JSON.stringify({ dirs: dirs(), enabled: enabled() }) }));
    box.querySelector("#lt-refresh")?.addEventListener("click", () =>
      send("/api/local-tools/refresh", { method: "POST" }));
    box.querySelector("#lt-cleanup")?.addEventListener("click", async () => {
      await send("/api/local-tools/cleanup", { method: "POST" });
      await send("/api/local-tools");
    });
    box.querySelector("#lt-dir-add")?.addEventListener("click", () => {
      const input = box.querySelector("#lt-dir-input");
      const value = (input?.value || "").trim();
      if (!value) { input?.focus(); return; }
      send("/api/local-tools", { method: "PUT",
        body: JSON.stringify({ dirs: [...dirs(), value], enabled: enabled() }) });
    });
    box.querySelector("#lt-dir-input")?.addEventListener("keydown", ev => {
      if (ev.key === "Enter") { ev.preventDefault(); box.querySelector("#lt-dir-add")?.click(); }
    });
    box.querySelectorAll("[data-lt-remove]").forEach(btn =>
      btn.addEventListener("click", () =>
        send("/api/local-tools", { method: "PUT",
          body: JSON.stringify({ dirs: dirs().filter(d => d !== btn.dataset.ltRemove) }) })));
    /* 过滤只在本地做：输入时不重绘整块，光标和输入法都不被打断 */
    box.querySelector("#lt-query")?.addEventListener("input", ev => {
      query = ev.target.value;
      renderTools();
    });
  }

  async function open() {
    if (!loaded) {
      const box = $("#view-localtools");
      if (box && !box.querySelector(".lt-head")) {
        box.innerHTML = '<div class="lt-head"><div><h2>本地工具</h2>'
          + '<p class="lt-sub">正在读取工具目录配置…</p></div></div>';
      }
    }
    try {
      const next = await api("/api/local-tools");
      if (next && next.config) { data = next; loaded = true; }
    } catch (e) {
      error = e.message || "读取配置失败";
    }
    render();
  }

  return { open, render, get data() { return data; } };
})();
