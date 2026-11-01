/* 用量统计：按模型看 token 花在哪儿。只读账本，不动调度。 */
const UsagePage = (() => {
  const PERIODS = [["hour", "近 1 小时"], ["today", "今天"],
                   ["7d", "近 7 天"], ["30d", "近 30 天"], ["all", "全部"]];
  let period = "7d", data = null, busy = false, error = "", mounted = false;

  const fmt = n => {
    const v = Number(n) || 0;
    if (v >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
    if (v >= 1e4) return (v / 1e4).toFixed(1) + " 万";
    return v.toLocaleString("zh-CN");
  };
  const money = (usd, cnyMin, cnyMax) => {
    const parts = [];
    if (Number(cnyMin) > 0 || Number(cnyMax) > 0) {
      const lo = Number(cnyMin).toFixed(2), hi = Number(cnyMax).toFixed(2);
      parts.push(lo === hi ? `¥${lo}` : `¥${lo}~${hi}`);
    }
    if (Number(usd) > 0) parts.push(`$${Number(usd).toFixed(3)}`);
    return parts.join(" / ") || "—";
  };

  function rows() {
    const models = data?.models || [];
    if (!models.length) {
      return `<p class="usage-empty">这个时间段还没有用量记录。跑一次任务或对话之后再看。</p>`;
    }
    return models.map(m => `
      <tr>
        <td class="u-model" title="${esc(m.model)}">${esc(m.model)}</td>
        <td class="u-num">${fmt(m.calls)}</td>
        <td class="u-num">${fmt(m.input)}</td>
        <td class="u-num">${fmt(m.output)}</td>
        <td class="u-num">${m.cached ? fmt(m.cached) : "—"}</td>
        <td class="u-num u-total">${fmt(m.tokens)}</td>
        <td class="u-share">
          <span class="u-bar"><i style="width:${Math.max(1, Math.round((m.share || 0) * 100))}%"></i></span>
          <span class="u-pct">${((m.share || 0) * 100).toFixed(1)}%</span>
        </td>
        <td class="u-num">${esc(money(m.usd, m.cny_min, m.cny_max))}</td>
        <td class="u-time">${esc(m.last_at || "—")}</td>
      </tr>`).join("");
  }

  function summary() {
    const t = data?.totals;
    if (!t) return "";
    const cards = [
      ["合计 token", fmt(t.tokens)],
      ["调用次数", fmt(t.calls)],
      ["输入 / 输出", `${fmt(t.input)} / ${fmt(t.output)}`],
      ["模型数", fmt(t.models)],
      ["费用", money(t.usd, t.cny_min, t.cny_max)],
    ];
    return cards.map(([label, value]) =>
      `<div class="u-card"><span>${label}</span><b>${value}</b></div>`).join("");
  }

  function html() {
    return `
      <div class="usage-head">
        <div>
          <h2>用量统计</h2>
          <div class="u-sub">按模型汇总 token 用量与费用。账本来自控制台与各会话，
            ${data ? `共 ${data.ledgers} 本` : "正在读账本"}。</div>
        </div>
        <div class="u-ops">
          <select data-usage-period>${PERIODS.map(([value, label]) =>
            `<option value="${value}"${value === period ? " selected" : ""}>${label}</option>`).join("")}
          </select>
          <button class="btn sm" type="button" data-usage-refresh${busy ? " disabled" : ""}>刷新</button>
        </div>
      </div>
      <div class="u-cards">${summary()}</div>
      ${error ? `<p class="usage-error">${esc(error)}</p>` : ""}
      <table class="u-table">
        <thead><tr>
          <th>模型</th><th>调用</th><th>输入</th><th>输出</th>
          <th>缓存读</th><th>合计 token</th><th>占比</th><th>费用</th><th>最近一次</th>
        </tr></thead>
        <tbody>${rows()}</tbody>
      </table>
      ${data?.totals?.unpriced_calls
        ? `<p class="u-note">有 ${data.totals.unpriced_calls} 次调用没有价格信息（本地端点或未定价渠道），费用列对它不计数。</p>`
        : ""}`;
  }

  function paint(host) {
    host.innerHTML = html();
    const sel = host.querySelector("[data-usage-period]");
    if (sel) sel.onchange = e => { period = e.target.value; load(); };
    const btn = host.querySelector("[data-usage-refresh]");
    if (btn) btn.onclick = () => load();
  }

  async function load() {
    const host = $("#view-usage");
    if (!host) return;
    error = "";
    try {
      data = await api(`/api/usage/stats?period=${encodeURIComponent(period)}`);
    } catch (e) {
      error = e.message || "读用量失败";
      data = null;
    }
    mounted = true;
    paint(host);
  }

  function open() {
    const host = $("#view-usage");
    if (!host) return;
    if (!mounted) host.innerHTML = `<p class="usage-empty">正在读账本…</p>`;
    load();
  }

  return { open, load };
})();
