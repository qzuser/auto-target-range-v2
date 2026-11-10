/* ================= CTF 解题思路（WP） =================
   按赛方模板撰写：题目按方向分章（WEB/PWN/REVERSE/MISC/CRYPTO/DS/IOT），
   每题给题面要点、关键步骤与获取 Flag。材料全部来自本会话已记录的内容。

   生成前先过一道信息页：团队名称、队员、单位、赛事、补充说明，外加每道题的分章。
   这些都可留空（留空按材料里的事实写），但填过的会被记住——下次点开就是上次那套，
   沿用或改几个字都行。生成一次可能要几十秒（模型在写正文），按钮要给出明确的进行中状态。 */
const WriteUp = (() => {
  let busy = false;
  let pending = null;          // 上一次取到的 options，取消后再点不必重取
  const box = () => $("#tab-writeup");

  const DIRECTION_HINT = {
    WEB: "Web 安全", PWN: "二进制利用", REVERSE: "逆向工程", MISC: "杂项",
    CRYPTO: "密码学", DS: "数据安全", IOT: "工控与硬件",
  };

  const splitMembers = (text) =>
    text.split(/[,，、;；\n]/).map((item) => item.trim()).filter(Boolean);

  /* 只有 CTF 解题模式能重新生成（后端同样只认这个模式）；自动战报那份只给看和下载 */
  const canWrite = () => S.state?.session?.mode === "ctf";

  const shell = (data) => `<div class="wp-head">
      <span class="muted">${data.updated_at ? `生成于 ${esc(data.updated_at)}` : "尚无记录"}${
        data.source === "auto" ? " · 由本场自动生成" : ""}</span>
      <span class="wp-acts">
        ${canWrite() ? `<button class="btn sm" type="button" data-wp="open">重新生成</button>` : ""}
        <a class="btn sm" href="/api/sessions/${S.cur}/writeup/download" download>下载 Markdown</a>
      </span>
    </div>
    <div class="card report wp-body">${mdRender(data.markdown)}</div>`;

  const empty = () => `<div class="card wp-empty">
      <h3>还没有解题思路</h3>
      <p>${canWrite()
        ? "点下面的按钮，灵枢会按赛方模板为这次解答的题目写一份 WP：题目按方向分章，每题讲清怎么看出问题、怎么利用、最后拿到什么。"
        : "这个会话不是 CTF 解题模式，也没有自动生成过 WP；换到 CTF 解题模式的会话再生成。"}</p>
      ${canWrite() ? `<button class="btn primary" type="button" data-wp="open">生成 WP</button>` : ""}
    </div>`;

  const form = (data) => {
    const p = data.profile || {};
    const members = (p.members || []).join("、");
    const rows = (data.challenges || []).map((c) => {
      const options = (data.directions || []).map((name) =>
        `<option value="${esc(name)}"${name === c.chapter ? " selected" : ""}>${esc(name)}</option>`)
        .join("");
      const title = DIRECTION_HINT[c.chapter] ? "" :
        `<em class="wp-dir-note">按题面认不出方向，默认归到 ${esc(c.chapter)}</em>`;
      return `<label class="wp-dir">
          <span class="wp-dir-main">
            <span class="wp-dir-title">${esc(c.title)}</span>
            <small class="muted">${c.solved ? "已解出" : "未完成"}${c.raw ? ` · 题面标注 ${esc(c.raw)}` : ""}</small>
            ${title}
          </span>
          <select data-cid="${esc(c.id)}">${options}</select>
        </label>`;
    }).join("");
    const note = data.first_time
      ? "第一次写 WP：信息都可以留空，留空的地方模板里会写「（待填写）」。"
      : "已带出上次填的信息；沿用就点「开始生成」，要改几处直接改。";
    return `<div class="card wp-form">
        <div class="wp-form-head">
          <h3>写 WP 前确认一下信息</h3>
          <p class="muted">这些只影响文档开头的团队信息与题目分章，不填也能生成。</p>
        </div>
        <div class="wp-grid">
          <label class="wp-field"><span>团队名称</span>
            <input data-f="name" maxlength="120" value="${esc(p.name || "")}"
                   placeholder="留空则用会话标题"></label>
          <label class="wp-field"><span>队员组成</span>
            <input data-f="members" maxlength="600" value="${esc(members)}"
                   placeholder="逗号或顿号分隔，留空写「（待填写）」"></label>
          <label class="wp-field"><span>所属单位</span>
            <input data-f="affiliation" maxlength="120" value="${esc(p.affiliation || "")}"
                   placeholder="学校 / 公司（可空）"></label>
          <label class="wp-field"><span>参赛赛事</span>
            <input data-f="contest" maxlength="120" value="${esc(p.contest || "")}"
                   placeholder="例：2026 某某杯（可空）"></label>
        </div>
        <label class="wp-field wp-wide"><span>补充说明</span>
          <textarea data-f="notes" rows="2" maxlength="1000"
                    placeholder="比赛约定、想强调的细节、需要回避的内容（可空）">${esc(p.notes || "")}</textarea></label>
        <div class="wp-dirs">
          <div class="wp-dirs-head">
            <span>题目分章</span>
            <small class="muted">按题面自动判定，不对就改——写手按你选的chapter分章</small>
          </div>
          ${rows || '<div class="empty-note">这个会话没有题目记录，生成时会写成「本场未解出题目」。</div>'}
        </div>
        <div class="wp-form-acts">
          <button class="btn primary" type="button" data-wp="submit">开始生成</button>
          <button class="btn" type="button" data-wp="cancel">取消</button>
          <span class="muted wp-form-note">${esc(note)}</span>
        </div>
      </div>`;
  };

  const readForm = () => {
    const host = box();
    const field = (name) => host.querySelector(`[data-f='${name}']`);
    const team = {
      name: (field("name")?.value || "").trim(),
      members: splitMembers(field("members")?.value || ""),
      affiliation: (field("affiliation")?.value || "").trim(),
      contest: (field("contest")?.value || "").trim(),
      notes: (field("notes")?.value || "").trim(),
    };
    const directions = {};
    host.querySelectorAll("select[data-cid]").forEach((select) => {
      directions[select.dataset.cid] = select.value;
    });
    return { team, directions };
  };

  const render = (data) => {
    pending = null;
    box().innerHTML = data && data.markdown ? shell(data) : empty();
  };

  const load = async () => {
    const host = box();
    pending = null;
    host.innerHTML = '<div class="empty-note">加载中…</div>';
    try {
      render(await api(`/api/sessions/${S.cur}/writeup`));
    } catch (e) {
      host.innerHTML = `<div class="empty-note">${esc(e.message)}</div>`;
    }
  };

  const open = async () => {
    const host = box();
    try {
      pending = pending || await api(`/api/sessions/${S.cur}/writeup/options`);
      host.innerHTML = form(pending);
      host.querySelector("[data-f='name']")?.focus();
    } catch (e) {
      toast(e.message, true);
    }
  };

  const submit = async (btn) => {
    if (busy) return;
    busy = true;
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "正在按模板撰写…";
    const hint = document.createElement("div");
    hint.className = "empty-note wp-progress";
    hint.textContent = "灵枢正在读这次的题目、过程记录和 Flag，成文需要几十秒。";
    btn.after(hint);
    try {
      const data = await api(`/api/sessions/${S.cur}/writeup`,
        { method: "POST", body: JSON.stringify(readForm()) });
      render(data);
      toast("解题思路已生成");
    } catch (e) {
      toast(e.message, true);
      hint.remove();
      btn.disabled = false;
      btn.textContent = label;
    } finally {
      busy = false;
    }
  };

  document.addEventListener("click", (ev) => {
    if (ev.target.closest("[data-wp='open']")) { void open(); return; }
    if (ev.target.closest("[data-wp='cancel']")) { void load(); return; }
    const btn = ev.target.closest("[data-wp='submit']");
    if (btn) void submit(btn);
  });

  return { load, reset: () => { pending = null; box().innerHTML = ""; } };
})();
