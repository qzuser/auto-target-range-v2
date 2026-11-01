"use strict";
/* ================= 基础 ================= */
const $ = s => document.querySelector(s);
const S = { view: "home", cur: null, tab: "chat", sessions: [], state: null,
            agents: null, models: null, evSeen: 0, es: null, poll: null, medit: null,
            providers: null, pedit: null, fprov: "", presets: null, effSel: [],
            topoView: null, compFiles: [], homeFiles: [], think: new Map(),
            projects: [] };
/* 上一次列表里也没找到的当前会话。连两轮都缺才认定被删——刚建好的会话在
   列表接口返回之前会短暂缺席，只差一轮就当它被删，会把新区踢回首页。 */
let missingSessionTick = null;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

async function api(path, opt = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opt });
  if (r.status === 401 && !String(path).startsWith("/api/auth/")) {
    location.assign("/login");           // 会话过期：回登录页而不是持续报错
    throw new Error("需要重新登录");
  }
  if (!r.ok) {
    let detail = null, msg = r.statusText;
    try { detail = (await r.json()).detail; } catch {}
    if (detail && typeof detail === "object") msg = detail.message || msg;
    else if (detail) msg = detail;
    const err = new Error(msg);
    err.detail = detail;               // 结构化错误（如规则冲突清单）随异常上抛
    err.status = r.status;             // 调用方按状态码分流：会话已删除 vs 别的问题
    throw err;
  }
  const result = await r.json();
  return result;
}
function toast(msg, err = false) {
  const el = document.createElement("div");
  el.className = "toast" + (err ? " err" : "");
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}
const TERMINAL = new Set(["completed", "failed", "stopped", "interrupted"]);
const STATUS_CN = { created: "排队中", running: "运行中", completed: "已完成",
                    failed: "失败", stopped: "已停止", interrupted: "已中断" };
const MODE_CN = { src: "SRC 渗透", ctf: "CTF 解题", competition: "智能渗透赛",
                  dialogue: "对话", rules: "规则" };
const TASK_CN = { business_context: "业务体验与上下文", recon: "侦察测绘", port_scan: "端口扫描", web_probe: "Web 探测",
                  host_probe: "主机探测", post_exploit: "后渗透", report: "报告生成",
                  ctf_web: "Web 题", ctf_pwn: "Pwn 题", ctf_reverse: "逆向题",
                  ctf_crypto: "密码题", ctf_misc: "杂项题" };
const SEV_CN = { critical: ["严重", "red"], high: ["高危", "red"], medium: ["中危", "orange"],
                 low: ["低危", "blue"], info: ["信息", "blue"] };
function agentName(key) {
  if (!S.agents) return key || "—";
  const a = S.agents.roster.find(x => x.key === key);
  return a ? a.name : (key || "—");
}
/* 审计 actor 形如 ctf-web-094cd1652967（键+实例短码）：还原为编队显示名 */
function actorName(actor) {
  const base = String(actor || "").replace(/-[0-9a-f]{8,}$/i, "").replace(/-/g, "_");
  if (!S.agents) return actor || "—";
  const a = S.agents.roster.find(x => x.key === base || x.key === actor);
  return a ? a.name : (actor || "—");
}
/* 项目名缓存由项目页加载；取不到（未分类/项目已删）按未分类显示 */
function projectName(id) {
  if (!id) return "未分类";
  const hit = (S.projects || []).find(x => x.project_id === id);
  return hit ? hit.name : "未分类";
}
function fmtElapsed(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), ss = sec % 60;
  const pad = n => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(ss)}` : `${m}:${pad(ss)}`;
}
/* 事件时刻 = 任务累积时间（相对会话开始的 0:00 计时，免疫时区） */
function evElapsed(ts) {
  const t0 = S.state && S.state.session && S.state.session.started_at;
  if (!t0 || !ts) return "";
  const t = new Date(ts).getTime();
  return isFinite(t) ? fmtElapsed(t / 1000 - t0) : "";
}
function fmtDur(a, b) {
  if (!a) return "—";
  const s = Math.max(0, Math.round(((b || Date.now() / 1000) - a)));
  const m = Math.floor(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)}h${m % 60}m` : m ? `${m}m${s % 60}s` : `${s}s`;
}

/* ================= 主题 ================= */
function applyTheme(t) {
  const root = document.documentElement;
  if (t === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", t);
  try { localStorage.setItem("ss-theme", t); } catch {}
}
/* 主题按钮在侧栏底与「关于」里都有，共用一套轮换逻辑 */
function cycleTheme() {
  const cur = (() => { try { return localStorage.getItem("ss-theme") || "system"; } catch { return "system"; } })();
  const next = { system: "light", light: "dark", dark: "system" }[cur];
  applyTheme(next);
  toast({ system: "跟随系统", light: "浅色", dark: "深色" }[next] + "主题");
}
$("#btn-theme").onclick = cycleTheme;
try { applyTheme(localStorage.getItem("ss-theme") || "system"); } catch {}

/* 退出登录：清 Cookie 后回登录页；未启用登录时 /login 会自动跳回控制台 */
async function logout() {
  try { await fetch("/api/auth/logout", { method: "POST" }); } catch {}
  location.assign("/login");
}
$("#btn-logout").onclick = logout;

/* ================= 视图切换 =================
   主界面放五项：任务 / 仪表盘 / 编队 / 项目 / 经验。
   模型、MCP 接入、Skill 知识、关于收进「设置」——设置是占满主区的独立界面，
   靠左侧分类栏切换而不是弹窗；S.view 仍记分类名，各页原有判断不受影响。 */
const VIEWS = { home: "#view-home", session: "#view-session", dash: "#view-dash",
                agents: "#view-agents", projects: "#view-projects", exp: "#view-exp",
                settings: "#view-settings" };
const SET_TABS = { models: "#view-models", mcp: "#view-mcp", skill: "#view-skill",
                   notify: "#view-notify", about: "#view-about" };
const SET_FIRST = "models";

function show(view) {
  const inSet = SET_TABS[view] !== undefined;
  if (view !== "mcp" && typeof ExaSettings !== "undefined") ExaSettings.clear();
  S.view = view;
  for (const [k, sel] of Object.entries(VIEWS)) $(sel).hidden = k !== (inSet ? "settings" : view);
  for (const [k, sel] of Object.entries(SET_TABS)) { const el = $(sel); if (el) el.hidden = !inSet || k !== view; }
  if (inSet) S.setTab = view;
  document.querySelectorAll(".side > nav button").forEach(b =>
    b.classList.toggle("on", b.dataset.nav === (view === "session" ? "home" : view)));
  $("#btn-settings").classList.toggle("on", inSet);
  document.querySelectorAll(".set-nav button").forEach(b =>
    b.classList.toggle("on", inSet && b.dataset.set === view));
  if (view === "agents") loadAgents();
  if (view === "models") loadModels();
  if (view === "notify" && typeof ConsoleNotify !== "undefined") ConsoleNotify.open();
  if (view === "about") renderAbout();
  if (view === "dash") renderDash();
  if (typeof ProjectsPage !== "undefined") {
    if (view === "projects") ProjectsPage.open(); else ProjectsPage.close();
  }
  if (["mcp","skill"].includes(view) && typeof ResourceConsole !== "undefined") ResourceConsole.open(view);
  if (view === "exp" && typeof ExperiencePage !== "undefined") ExperiencePage.open();
  if (view !== "session") { SessionHistory.cancel(); stopStreams(); }
  renderTaskDock();   /* 换了视图，「哪些算在后台」就变了 */
}
/* 「关于」页复用侧栏底部那份版本号，不在前端再写一处版本字面量 */
function renderAbout() {
  const ver = ($("#ver")?.textContent || "").trim();
  const el = $("#about-ver"); if (el && ver) el.textContent = ver;
}
$("#btn-theme-inline").onclick = cycleTheme;
$("#btn-logout-inline").onclick = logout;
document.querySelectorAll(".set-nav button").forEach(b =>
  b.onclick = () => { S.cur = null; show(b.dataset.set); renderSessions(); });
$("#btn-settings").onclick = () => { S.cur = null; show(S.setTab || SET_FIRST); renderSessions(); };
document.querySelectorAll(".side > nav button").forEach(b =>
  b.onclick = () => { S.cur = null; show(b.dataset.nav); renderSessions(); });
$("#btn-new").onclick = () => { S.cur = null; show("home"); renderSessions(); };
initTaskDock();

/* ================= 会话列表 ================= */
let sessionsInFlight = null;
function refreshSessions() {
  if (sessionsInFlight) return sessionsInFlight;
  sessionsInFlight = fetchSessions().finally(() => { sessionsInFlight = null; });
  return sessionsInFlight;
}
async function fetchSessions() {
  S.polling?.listRequested();
  try {
    const d = await api("/api/sessions");
    S.sessions = d.sessions;
    $("#connection-status")?.remove();
    renderSessions();
    renderTaskDock();
    if (S.view === "dash") renderDash();
    if (S.cur) {
      const cur = S.sessions.find(x => x.session_id === S.cur);
      if (cur && S.state && S.state.session.status !== cur.status) await refreshState();
      if (cur && S.view === "session" && !TERMINAL.has(cur.status) && !S.es) startStreams(false);
      /* 服务端列表里没有当前会话：连两轮都缺才算真没了，摘掉并按需退回首页。
         缺一轮不算，那是刚建好还没进列表的窗口。 */
      if (cur) missingSessionTick = null;
      else if (missingSessionTick === S.cur) dropMissingSession(S.cur);
      else missingSessionTick = S.cur;
    } else missingSessionTick = null;
  } catch (e) {
    if (!$("#connection-status")) {
      const notice = document.createElement("div"); notice.id = "connection-status"; notice.setAttribute("role", "status");
      notice.textContent = "控制台连接中断，正在重试；当前内容可能不是最新。"; document.body.append(notice);
    }
  }
}
/* 会话按项目文件夹分组：指向已删项目的会话归入未分类。
   文件夹顺序跟随项目目录（最近活动优先），未分类殿后；只渲染有会话的文件夹。 */
function sessionGroups(sessions, projects) {
  const known = new Map((projects || []).map(p => [p.project_id, p]));
  const groups = new Map();
  for (const s of sessions || []) {
    const id = s.project_id && known.has(s.project_id) ? s.project_id : "";
    if (!groups.has(id)) {
      groups.set(id, {id,
        name: id ? (known.get(id).name || "未命名项目") : "未分类", items: []});
    }
    groups.get(id).items.push(s);
  }
  const order = new Map((projects || []).map((p, i) => [p.project_id, i]));
  return [...groups.values()].sort((a, b) =>
    (a.id ? order.get(a.id) : Number.MAX_SAFE_INTEGER)
    - (b.id ? order.get(b.id) : Number.MAX_SAFE_INTEGER));
}

/* 折叠状态是浏览器本地偏好：按项目 ID 记一组收起的文件夹。 */
const SESS_FOLD_KEY = "ss-sess-folded";
function foldedFolders() {
  try {
    const raw = JSON.parse(localStorage.getItem(SESS_FOLD_KEY) || "[]");
    return new Set(Array.isArray(raw) ? raw.map(String) : []);
  } catch { return new Set(); }
}
function foldFolder(id, folded) {
  const set = foldedFolders(), key = String(id || "");
  if (folded) set.add(key); else set.delete(key);
  try { localStorage.setItem(SESS_FOLD_KEY, JSON.stringify([...set])); } catch {}
}

function sessionItemHtml(s) {
  return `
    <div class="sess-item ${s.session_id === S.cur ? "on" : ""}" data-id="${s.session_id}">
      <div class="t"><span class="pill ${s.status}" style="padding:1px 7px;font-size:10.5px">${STATUS_CN[s.status] || s.status}</span>
        <span class="name" title="${esc(s.title)}">${esc(s.title)}</span></div>
      <div class="s">${esc(s.target || s.session_id)} · <span class="mono">${esc(s.session_id.slice(5, 13))}</span></div>
      <div class="ops">
        <button data-act="rename" title="重命名" aria-label="重命名"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m16 3 5 5-12 12-6 1 1-6L16 3ZM14 5l5 5"/></svg></button>
        <button data-act="del" class="danger" title="删除会话">✕</button>
      </div>
    </div>`;
}

function renderSessions() {
  const box = $("#sess-list");
  if (!box) return;
  if (box.querySelector("input.rename, [data-armed]")) return;   // 正在重命名：不打断输入
  if (!S.sessions.length) {
    box.innerHTML = `<div class="empty-note" style="padding:22px 8px">还没有会话</div>`;
    return;
  }
  const folded = foldedFolders();
  const chev = `<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>`;
  const folder = `<svg class="fico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5h3.4l2 2h7.6A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z"/></svg>`;
  box.innerHTML = sessionGroups(S.sessions, S.projects).map(g => {
    const isFolded = folded.has(g.id);
    const hasCurrent = g.items.some(s => s.session_id === S.cur);
    const running = g.items.some(s => !TERMINAL.has(s.status));
    const action = isFolded ? "展开" : "折叠";
    return `<section class="sess-folder${isFolded ? " folded" : ""}${hasCurrent ? " has-on" : ""}" data-folder="${esc(g.id)}">
      <button class="sess-folder-head" type="button" aria-expanded="${isFolded ? "false" : "true"}" title="${action}项目：${esc(g.name)}">
        ${chev}${folder}<span class="fname">${esc(g.name)}</span>${running ? `<span class="frun" title="有会话在运行"></span>` : ""}<span class="fcount">${g.items.length}</span>
      </button>
      <div class="sess-folder-body">${g.items.map(sessionItemHtml).join("")}</div>
    </section>`;
  }).join("");
  box.querySelectorAll(".sess-folder-head").forEach(head => {
    head.onclick = () => {
      const section = head.closest(".sess-folder");
      const next = !section.classList.contains("folded");
      section.classList.toggle("folded", next);
      head.setAttribute("aria-expanded", String(!next));
      head.title = `${next ? "展开" : "折叠"}项目：${section.querySelector(".fname").textContent}`;
      foldFolder(section.dataset.folder, next);
    };
  });
  box.querySelectorAll(".sess-item").forEach(el => {
    el.onclick = (ev) => {
      if (!ev.target.closest(".ops") && !ev.target.closest("input"))
        openSession(el.dataset.id);
    };
    el.querySelector('[data-act="rename"]').onclick = (ev) => {
      ev.stopPropagation(); startRename(el.dataset.id, el.querySelector(".name"));
    };
    el.querySelector('[data-act="del"]').onclick = (ev) => {
      ev.stopPropagation(); armDelete(ev.currentTarget, el.dataset.id);
    };
  });
}

/* ── 后台任务坞 ─────────────────────────────────────────────
   任务跑着、而当前视图不是它的时候，左下角浮出一条：「N 个任务在后台运行」，
   点开能看见各自状态并跳回去。

   只报状态不报进度：S.state 只装当前会话的详情，别的会话跑到第几步前端并不
   知道。这里不编一个假进度条，要细节就点进去看。 */
function backgroundTasks() {
  return S.sessions.filter(s =>
    !TERMINAL.has(s.status) && !(S.view === "session" && s.session_id === S.cur));
}

function renderTaskDock() {
  const box = $("#task-dock");
  if (!box) return;
  const body = $("#dock-body");
  /* 任务坞挂在 body 下，是唯一会盖在所有页面上的浮层。它回答的是「我这边还有
     哪些任务在后台跑、哪些在等我回答」——这是会话页的问题。切到仪表盘、资源、
     设置页时先收起，回到会话再出现，免得在别的页面挡住内容。 */
  const behind = S.view === "session" ? backgroundTasks() : [];
  if (!behind.length) {
    box.hidden = true;
    box.classList.remove("open");
    $("#dock-toggle")?.setAttribute("aria-expanded", "false");
    if (body) body.hidden = true;
    return;
  }
  box.hidden = false;
  const count = $("#dock-count");
  if (count) {
    const running = behind.filter(s => s.status === "running").length;
    count.textContent = running === behind.length
      ? `${behind.length} 个任务在后台运行`
      : `${behind.length} 个任务在后台（${running} 个运行中）`;
  }
  if (!body) return;
  body.innerHTML = behind.map(s => `
    <button class="dock-row" type="button" data-id="${esc(s.session_id)}" title="切到这个任务">
      <span class="pill ${esc(s.status)}">${esc(STATUS_CN[s.status] || s.status)}</span>
      <span class="dock-name">${esc(s.title)}</span>
      <span class="dock-target">${esc(s.target || "")}</span>
    </button>`).join("");
  body.hidden = !box.classList.contains("open");   /* 重渲染后仍守住展开状态 */
  body.querySelectorAll(".dock-row").forEach(el => {
    el.onclick = () => openSession(el.dataset.id);
  });
}

function initTaskDock() {
  const btn = $("#dock-toggle"), box = $("#task-dock"), body = $("#dock-body");
  if (!btn || !box || !body) return;
  btn.onclick = () => {
    const open = !box.classList.contains("open");
    box.classList.toggle("open", open);
    body.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
  };
}

/* 重命名：就地编辑，回车提交 / Esc 取消；清空提交 = 恢复自动命名。
   输入框以兄弟节点浮出、原名隐藏，避免破坏被隐藏节点的既有渲染逻辑。 */
function startRename(id, host) {
  if (!host || host.parentElement.querySelector("input.rename")) return;
  const cur = S.sessions.find(s => s.session_id === id) || {};
  const input = document.createElement("input");
  input.className = "rename";
  input.value = cur.title || "";
  input.placeholder = cur.title || "会话名";
  input.title = "回车保存；清空并回车恢复自动命名";
  host.style.display = "none";
  host.after(input);
  input.focus(); input.select();
  let settled = false;
  const restore = () => { input.remove(); host.style.display = ""; };
  const commit = async () => {
    if (settled) return; settled = true;
    const next = input.value.trim();
    restore();
    try {
      await api(`/api/sessions/${id}`, {
        method: "PATCH", body: JSON.stringify({ title: next }) });
      toast(next ? "已重命名" : "已恢复自动命名");
    } catch (e) { toast(e.message, true); }
    await refreshSessions();
    if (S.cur === id) refreshState();
  };
  input.onkeydown = (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); commit(); }
    else if (ev.key === "Escape") {
      settled = true; restore(); renderSessions();
      if (S.cur === id) refreshState();
    }
  };
  input.onblur = commit;
  input.onclick = (ev) => ev.stopPropagation();
}

/* 两段式确认：首击变「删除?」，3 秒内再击才执行 run（会话/经验/模型等删除共用）。
   存的是 innerHTML 而不是 textContent —— 图标按钮（供应商那排垃圾桶）文字是空的，
   按 textContent 恢复会把整个图标抹掉。 */
function armConfirm(btn, run) {
  if (btn.dataset.armed) {
    delete btn.dataset.armed;
    btn.disabled = true;
    Promise.resolve().then(run).catch(() => {}).finally(() => {
      btn.disabled = false;
      btn.classList.remove("armed");
      btn.innerHTML = btn.dataset.label || "删除";
    });
    return;
  }
  btn.dataset.armed = "1"; btn.classList.add("armed");
  btn.dataset.label = btn.innerHTML; btn.innerHTML = "删除?";
  setTimeout(() => {
    if (btn.dataset.armed) {
      delete btn.dataset.armed; btn.classList.remove("armed"); btn.innerHTML = btn.dataset.label;
    }
  }, 3000);
}
function armDelete(btn, id) { armConfirm(btn, () => doDelete(id)); }

/* 破坏性操作的模态确认：遮罩 + 居中弹窗 + 红色确认键，Esc / 取消 / 点遮罩都能退。
   返回 Promise<boolean>。两段式 armConfirm 挡不住「手滑连点两下」，而模型和
   供应商这类删掉就得重配一遍的对象值得一次真正的停顿——弹窗里还要把「删的是
   哪一个」「会牵连什么」摆出来，光换个按钮文字说不清。 */
function confirmDialog({ title, body = "", target = "", footnote = "", okText = "删除" }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "confirm-dlg";
    const note = footnote ? `<small>${esc(footnote)}</small>` : "";
    dlg.innerHTML = `<h3>${esc(title)}</h3>
      <p class="cf-body">${body}</p>
      ${target ? `<code class="cf-target">${esc(target)}${note}</code>` : ""}
      <div class="cf-error" role="alert"></div>
      <div class="dlg-ops"><button type="button" class="btn" data-cancel>取消</button>
        <button type="button" class="btn danger" data-ok>${esc(okText)}</button></div>`;
    document.body.append(dlg);
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      dlg.close();
      dlg.remove();
      resolve(value);
    };
    dlg.querySelector("[data-cancel]").onclick = () => finish(false);
    dlg.querySelector("[data-ok]").onclick = () => finish(true);
    /* Esc 走 cancel 事件：拦下来自己收尾，免得 close 与 remove 各触发一次 */
    dlg.addEventListener("cancel", (ev) => { ev.preventDefault(); finish(false); });
    dlg.addEventListener("click", (ev) => { if (ev.target === dlg) finish(false); });
    dlg.showModal();
    dlg.querySelector("[data-ok]").focus();
  });
}
async function doDelete(id) {
  try {
    await api(`/api/sessions/${id}?confirm=true`, { method: "DELETE" });
    toast("会话已删除");
    if (S.cur === id) { S.cur = null; show("home"); }
    refreshSessions();
  } catch (e) { toast(e.message, true); }
}


/* ================= 自定义下拉：全站 <select> 增强 ================= */
/* 原生 select 留在 DOM 管值与 change 事件（既有监听不动，元素身份不变），
   视觉与交互由触发框 + 浮层面板接管：键盘可达（↑↓ Enter Esc Home End）、
   点外即关、选中打勾、贴视口下缘自动上翻。不依赖试验性的
   appearance:base-select（Firefox/Safari 尚未默认支持，跨浏览器一致）。 */
function selxSync(sel) {
  const wrap = sel.closest(".selx");
  if (!wrap) return;
  const o = sel.selectedOptions[0];
  const prov = o?.dataset.prov || "";
  wrap.querySelector(".selx-label").textContent =
    prov ? `${prov} ｜ ${o.textContent}` : (o?.textContent ?? "");
  wrap.querySelector(".selx-btn").disabled = sel.disabled;
}
function selxRebuild(sel) {
  const list = sel.closest(".selx").querySelector(".selx-list");
  list.innerHTML = "";
  for (const o of sel.options) {
    if (o.hidden) continue;
    const row = document.createElement("div");
    row.className = "selx-opt" + (o.selected ? " on" : "") + (o.disabled ? " dis" : "");
    row.dataset.value = o.value;
    const prov = o.dataset.prov || "";
    row.innerHTML = (prov ? `<span class="selx-prov">${esc(prov)}</span>` : "") +
      `<span class="selx-txt">${esc(o.textContent)}</span>` +
      (o.selected ? `<i class="selx-check"></i>` : "");
    list.append(row);
  }
}
function enhanceSelect(sel) {
  if (sel.dataset.selx || sel.multiple) return;
  sel.dataset.selx = "1";
  const wrap = document.createElement("div");
  wrap.className = "selx";
  sel.replaceWith(wrap);
  wrap.append(sel);
  sel.classList.add("selx-native");

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "selx-btn";
  btn.innerHTML = `<span class="selx-label"></span><i class="selx-chev"></i>`;
  const panel = document.createElement("div");
  panel.className = "selx-panel";
  const list = document.createElement("div");
  list.className = "selx-list";
  panel.append(list);
  wrap.append(btn, panel);

  const paint = () => [...list.children].forEach((r, i) =>
    r.classList.toggle("cur", i === cur));
  const choose = (row) => {
    if (!row || row.classList.contains("dis")) return;
    if (sel.value !== row.dataset.value) {
      sel.value = row.dataset.value;
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    selxSync(sel);
    close();
    btn.focus();
  };
  const close = () => wrap.classList.remove("open");
  let cur = -1;
  const open = () => {
    selxRebuild(sel);
    selxSync(sel);
    wrap.classList.add("open");
    const on = list.querySelector(".on");
    cur = Math.max(0, [...list.children].indexOf(on));
    paint();
    // 贴视口下缘翻到上方展开
    const r = btn.getBoundingClientRect();
    wrap.classList.toggle("up",
      r.bottom + Math.min(panel.scrollHeight, 300) + 14 > innerHeight &&
      r.top - Math.min(panel.scrollHeight, 300) - 14 > 0);
    panel.scrollTop = on ? Math.max(0, on.offsetTop - 120) : 0;
  };

  btn.addEventListener("click", () => wrap.classList.contains("open") ? close() : open());
  btn.addEventListener("keydown", (e) => {
    const keys = ["ArrowDown", "ArrowUp", "Enter", " "];
    if (!wrap.classList.contains("open") && keys.includes(e.key)) {
      e.preventDefault(); open(); return;
    }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      cur = Math.min(Math.max(cur + (e.key === "ArrowDown" ? 1 : -1), 0),
                     list.children.length - 1);
      paint();
      list.children[cur]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault(); choose(list.children[cur]);
    } else if (e.key === "Escape") { close(); }
    else if (e.key === "Home") { e.preventDefault(); cur = 0; paint(); }
    else if (e.key === "End") {
      e.preventDefault(); cur = list.children.length - 1; paint();
    }
  });
  list.addEventListener("click", (e) => {
    const row = e.target.closest(".selx-opt");
    if (row) choose(row);
  });
  selxSync(sel);
}
function enhanceAllSelects(root = document) {
  root.querySelectorAll("select").forEach(enhanceSelect);
}
/* 动态渲染的 select（编队卡/弹窗模板）落进 DOM 即增强 */
new MutationObserver((muts) => {
  for (const m of muts) for (const n of m.addedNodes) {
    if (n.nodeType !== 1) continue;
    if (n.tagName === "SELECT") enhanceSelect(n);
    else if (n.querySelector) n.querySelectorAll("select").forEach(enhanceSelect);
  }
}).observe(document.body, { childList: true, subtree: true });
/* 点面板外即收起（pointerdown 捕获触发框内外的边界情形） */
document.addEventListener("pointerdown", (e) => {
  document.querySelectorAll(".selx.open").forEach(w => {
    if (!w.contains(e.target)) w.classList.remove("open");
  });
});
enhanceAllSelects();
