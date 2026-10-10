"use strict";
/* 律法夕惕者 Xitilex 前端。無 build step，原生 JS。
   © 2026 無名小律師（楊朝淵律師）. Released under the MIT License. */

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  meta: null, cases: [], current: null, detail: null, sub: "", detailTab: "overview",
  filter: { q: "", status: "使用中", group: "", type: "" },
  sort: "recent", scope: "case", ui: {},
  chat: null, running: null,
};

/* ---------------- 縮放（Ctrl＋＋／－／0） ---------------- */
function zoomKeyDir(e) {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return 0;
  if (e.key === "+" || e.key === "=" || e.code === "NumpadAdd") return 1;
  if (e.key === "-" || e.key === "_" || e.code === "NumpadSubtract") return -1;
  if (e.key === "0" || e.code === "Numpad0") return 2;          // 2＝恢復 100%
  return 0;
}
function nativeApi() {
  try { const w = window.top; return w.pywebview && w.pywebview.api && w.pywebview.api.zoom ? w.pywebview.api : null; }
  catch { return null; }
}
document.addEventListener("keydown", e => {
  const dir = zoomKeyDir(e), api = dir && nativeApi();
  if (!api) return;                                              // 一般瀏覽器：交給瀏覽器
  e.preventDefault();
  api.zoom(dir).then(f => { if (typeof toast === "function" && f) toast("縮放 " + Math.round(f * 100) + "%"); }, () => { });
}, true);
// Ctrl＋滑鼠滾輪縮放不經過上面那段；畫面像素比一變就請程式記下目前倍率
let lastDpr = window.devicePixelRatio, dprTimer = 0;
window.addEventListener("resize", () => {
  if (window.devicePixelRatio === lastDpr) return;
  lastDpr = window.devicePixelRatio;
  clearTimeout(dprTimer);
  dprTimer = setTimeout(() => {
    const api = nativeApi();
    if (api && api.remember_zoom) api.remember_zoom().catch(() => { });
  }, 500);
});

/* ---------------- 分頁／視窗 ----------------
   系統畫面放在分頁外殼（shell.html）的 iframe 裡；開分頁、開視窗、改標題都請外殼處理。 */
const EMBEDDED = window.parent !== window;
function toShell(msg) { if (EMBEDDED) window.parent.postMessage(msg, location.origin); }
function openInNewTab(params = {}, focus = true) {
  if (EMBEDDED) toShell({ type: "newTab", params, focus });
  else window.open("/?" + new URLSearchParams(params), "_blank");
}
async function openInNewWindow(params = {}) {
  if (EMBEDDED) return toShell({ type: "newWindow", params });
  window.open("/?" + new URLSearchParams(params), "_blank", "width=1400,height=900");
}
function setDocTitle(t) {
  document.title = t ? t + " — 律法夕惕者 Xitilex" : "律法夕惕者 Xitilex";
  toShell({ type: "title" });
}

const STORE = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 私密視窗等情況，忽略 */ } },
};

async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { }
    const err = new Error(msg); err.status = r.status;
    throw err;
  }
  return r.json();
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, 2600);
}

const fmtTime = ts => {
  const d = new Date(ts * 1000), p = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}/${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
};
const fmtSize = b => b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(0) + " KB" : (b / 1048576).toFixed(1) + " MB";
const today = () => {   // 本地日期；toISOString 是 UTC，台灣早上八點前會變成昨天
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
function dueClass(due, done) {
  if (!due || done) return "";
  const days = (new Date(due) - new Date(today())) / 86400000;
  return days < 0 ? "overdue" : days <= 7 ? "soon" : "";
}
const icon = name => `<svg class="icon" aria-hidden="true"><use href="/static/icons.svg#${name}"/></svg>`;
const pill = s => `<span class="pill ${s ? "s-" + esc(s) : "s-none"}">${esc(s || "未標示")}</span>`;

/* ---------------- 迷你 Markdown ---------------- */
function md(src) {
  const lines = String(src || "").replace(/\r/g, "").split("\n");
  let out = "", list = null, inCode = false, code = [], table = [];
  const inline = s => esc(s)
    .replace(/`([^`]+)`/g, (_, c) => `<code${/[\\/.]/.test(c) && !/\s{2}/.test(c) ? ' class="path" data-path="' + c + '"' : ""}>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  const closeList = () => { if (list) { out += `</${list}>`; list = null; } };
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r));
    out += "<table>" + rows.map((r, i) => "<tr>" + r.replace(/^\s*\||\|\s*$/g, "").split("|")
      .map(c => i === 0 ? `<th>${inline(c.trim())}</th>` : `<td>${inline(c.trim())}</td>`).join("") + "</tr>").join("") + "</table>";
    table = [];
  };
  for (const raw of lines) {
    if (raw.startsWith("```")) {
      if (inCode) { out += `<pre><code>${esc(code.join("\n"))}</code></pre>`; code = []; inCode = false; }
      else { closeList(); flushTable(); inCode = true; }
      continue;
    }
    if (inCode) { code.push(raw); continue; }
    if (/^\s*\|.*\|\s*$/.test(raw)) { closeList(); table.push(raw); continue; } else flushTable();
    let m;
    if ((m = raw.match(/^(#{1,4})\s+(.*)/))) { closeList(); out += `<h${m[1].length + 1}>${inline(m[2])}</h${m[1].length + 1}>`; }
    else if ((m = raw.match(/^\s*[-*]\s+\[( |x|X)\]\s+(.*)/))) { if (list !== "ul") { closeList(); out += "<ul>"; list = "ul"; } out += `<li>${m[1] === " " ? "☐" : "☑"} ${inline(m[2])}</li>`; }
    else if ((m = raw.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { closeList(); out += "<ul>"; list = "ul"; } out += `<li>${inline(m[1])}</li>`; }
    else if ((m = raw.match(/^\s*\d+[.)、]\s+(.*)/))) { if (list !== "ol") { closeList(); out += "<ol>"; list = "ol"; } out += `<li>${inline(m[1])}</li>`; }
    else if ((m = raw.match(/^>\s?(.*)/))) { closeList(); out += `<blockquote>${inline(m[1])}</blockquote>`; }
    else if (!raw.trim()) { closeList(); }
    else { closeList(); out += `<p>${inline(raw)}</p>`; }
  }
  if (inCode) out += `<pre><code>${esc(code.join("\n"))}</code></pre>`;
  closeList(); flushTable();
  return out;
}

/* ---------------- 案件清單 ---------------- */
async function loadMeta() {
  state.meta = await api("/api/meta");
  $("#rootInfo").textContent = state.meta.root_exists ? state.meta.root : "⚠ 找不到案件根目錄：" + state.meta.root;
  $("#rootInfo").title = state.meta.root;
  const chips = ["使用中", "全部", ...state.meta.statuses, "未標示", INBOX_CHIP];
  $("#statusFilter").innerHTML = chips.map(s => `<button class="chip" data-s="${esc(s)}">${esc(s)}</button>`).join("");
  $("#statusFilter").title = "「使用中」＝已結案以外的全部";
  if (state.meta.claude_credentials !== "正常") $("#claudeStatus").textContent = "⚠ " + state.meta.claude_credentials;
  const ML = { "": "預設", fable: "Fable", opus: "Opus", sonnet: "Sonnet", haiku: "Haiku" };
  const EL = { "": "預設", low: "低", medium: "中", high: "高", xhigh: "很高", max: "最高" };
  $("#modelSel").innerHTML = state.meta.models.map(m => `<option value="${m}">${ML[m] || m}</option>`).join("");
  $("#effortSel").innerHTML = state.meta.efforts.map(m => `<option value="${m}">${EL[m] || m}</option>`).join("");
}

async function loadCases(refresh = false) {
  state.cases = await api("/api/cases" + (refresh ? "?refresh=1" : ""));
  const groups = [...new Set(state.cases.map(c => c.group))].sort();
  const sel = $("#groupFilter"), keep = state.filter.group;
  sel.innerHTML = `<option value="">全部資料夾（${state.cases.length}）</option>` +
    groups.map(g => `<option value="${esc(g)}">${esc(g)}（${state.cases.filter(c => c.group === g).length}）</option>`).join("");
  sel.value = keep;
  renderList();
}

/* skip：計數時略過哪一個篩選條件（種類 chip 的數字要反映「其他條件下」各種類有幾件） */
function filtered(skip = "") {
  const { q, status, group, type } = state.filter, ql = q.trim().toLowerCase();
  return state.cases.filter(c => {
    if (group && c.group !== group) return false;
    if (status === "使用中" && c.status === "已結案") return false;
    if (status === "未標示" && c.status) return false;
    if (status === INBOX_CHIP && !c.new_docs) return false;
    if (!["使用中", "全部", "未標示", INBOX_CHIP].includes(status) && c.status !== status) return false;
    if (skip !== "type" && type && c.ctype !== type) return false;
    if (ql && !(c.name + " " + c.group + " " + c.ctype).toLowerCase().includes(ql)) return false;
    return true;
  });
}

function sortCases(list) {
  const by = state.sort;
  const typeIdx = t => { const i = state.meta.types.indexOf(t); return i < 0 ? 99 : i; };
  return [...list].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;           // 釘選的永遠在最上面
    if (by === "code") return a.code.localeCompare(b.code, "en", { numeric: true });
    if (by === "type" && a.ctype !== b.ctype) return typeIdx(a.ctype) - typeIdx(b.ctype);
    return b.mtime - a.mtime;
  });
}

function caseItem(c) {
  return `<li class="case-item ${state.current === c.id ? "active" : ""} ${c.pinned ? "pinned" : ""}" data-id="${c.id}">
      <div class="ci-top"><span class="ci-name" title="${esc(c.client)}">${esc(c.client)}</span>
        ${c.pinned ? `<span class="pin" title="已釘選">${icon("pin")}</span>` : ""}<span class="ci-code">${esc(c.code)}</span></div>
      <div class="ci-cause" title="${esc(c.cause || c.category)}">${esc(c.cause || c.category)}</div>
      <div class="ci-sub">${pill(c.status)}<span class="ci-type">${esc(c.ctype)}</span>
        ${c.new_docs ? `<span class="badge-new" title="有 ${c.new_docs} 份新收文書">${icon("inbox")} ${c.new_docs}</span>` : ""}
        ${c.open_todos ? `<span class="badge-todo">待辦 ${c.open_todos}</span>` : ""}</div>
    </li>`;
}

function renderList() {
  document.querySelectorAll("#statusFilter .chip").forEach(b => b.classList.toggle("on", b.dataset.s === state.filter.status));
  const inboxChip = document.querySelector(`#statusFilter .chip[data-s="${INBOX_CHIP}"]`);
  if (inboxChip) {
    const n = state.cases.filter(c => c.new_docs).length;
    inboxChip.innerHTML = `${icon("inbox")} 新收文書${n ? `<span class="n">${n}</span>` : ""}`;
    inboxChip.classList.toggle("has", n > 0);
  }
  // 種類 chips：數字依其他篩選條件即時計算
  const base = filtered("type"), counts = {};
  base.forEach(c => counts[c.ctype] = (counts[c.ctype] || 0) + 1);
  $("#typeFilter").innerHTML = `<button class="chip ${state.filter.type ? "" : "on"}" data-t="">全部種類</button>` +
    state.meta.types.filter(t => counts[t] || state.filter.type === t).map(t =>
      `<button class="chip ${state.filter.type === t ? "on" : ""}" data-t="${esc(t)}">${esc(t)}<span class="n">${counts[t] || 0}</span></button>`).join("");

  const list = sortCases(filtered()), LIMIT = 400;
  const pinnedN = list.filter(c => c.pinned).length;
  $("#caseCount").textContent = `${list.length} 件${pinnedN ? `・釘選 ${pinnedN}` : ""}・${{ recent: "依最近更動", type: "依種類分組", code: "依代號" }[state.sort]}`;
  let html = "", lastHead = null;
  list.slice(0, LIMIT).forEach(c => {
    const head = c.pinned ? "釘選案件" : state.sort === "type" ? c.ctype : (pinnedN ? "其他案件" : null);
    if (head !== lastHead && head) {
      const n = c.pinned ? pinnedN : list.filter(x => !x.pinned && (state.sort === "type" ? x.ctype === c.ctype : true)).length;
      html += `<li class="list-head">${esc(head)}<span>${n}</span></li>`;
    }
    lastHead = head;
    html += caseItem(c);
  });
  if (list.length > LIMIT) html += `<li class="muted small" style="padding:8px 12px">還有 ${list.length - LIMIT} 件，請用搜尋或篩選縮小範圍</li>`;
  $("#caseList").innerHTML = html;
  if (state.scope === "list") renderScopeLabel();
  renderFilterSummary();
}

/* ---------------- 左欄：篩選區收折、欄寬拖曳 ---------------- */
function renderFilterSummary() {
  const f = state.filter, parts = [f.status];
  if (f.type) parts.push(f.type);
  if (f.group) parts.push(f.group);
  parts.push({ recent: "最近更動", type: "依種類", code: "依代號" }[state.sort] || "");
  $("#filterSummary").textContent = parts.filter(Boolean).join("・");
}

function setFilterCollapsed(on) {
  $(".sidebar").classList.toggle("filters-collapsed", on);
  $("#filterToggle").setAttribute("aria-expanded", String(!on));
  STORE.set("casedesk.filtersCollapsed", on);
}

/* 拖曳分隔線調整欄寬：寬度存在 CSS 變數，記在本機 */
function makeResizable(handle, cssVar, storeKey, { min, max, def, fromRight }) {
  const layout = $("#viewCases");
  const apply = w => { layout.style.setProperty(cssVar, Math.round(w) + "px"); };
  const saved = STORE.get(storeKey, null);
  if (saved) apply(Math.min(max, Math.max(min, saved)));
  handle.addEventListener("pointerdown", e => {
    e.preventDefault();
    const rect = layout.getBoundingClientRect();
    document.body.classList.add("resizing");
    // 移動與放開都聽整個視窗：滑鼠拖出分隔線（或拖過 Claude 對話區）時才不會斷掉
    const move = ev => {
      const w = fromRight ? rect.right - ev.clientX : ev.clientX - rect.left;
      apply(Math.min(max, Math.max(min, w)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
      document.body.classList.remove("resizing");
      STORE.set(storeKey, parseInt(getComputedStyle(layout).getPropertyValue(cssVar)) || def);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  });
  handle.addEventListener("dblclick", () => { apply(def); STORE.set(storeKey, null); });
}

/* ---------------- 右鍵選單 ---------------- */
function showCtx(x, y, c) {
  const menu = $("#ctxMenu");
  menu.innerHTML = `
    <div class="ctx-title">${esc(c.code)} ${esc(c.client)}</div>
    <button data-cmd="tab">在新分頁開啟</button>
    <button data-cmd="window">在新視窗開啟</button>
    <div class="ctx-sep"></div>
    <button data-cmd="folder">📂 在檔案總管開啟資料夾</button>
    <button data-cmd="pin">${c.pinned ? "取消釘選" : "📌 釘選到最上面"}</button>
    <button data-cmd="claude">💬 叫 Claude 處理這件</button>
    <button data-cmd="copy">複製資料夾路徑</button>
    <div class="ctx-sep"></div>
    <div class="ctx-label">設定狀態</div>
    <div class="ctx-status">${state.meta.statuses.map(s => `<button data-cmd="status" data-v="${esc(s)}" class="${c.status === s ? "on" : ""}">${pill(s)}</button>`).join("")}</div>`;
  menu.dataset.id = c.id;
  menu.hidden = false;
  const r = menu.getBoundingClientRect();
  menu.style.left = Math.min(x, innerWidth - r.width - 8) + "px";
  menu.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
}
function hideCtx() { $("#ctxMenu").hidden = true; }

async function patchMeta(id, meta, msg) {
  try {
    const c = await api(`/api/case/${id}/meta`, { method: "PATCH", body: { meta } });
    syncCaseIntoList(c);
    if (state.current === id) openCase(id, true);
    toast(msg);
  } catch (e) { toast(e.message); }
}

async function ctxCommand(cmd, id, v) {
  const c = state.cases.find(x => x.id === id);
  if (!c) return;
  if (cmd === "tab") return openInNewTab({ case: id });
  if (cmd === "window") return openInNewWindow({ case: id });
  if (cmd === "folder") api(`/api/case/${id}/reveal`, { method: "POST", body: { rel: "" } }).catch(e => toast(e.message));
  else if (cmd === "pin") patchMeta(id, { "釘選": c.pinned ? "" : "是" }, c.pinned ? "已取消釘選" : "已釘選");
  else if (cmd === "status") patchMeta(id, { "案件狀態": v }, "狀態已改為「" + v + "」");
  else if (cmd === "copy") {
    try { await navigator.clipboard.writeText(c.path); toast("已複製路徑"); } catch { prompt("資料夾路徑", c.path); }
  } else if (cmd === "claude") {
    setScope("case"); await openCase(id); $("#askInput").focus();
  }
}

/* ---------------- 案件內容 ---------------- */
async function openCase(id, keepSub = false) {
  const changed = state.current !== id;
  if (changed) {
    if (summaryDirty()) saveSummary(false, true);      // 還沒存的摘要先存
    state.sumEdit = null; state.rowEdit = null; state.detailTab = "overview";
    setAllowFiles(false);
  }
  state.current = id;
  if (!keepSub || changed) state.sub = "";
  renderList();
  let detail;
  try {
    detail = await api(`/api/case/${id}`);
  } catch (e) { if (state.current === id) toast(e.message); return; }
  if (state.current !== id) return;      // 等待期間已切到別件：這份回應作廢，不能蓋掉
  state.detail = detail;
  if (!$("#viewCases").hidden) setDocTitle(`${detail.case.code} ${detail.case.client}`);
  syncCaseIntoList(state.detail.case);
  renderDetail();
  if (changed) $("#detail").scrollTop = 0;
  loadFiles();
  if (changed && state.scope === "case") loadChat();
  renderScopeLabel();
}

function syncCaseIntoList(c) {
  const i = state.cases.findIndex(x => x.id === c.id);
  if (i >= 0) state.cases[i] = c;
  renderList();
}

/* 子案（例如集團客戶 SP001 底下的多件訴訟）：事由開頭的子案號換成「對造 子案號」標籤 */
const SUB_RE = /^\s*([A-Z]{1,3}\d{2,5}[A-Z]?)(?:[\s：:｜|、,，\-]+|(?=[^\x00-\x7f])|$)([\s\S]*)$/;
function subParts(text) {
  const subs = state.detail?.card.subcases || [];
  const m = SUB_RE.exec(text || "");
  const s = m && subs.find(x => x.code === m[1]);
  return s ? { chip: `<span class="sub-chip" title="子案 ${esc(s.code)}">${esc(s.name)} ${esc(s.code)}</span>`, rest: m[2].trim() } : { chip: "", rest: text };
}
function subSelect(id, selected = "") {
  const subs = state.detail?.card.subcases || [];
  if (!subs.length) return "";
  return `<select id="${id}" class="sub-select" title="子案"><option value="">（不屬子案）</option>${subs.map(x => `<option value="${esc(x.code)}" ${x.code === selected ? "selected" : ""}>${esc(x.name)} ${esc(x.code)}</option>`).join("")}</select>`;
}
/* 待辦／庭期文字拆成 子案號＋其餘（編輯時分開放進子案選單與文字框） */
function subSplit(text) {
  const subs = state.detail?.card.subcases || [];
  const m = SUB_RE.exec(text || "");
  return m && subs.some(x => x.code === m[1]) ? { code: m[1], rest: m[2].trim() } : { code: "", rest: text || "" };
}
const withSub = (selId, text) => { const v = $("#" + selId)?.value; return v ? (v + " " + text).trim() : text; };

/* 存檔、Claude 改完、衝突重新載入時，案件頁會整個重畫。重畫前把「還沒存的輸入」
   與游標位置記下來，重畫後放回去，正在打的字才不會被洗掉。 */
let lastRendered = { id: null, inputs: null };
function snapshotInputs() {
  const out = {};
  $("#detail").querySelectorAll("input[id], input[data-field], select[data-field], select.sub-select, textarea[id]").forEach(el => {
    const key = el.id || "f:" + el.dataset.field;
    if (el.type === "checkbox") return;
    out[key] = { value: el.value, initial: el.defaultValue ?? "" };
    if (el === document.activeElement) {
      out[key].focus = true;
      try { out[key].sel = [el.selectionStart, el.selectionEnd]; } catch { }
    }
  });
  return out;
}
function restoreInputs(snap) {
  for (const [key, s] of Object.entries(snap)) {
    const el = key.startsWith("f:") ? $(`#detail [data-field="${CSS.escape(key.slice(2))}"]`) : $("#detail #" + CSS.escape(key));
    if (!el) continue;
    if (el.classList.contains("sub-select")) {                // 子案選單：保留上次選的子案
      if ([...el.options].some(o => o.value === s.value)) el.value = s.value;
    } else if (el.tagName !== "SELECT" && s.value !== s.initial && s.value !== el.value) {
      // 只放回「使用者改過、還沒存」的值。程式設定的值離開欄位時不會觸發 change，
      // 所以標成 dirty，由 focusout 補存（見 bind）
      el.value = s.value;
      if (el.dataset.field) el.dataset.dirty = "1";
    }
    if (s.focus) {
      el.focus();
      try { if (s.sel) el.setSelectionRange(s.sel[0], s.sel[1]); } catch { }
    }
  }
}

function renderDetail() {
  const sameCase = lastRendered.id === state.detail.case.id && $("#detail .case-head");
  const snap = sameCase ? snapshotInputs() : null;
  renderDetailInner();
  lastRendered.id = state.detail.case.id;
  if (snap) restoreInputs(snap);
  // 案件頁整個重畫後，把已讀到的卷宗清單放回去（編輯摘要、待辦等只重畫畫面，不會重讀檔案）
  if (filesData && filesFor === state.current + "|" + state.sub) renderFiles();
}

function renderDetailInner() {
  const { case: c, card } = state.detail, m = card.meta || {};
  const opts = ["", ...state.meta.statuses].map(s => `<option value="${esc(s)}" ${s === (m["案件狀態"] || "") ? "selected" : ""}>${s || "（未標示）"}</option>`).join("");
  const field = k => `<label>${k}</label><input data-field="${k}" aria-label="${k}" value="${esc(m[k] || "")}" placeholder="—">`;
  const typeSel = `<label>案件種類</label><select data-field="案件類型" aria-label="案件種類">
    <option value="">自動判斷（${esc(c.ctype_auto)}）</option>
    ${state.meta.types.map(t => `<option ${m["案件類型"] === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
  const notes = (card.notes || []).filter(n => n.content.trim() && n.heading !== SUMMARY);
  const summary = summaryText(card);
  const ed = editingRow(), sumEd = state.sumEdit && state.sumEdit.cid === c.id ? state.sumEdit : null;
  $("#detail").innerHTML = `
    <div class="case-head">
      <div class="case-heading">
        <div class="code">${esc(c.code)} · ${esc(c.ctype)} · ${esc(c.group)}</div>
        <h1>${esc(c.client || c.name)}</h1>
        ${c.cause ? `<div class="case-cause">${esc(c.cause)}</div>` : ""}
        <div class="crumbs">${esc(c.rel)}</div>
      </div>
      <div class="head-actions">
        <button class="btn ${c.pinned ? "pinned-btn" : ""}" id="pinCase" title="${c.pinned ? "取消釘選" : "釘選到清單最上面"}">${icon("pin")}${c.pinned ? "已釘選" : "釘選"}</button>
        <select class="status-select" id="statusSel" aria-label="案件狀態">${opts}</select>
        <button class="btn" id="revealCase">${icon("folder")}開啟資料夾</button>
      </div>
    </div>
    ${inboxBar()}
    <nav class="detail-tabs" role="tablist" aria-label="案件內容">
      ${[["overview", "總覽"], ["files", "卷宗檔案"], ["notes", "案件摘要"]].map(([key, label]) => `<button class="detail-tab" role="tab" id="detailTab-${key}" data-detail-tab="${key}" aria-controls="${key === "files" ? "detailFiles" : key === "notes" ? "detailNotes" : "detailOverview"}">${label}</button>`).join("")}
    </nav>
    <div id="detailOverview" role="tabpanel" aria-labelledby="detailTab-overview">
      ${priorityStrip(card)}
    <div class="overview-todos">
      <div class="card">
        <div class="card-title">待辦事項<span class="right muted small">${card.todos.filter(t => !t.done).length} 項未完成
          <button class="btn ghost small" id="openDeadline" title="依送達日計算上訴、抗告等法定期間，直接加入待辦">${icon("clock")}期限計算</button></span></div>
        <ul class="todo-list">${card.todos.length ? card.todos.map((t, i) => ed && ed.kind === "todo" && ed.i === i ? todoEditRow(t, i) : `
          <li class="todo ${t.done ? "done" : ""}" data-i="${i}">
            <input type="checkbox" ${t.done ? "checked" : ""} data-act="toggle" aria-label="${esc(t.text)}：完成狀態">
            ${t.due ? `<span class="due ${dueClass(t.due, t.done)}">${esc(t.due)}</span>` : ""}
            <span class="txt" data-act="edit" title="點兩下修改">${(p => p.chip + esc(p.rest))(subParts(t.text))}</span>
            <button class="edit" data-act="edit" title="修改這條待辦">${icon("edit")}</button>
            <button class="del" data-act="del" title="刪除">${icon("close")}</button>
          </li>`).join("") : `<li class="no-todo">沒有待辦</li>`}</ul>
        <form class="todo-add" id="todoAdd">
          ${subSelect("tSub")}
          <input type="text" id="todoText" placeholder="新增待辦…">
          <input type="date" id="todoDue" title="期限（可空白）">
          <button class="btn small" type="submit">新增</button>
        </form>
      </div>
    </div>

    <div class="grid2">
      <div class="card">
        <div class="card-title">案件資訊<span class="right muted small">欄位可直接修改</span></div>
        <div class="fields">${typeSel}${["案號", "法院", "股別", "對造", "委任日"].map(field).join("")}
          <label>下次期日</label><div class="computed">${card.next ? esc(card.next) : `<span class="muted">—（由庭期自動帶出）</span>`}</div>
        </div>
        <p class="card-updated">${card.mtime ? "更新於 " + fmtTime(card.mtime) : "第一次編輯時建立案件卡"}</p>
      </div>
      <div class="card">
        <div class="card-title">庭期<span class="right muted small" id="gcalLine">${gcalLine(state.detail.gcal)}</span></div>
        <ul class="todo-list">${(card.hearings || []).length ? card.hearings.map((h, i) => ed && ed.kind === "hearing" && ed.i === i ? hearingEditRow(h, i) : `
          <li class="todo hearing ${h.date < today() ? "past" : ""}" data-i="${i}">
            <span class="due ${dueClass(h.date, false)}">${esc(h.date)}${h.time ? " " + esc(h.time) : ""}</span>
            <span class="txt" data-act="hedit" title="點兩下修改">${(p => p.chip + esc(p.rest || "（未填事由）"))(subParts(h.text))}</span>
            <button class="edit" data-act="hedit" title="修改這筆庭期">${icon("edit")}</button>
            <button class="del" data-act="hdel" title="刪除">${icon("close")}</button>
          </li>`).join("") : `<li class="no-todo">沒有庭期</li>`}</ul>
        <form class="todo-add" id="hearingAdd">
          ${subSelect("hSub")}
          <input type="date" id="hDate" title="日期" required>
          <input type="time" id="hTime" title="時間（可空白）">
          <input type="text" id="hText" placeholder="事由（法庭），例如 言詞辯論（第12法庭）">
          <button class="btn small" type="submit">新增</button>
        </form>
      </div>
    </div>

    </div>
    <div id="detailNotes">
    <div class="card summary-card">
      <div class="card-title">案件摘要<span class="right">${sumEd ? `<span class="muted small">編輯中</span>`
        : `<button class="btn ghost small" id="sumEdit" title="直接打字修改案件摘要（點兩下內容也可以）">${icon("edit")}編輯</button>`}</span></div>
      ${sumEd ? `<textarea id="sumText" class="sum-text" spellcheck="false" placeholder="例如：\n- 案情：……\n- 程序：……\n- 下一步：……">${esc(sumEd.base)}</textarea>
        <div class="sum-actions"><span class="muted small">Ctrl+S 儲存・Esc 取消・可用 Markdown（- 開頭成清單、**粗體**）・離開編輯框會自動存</span>
          <span class="grow"></span><button class="btn small" type="button" id="sumCancel">取消</button>
          <button class="btn primary small" type="button" id="sumSave">儲存</button></div>`
      : summary ? `<div class="md sum-view" data-act="sumedit" title="點兩下編輯">${md(summary)}</div>`
      : `<div class="sum-empty muted" data-act="sumedit">還沒有摘要。按右上「編輯」或在這裡點兩下，就可以直接打字。</div>`}
    </div>

    ${notes.length ? `<div class="card notes">
      <div class="card-title">案件卡筆記<span class="right"><button class="btn ghost small" id="openCard">用 Markdown 軟體開啟</button></span></div>
      ${notes.map(n => `<h3>${esc(n.heading)}</h3><div class="md">${md(n.content)}</div>`).join("")}
    </div>` : ""}

    </div>
    <div id="detailFiles" role="tabpanel" aria-labelledby="detailTab-files">
    <div class="card">
      <div class="card-title">卷宗檔案<span class="right"><button class="btn ghost small" id="refreshFiles">重新整理</button></span></div>
      <div class="crumbbar" id="crumbs"></div>
      <div id="files"><div class="files-empty">讀取中…</div></div>
    </div>

    </div>
  `;
  setDetailTab(state.detailTab);
  renderScopeLabel();
}

function setDetailTab(tab, resetScroll = false) {
  if (!["overview", "files", "notes"].includes(tab)) return;
  state.detailTab = tab;
  document.querySelectorAll("[data-detail-tab]").forEach(b => {
    const on = b.dataset.detailTab === tab;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
  });
  $("#detailOverview").hidden = tab !== "overview";
  $("#detailFiles").hidden = tab !== "files";
  $("#detailNotes").hidden = tab === "files";
  $("#detailNotes").setAttribute("role", tab === "notes" ? "tabpanel" : "region");
  $("#detailNotes").setAttribute("aria-labelledby", "detailTab-notes");
  if (resetScroll) $("#detail").scrollTop = 0;
}

function priorityStrip(card) {
  const todo = [...card.todos].filter(t => !t.done && t.due).sort((a, b) => a.due.localeCompare(b.due))[0];
  const hearing = [...(card.hearings || [])].filter(h => h.date >= today()).sort((a, b) => (a.date + (a.time || "99:99")).localeCompare(b.date + (b.time || "99:99")))[0];
  const dc = todo ? dueClass(todo.due, false) : "";
  const date = d => esc(d.replace(/-/g, "/"));
  return `<div class="priority-strip">
    <div class="priority-item ${dc}"><div class="priority-label">${icon("clock")}最近期限${dc ? `<span class="priority-badge">${dc === "overdue" ? "已逾期" : "七日內"}</span>` : ""}</div>
      <div class="priority-date">${todo ? date(todo.due) : "尚無期限"}</div><div class="priority-text">${todo ? esc(todo.text) : "有期限的未完成待辦會顯示在這裡"}</div></div>
    <div class="priority-item"><div class="priority-label">${icon("calendar")}下一次庭期</div>
      <div class="priority-date">${hearing ? date(hearing.date) + (hearing.time ? " · " + esc(hearing.time) : "") : "尚無庭期"}</div><div class="priority-text">${hearing ? esc(hearing.text || "未填事由") : "尚未安排接下來的庭期"}</div></div>
  </div>`;
}

/* ---------- 新收文書提醒 ---------- */
const INBOX_CHIP = "新收文書";
function inboxBar() {
  const list = state.detail?.inbox || [];
  if (!list.length) return "";
  const total = state.detail.case.new_docs || list.length;
  const open = state.inboxOpen === state.detail.case.id, SHOW = 6;
  const rows = (open ? list : list.slice(0, SHOW)).map(f => {
    const parts = f.rel.split(/[\\/]/), name = parts.pop();
    return `<li><span class="fname" data-act="ibopen" data-rel="${esc(f.rel)}" title="用預設程式開啟">${esc(name)}</span>
      <span class="muted small">${esc(parts.join(" › ") || "（最上層）")}・${fmtTime(f.mtime).slice(0, 10)}</span>
      <button class="ib-ok" data-act="iback" data-rel="${esc(f.rel)}" title="這份標為已看過">✓</button></li>`;
  }).join("");
  return `<div class="inbox-bar">
    <div class="ib-head"><b>📥 有 ${total} 份新收文件</b><span class="muted small">上次看過之後新增</span>
      <span class="right">
        <button class="btn primary small" id="inboxClaude" title="請 Claude 讀這些文件，把庭期、法定期限寫進案件卡">請 Claude 讀取並更新庭期、期限</button>
        <button class="btn small" id="inboxAck">全部標為已看過</button></span></div>
    <ul class="ib-list">${rows}</ul>
    ${list.length > SHOW ? `<a class="link small" id="inboxMore">${open ? "收起" : `顯示全部 ${list.length} 份`}</a>` : ""}
  </div>`;
}
async function inboxAck(files) {
  const cid = state.current;
  try {
    const r = await api(`/api/case/${cid}/inbox/ack`, { method: "POST", body: { files: files || null } });
    if (state.current !== cid) return;
    state.detail.inbox = r.inbox; state.detail.case.new_docs = r.left;
    syncCaseIntoList(state.detail.case); renderDetail();
  } catch (e) { toast(e.message); }
}
async function inboxToClaude() {
  const list = state.detail?.inbox || [], cid = state.current;
  if (!list.length) return;
  if (state.running) { toast("Claude 正在處理其他事，等它做完再試"); return; }
  if ($("#viewCases").classList.contains("no-claude")) $("#toggleClaude").click();
  if (state.scope !== "case") setScope("case");
  const files = list.map(f => f.rel);
  const rest = typeof Deadline !== "undefined" ? await Deadline.restDaysText(150) : "";
  const prompt = `這件案件的資料夾有 ${files.length} 份新收到的文件（上次看過之後新增）：
${list.map(f => `- ${f.rel}（${fmtTime(f.mtime).slice(0, 10)}）`).join("\n")}

請閱讀這些文件（很多時，先依檔名判斷哪些是法院、檢察署或對造的來文，優先處理），然後：
1. 開庭通知、傳票：把庭期（日期、時間、法庭、事由）寫進案件卡的「## 庭期」。
2. 判決、裁定、處分書、補正命令等有法定期間或指定期間的文書：依送達日計算期限末日，寫進「## 待辦事項」，並在回覆裡寫出計算過程。
   計算規則：始日不算入；寄存送達自寄存日起經 10 日發生效力；以月定期間依民法第121條；末日為星期六、日或下列休息日時順延至次一上班日；有在途期間要另計。
   今天起的國定假日與補假：${rest || "（沒有資料，請自行查證）"}。
   送達日看不出來時，寫明你的假設並請我確認。
3. 對造書狀、當事人提供的資料：在「## 案件摘要」補一行收文紀錄與重點。
4. 最後列出你更新了哪些項目，以及需要我確認的地方。
不要刪除、搬移或改名任何檔案。`;
  const ok = await ask(prompt);
  if (ok && state.current === cid) { await inboxAck(files); toast("已把這些文件標為已看過"); }
  else if (ok) api(`/api/case/${cid}/inbox/ack`, { method: "POST", body: { files } }).catch(() => { });
}
/* 背景掃描的新收文書數：每分鐘更新一次清單上的數字 */
async function pollInboxCounts() {
  try {
    const r = await api("/api/inbox/counts");
    let changed = false;
    for (const c of state.cases) {
      const n = r.counts[c.id] || 0;
      if ((c.new_docs || 0) !== n) { c.new_docs = n; changed = true; }
    }
    if (changed) renderList();
  } catch { }
}

/* ---------- 利益衝突檢查 ---------- */
async function conflictLookup(clientText, oppText, exclude = "") {
  const ask = async t => t.trim() ? (await api("/api/conflict", { method: "POST", body: { names: [t], exclude } })).results : [];
  const [cl, op] = await Promise.all([ask(clientText), ask(oppText)]);
  return { cl, op };
}
/* 當事人在別案是對造、或對造在別案是本所當事人 → 紅色警示；其他命中只是參考 */
function conflictHtml({ cl, op }, { links = false, compact = false } = {}) {
  const caseLabel = h => `${esc(h.code)} ${esc(h.client)}${h.cause ? "｜" + esc(h.cause) : ""}${h.status ? `（${esc(h.status)}）` : ""}`;
  const link = h => links ? `<a class="link" data-open-case="${esc(h.id)}">${caseLabel(h)}</a>` : caseLabel(h);
  const red = [], info = [];
  for (const r of cl) for (const h of r.hits) {
    if (h.role === "對造") red.push(`當事人「${esc(r.name)}」曾是 ${link(h)} 的<b>對造</b>（${esc(h.via)}）`);
    else if (h.role === "當事人") info.push(`當事人「${esc(r.name)}」也是 ${link(h)} 的當事人`);
    else info.push(`「${esc(r.name)}」出現在 ${link(h)} 的案件卡：<span class="muted">${esc(h.via)}</span>`);
  }
  for (const r of op) for (const h of r.hits) {
    if (h.role === "當事人") red.push(`對造「${esc(r.name)}」是本所 ${link(h)} 的<b>當事人</b>`);
    else if (h.role === "對造") info.push(`對造「${esc(r.name)}」也是 ${link(h)} 的對造`);
    else info.push(`「${esc(r.name)}」出現在 ${link(h)} 的案件卡：<span class="muted">${esc(h.via)}</span>`);
  }
  const names = [...cl, ...op].map(r => r.name);
  if (!names.length) return "";
  if (!red.length && !info.length) return `<div class="cf-ok">✓ 沒有找到「${names.map(esc).join("、")}」的相關案件</div>`;
  const LIM = compact ? 4 : 999;
  const list = (arr, cls) => arr.length ? `<ul class="${cls}">${arr.slice(0, LIM).map(x => `<li>${x}</li>`).join("")}${arr.length > LIM ? `<li class="muted">…還有 ${arr.length - LIM} 筆</li>` : ""}</ul>` : "";
  return (red.length ? `<div class="cf-red-head">⚠ 可能有利益衝突，請確認</div>${list(red, "cf-red")}` : "") +
    (info.length ? `<div class="cf-info-head muted small">相關案件（參考）</div>${list(info, "cf-info")}` : "");
}
let ncConflictTimer = 0, ncConflictRed = 0;
function ncConflictCheck() {
  clearTimeout(ncConflictTimer);
  ncConflictTimer = setTimeout(async () => {
    const cl = $("#ncClient").value, op = $("#ncOpponent").value;
    if (!cl.trim() && !op.trim()) { $("#ncConflict").innerHTML = ""; ncConflictRed = 0; return; }
    try {
      const r = await conflictLookup(cl, op);
      if ($("#ncClient").value !== cl || $("#ncOpponent").value !== op) return;    // 期間又改了
      $("#ncConflict").innerHTML = conflictHtml(r, { compact: true });
      ncConflictRed = $("#ncConflict").querySelectorAll(".cf-red li").length;
    } catch { }
  }, 400);
}
function openConflictDlg() {
  const c = state.detail && !$("#viewCases").hidden ? state.detail : null;
  if (c && !$("#cfClient").value && !$("#cfOpp").value) {
    $("#cfClient").value = c.case.client;
    $("#cfOpp").value = c.card.meta?.["對造"] || "";
  }
  $("#cfResult").innerHTML = "";
  $("#conflictDlg").showModal();
}
async function runConflictDlg() {
  $("#cfResult").innerHTML = `<div class="muted">檢查中…</div>`;
  try { $("#cfResult").innerHTML = conflictHtml(await conflictLookup($("#cfClient").value, $("#cfOpp").value), { links: true }) || `<div class="muted">請輸入名字</div>`; }
  catch (e) { $("#cfResult").innerHTML = `<div class="dlg-err">${esc(e.message)}</div>`; }
}

/* ---------- 案件摘要（案件卡的「## 案件摘要」段） ---------- */
const SUMMARY = "案件摘要";
function summaryText(card) {
  return (card.notes || []).filter(n => n.heading === SUMMARY).map(n => n.content).join("\n\n").trim();
}
function startSummaryEdit() {
  if (!state.detail) return;
  state.sumEdit = { cid: state.detail.case.id, base: summaryText(state.detail.card) };
  renderDetail();
  const ta = $("#sumText");
  if (ta) { fitTextarea(ta); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
}
function fitTextarea(ta) { ta.style.height = "auto"; ta.style.height = Math.max(160, ta.scrollHeight + 4) + "px"; }
function summaryDirty() {
  const ed = state.sumEdit, ta = $("#sumText");
  return !!(ed && ta && ed.cid === state.current && ta.value.trim() !== ed.base.trim());
}
/* close：存完是否離開編輯模式（按「儲存」＝是；離開編輯框自動存＝否） */
let sumSaving = null;
async function saveSummary(close = true, quiet = false) {
  const ed = state.sumEdit, ta = $("#sumText");
  if (!ed || !ta || ed.cid !== state.current) return;
  const text = ta.value, cid = ed.cid;
  if (text.trim() === ed.base.trim()) {
    if (close) { state.sumEdit = null; renderDetail(); }
    return;
  }
  const conflicts0 = ed.conflicts || 0;
  if (sumSaving) await sumSaving;
  // 等候前一次存檔（例如離開編輯框時的自動存）期間若發生衝突，已經提示過：這次不送出，
  // 讓你看過最新內容、再按一次儲存才以你的版本為準，免得不知情就蓋掉別處的修改
  if ((ed.conflicts || 0) !== conflicts0) return;
  if (text.trim() === ed.base.trim()) {                  // 前一次已經存了同樣的內容
    if (close && state.sumEdit === ed) { state.sumEdit = null; renderDetail(); }
    return;
  }
  sumSaving = (async () => {
    try {
      // 跟其他存檔排隊，案件卡版本（mtime）才不會互相打架
      await saveChain;
      const res = await api(`/api/case/${cid}/summary`, { method: "PUT", body: { text, base: ed.base } });
      syncCaseIntoList(res.case);
      ed.base = summaryText(res.card);
      if (close && state.sumEdit === ed) state.sumEdit = null;
      if (state.current === cid) { state.detail = res; renderDetail(); }
      toast(quiet ? "已自動儲存案件摘要" : "已儲存案件摘要");
    } catch (e) {
      if (e.status === 409) {
        ed.conflicts = (ed.conflicts || 0) + 1;
        toast(e.message);
        if (state.current === cid) {                       // 讀最新版當基準，編輯框保留你打的字
          await openCase(cid, true);
          if (state.sumEdit === ed) { ed.base = summaryText(state.detail.card); renderDetail(); }
        }
      } else toast("摘要存檔失敗：" + e.message);
    }
  })();
  await sumSaving; sumSaving = null;
}
/* 關分頁、關視窗時還沒存的摘要：用 keepalive 送出（頁面關掉也會送到） */
window.addEventListener("pagehide", () => {
  if (!summaryDirty()) return;
  const ed = state.sumEdit;
  fetch(`/api/case/${ed.cid}/summary`, { method: "PUT", keepalive: true, headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: $("#sumText").value, base: ed.base }) });
});

/* ---------- 庭期、待辦：就地修改 ---------- */
function editingRow() {
  const e = state.rowEdit;
  if (!e || !state.detail || e.cid !== state.detail.case.id) return null;
  const list = e.kind === "todo" ? state.detail.card.todos : state.detail.card.hearings || [];
  const i = list.findIndex(x => (e.gcal && x.gcal === e.gcal) || (!e.gcal && x.text === e.text && (x.due || x.date) === e.when));
  return i < 0 ? null : { ...e, i };
}
function startRowEdit(kind, i) {
  const list = kind === "todo" ? state.detail.card.todos : state.detail.card.hearings;
  const x = list[i];
  if (!x) return;
  state.rowEdit = { cid: state.detail.case.id, kind, gcal: x.gcal || "", text: x.text, when: x.due || x.date || "" };
  renderDetail();
  const f = $("#eText"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); }
}
function todoEditRow(t, i) {
  const p = subSplit(t.text);
  return `<li class="todo editing" data-i="${i}"><form class="row-edit" data-kind="todo">
    ${subSelect("eSub", p.code)}
    <input type="text" id="eText" value="${esc(p.rest)}" placeholder="待辦內容" required>
    <input type="date" id="eDue" value="${esc(t.due || "")}" title="期限（可空白）">
    <button class="btn primary small" type="submit">儲存</button>
    <button class="btn small" type="button" data-act="ecancel">取消</button></form></li>`;
}
function hearingEditRow(h, i) {
  const p = subSplit(h.text);
  return `<li class="todo hearing editing" data-i="${i}"><form class="row-edit" data-kind="hearing">
    ${subSelect("eSub", p.code)}
    <input type="date" id="eDate" value="${esc(h.date)}" title="日期" required>
    <input type="time" id="eTime" value="${esc(h.time || "")}" title="時間（可空白）">
    <input type="text" id="eText" value="${esc(p.rest)}" placeholder="事由（法庭）">
    <button class="btn primary small" type="submit">儲存</button>
    <button class="btn small" type="button" data-act="ecancel">取消</button></form></li>`;
}
function cancelRowEdit() { state.rowEdit = null; renderDetail(); }
function submitRowEdit(form) {
  const ed = editingRow();
  if (!ed) { cancelRowEdit(); return; }
  const text = withSub("eSub", $("#eText").value.trim());
  const sameItem = x => (ed.gcal && x.gcal === ed.gcal) || (!ed.gcal && x.text === ed.text && (x.due || x.date) === ed.when);
  if (form.dataset.kind === "todo") {
    if (!$("#eText").value.trim()) { toast("待辦內容不能空白"); return; }
    const due = $("#eDue").value;
    state.rowEdit = null;
    saveCard((m, todos) => { const j = todos.findIndex(sameItem); if (j >= 0) Object.assign(todos[j], { text, due }); }, "已修改待辦");
  } else {
    const date = $("#eDate").value, time = $("#eTime").value;
    if (!date) { toast("請填日期"); return; }
    state.rowEdit = null;
    saveCard((m, todos, hs) => { const j = hs.findIndex(sameItem); if (j >= 0) Object.assign(hs[j], { date, time, text }); }, "已修改庭期");
  }
}

function cardPayload(mutate) {
  const card = state.detail.card;
  const meta = { ...card.meta }, todos = card.todos.map(t => ({ ...t }));
  const hearings = (card.hearings || []).map(h => ({ ...h }));
  mutate(meta, todos, hearings);
  return { meta, todos, hearings };
}

/* 存檔一次只送一筆，且在輪到它時才從「最新的」案件狀態組出內容——
   連續兩個操作（例如改了案號就馬上勾待辦）不會互相蓋掉。
   每次都帶上讀到的案件卡版本（mtime）：若 Claude 或 Obsidian 在這段時間改過，
   伺服器回 409，畫面重新載入，不會把對方的修改蓋掉。 */
let saveChain = Promise.resolve();
function saveCard(mutate, msg = "已存入案件卡") {
  const cid = state.detail?.case.id;
  if (!cid) return Promise.resolve();
  saveChain = saveChain.then(() => doSave(cid, mutate, msg));
  return saveChain;
}
async function doSave(cid, mutate, msg) {
  if (state.detail?.case.id !== cid) return false;    // 已切到別件：這個操作不再適用
  try {
    const body = { ...cardPayload(mutate), base_mtime: state.detail.card.mtime || 0 };
    const res = await api(`/api/case/${cid}/card`, { method: "PUT", body });
    syncCaseIntoList(res.case);
    if (state.current !== cid) return;
    state.detail = res;
    renderDetail(); state.sub ? renderFiles() : loadFiles();
    toast(msg);
    if (res.gcal_queued) watchCaseSync(cid);
    return true;
  } catch (e) {
    if (e.status === 409) { toast(e.message); if (state.current === cid) await openCase(cid, true); }
    else toast("存檔失敗：" + e.message);
    return false;
  }
}

/* 存檔後背景同步 Google 日曆；輪詢結果顯示在庭期卡右上角 */
function gcalLine(st, busy) {
  if (!state.meta?.gcal_ready) return `<a class="link" data-act="gcalcfg">Google 日曆未連結</a>`;
  if (busy) return "Google 日曆同步中…";
  if (!st) return `<a class="link" data-act="gcalsync">同步到 Google 日曆</a>`;
  if (st.error) return `<span class="err-text" title="${esc(st.error)}">⚠ 日曆同步失敗</span>・<a class="link" data-act="gcalsync">重試</a>`;
  const n = st.pushed + st.deleted;
  return `Google 日曆已同步 ${fmtTime(st.at).slice(11)}${n ? `（更新 ${n} 筆）` : ""}・<a class="link" data-act="gcalsync">再同步</a>`;
}

async function watchCaseSync(cid) {
  const line = () => state.current === cid && $("#gcalLine");
  if (line()) line().innerHTML = gcalLine(null, true);
  for (let i = 0; i < 200; i++) {
    await new Promise(r => setTimeout(r, 1500));
    let r; try { r = await api(`/api/gcal/case/${cid}`); } catch { return; }
    if (!r.status && !r.busy && i > 20) {               // 沒在忙也沒結果：不再假裝「同步中」
      if (line()) line().innerHTML = gcalLine(state.detail?.gcal);
      return;
    }
    if (r.status) {
      if (state.current === cid && state.detail) { state.detail.gcal = r.status; if (line()) line().innerHTML = gcalLine(r.status); }
      if (r.status.error) toast("Google 日曆同步失敗：" + r.status.error);
      return;
    }
  }
}

/* ---------------- 檔案 ---------------- */
let filesData = null, filesFor = "";       // filesFor：這份清單是哪件案件、哪個子資料夾的
async function loadFiles() {
  const cid = state.current, sub = state.sub;
  let data;
  try { data = await api(`/api/case/${cid}/files?sub=${encodeURIComponent(sub)}`); }
  catch (e) {
    if (state.current !== cid || state.sub !== sub) return;
    filesData = null; filesFor = ""; $("#files").innerHTML = `<div class="files-empty">${esc(e.message)}</div>`; return;
  }
  if (state.current !== cid || state.sub !== sub) return;
  filesData = data; filesFor = cid + "|" + sub;
  renderFiles();
}

function renderFiles() {
  if (!filesData || !$("#files")) return;
  const parts = state.sub ? state.sub.split(/[\\/]/) : [];
  $("#crumbs").innerHTML = `<a data-sub="">${esc(state.detail.case.code)} 資料夾</a>` +
    parts.map((p, i) => `<span class="sep">›</span><a data-sub="${esc(parts.slice(0, i + 1).join("\\"))}">${esc(p)}</a>`).join("");
  const icon = it => it.dir
    ? `<span class="ficon folder"><svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l2 2h8.4A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" fill="currentColor"/></svg></span>`
    : `<span class="ficon ${it.kind}">${esc((it.ext || "?").slice(0, 4))}</span>`;
  $("#files").innerHTML = filesData.items.length ? `<table class="files"><tbody>${filesData.items.map(it => `
    <tr data-rel="${esc(it.rel)}" data-dir="${it.dir ? 1 : ""}">
      <td><div class="fname" data-act="open" title="${it.dir ? "進入資料夾" : "用預設程式開啟"}">${icon(it)}<span>${esc(it.name)}</span></div></td>
      <td class="meta">${it.dir ? "" : fmtSize(it.size)}</td>
      <td class="meta">${fmtTime(it.mtime)}</td>
      <td class="act"><button class="btn ghost small" data-act="reveal" title="在檔案總管中顯示">顯示位置</button></td>
    </tr>`).join("")}</tbody></table>` : `<div class="files-empty">（空資料夾）</div>`;
}

async function openPath(rel) {
  try { await api(`/api/case/${state.current}/open`, { method: "POST", body: { rel } }); toast("已用預設程式開啟：" + rel.split(/[\\/]/).pop()); }
  catch (e) { toast(e.message); }
}

/* ---------------- Claude ---------------- */
const QUICK = [
  ["整理案件摘要", "請瀏覽本案資料夾裡的文件（必要時打開閱讀起訴狀／答辯狀、判決、開庭通知與筆錄等重要文件），整理一份案件摘要：當事人與對造、案號與法院、案件事實、主要爭點、目前程序進度、下一步建議。把摘要寫進案件卡的「## 案件摘要」段，並同步填好案件卡的案號、法院、對造、案件狀態。回覆時簡短說明你看了哪些檔案。"],
  ["更新待辦與期日", "請檢查本案最新的開庭通知、法院函文、對造書狀與筆錄，找出尚未處理的事項、期限與下次庭期，更新案件卡的「## 庭期」與「## 待辦事項」。保留我原有的待辦不要刪除，確定已完成的才打勾。回覆時逐條列出你新增或修改了什麼、依據哪一份文件。"],
  ["卷宗目錄", "請替本案資料夾製作卷宗目錄：依子資料夾分組，書狀依日期排序，每份文件一句話說明內容，標出最近一個月新增的文件。存成 Claude整理 資料夾裡的「今天日期-卷宗目錄.md」。"],
  ["書狀攻防整理", "請依時間序列出我方與對造已提出的書狀，各用二、三句話說明重點，最後指出對造最新主張中我方尚未回應的部分。"],
];

/* 多案模式（目前清單／全部案件）的快捷指令 */
const QUICK_MULTI = [
  ["全案狀態盤點", "請根據案件索引與各案件卡，盤點範圍內的案件，產出一份報告：(1) 進行中案件一覽（代號、當事人、種類、狀態、下次期日、未完成待辦數），依下次期日排序；(2) 未來 30 天的庭期與期限；(3) 已逾期但未完成的待辦；(4) 標為進行中、但超過 60 天沒有任何檔案更動的案件。報告存成「Claude整理（全案）/今天日期-全案盤點.md」，回覆中給我五到十點重點。"],
  ["近 30 天期日", "列出範圍內未來 30 天的庭期與期限（依日期排序，註明案件、事由、法院），並指出哪些看起來在辦、但案件卡沒有記任何庭期或待辦的案件，需要我補資料。"],
  ["補建案件卡", "請找出範圍內「最近 90 天有檔案更動、但還沒有案件卡」的案件，依最近更動排序取前 15 件，逐一快速瀏覽資料夾（看檔名、最新的開庭通知與書狀即可，不必讀完整卷宗），判斷案件狀態、案號、法院、對造與已排定的庭期，替它們建立案件卡。最後用表格回報建了哪些、各自的判斷依據，以及還剩多少件沒處理。"],
  ["找出可結案", "找出範圍內看起來已經結束（例如有判決確定證明、撤回、和解成立、結案文件、法扶結案回報），但案件卡沒標「已結案」或根本沒有案件卡的案件，列出每件的依據檔案。先不要修改任何案件卡，等我確認。"],
];

function quickSet() { return state.scope === "case" ? QUICK : QUICK_MULTI; }

function scopeReady() { return state.scope !== "case" || !!state.current; }

function renderQuick() {
  $("#quick").innerHTML = quickSet().map(([t], i) => `<button data-q="${i}" ${state.running || !scopeReady() ? "disabled" : ""}>${t}</button>`).join("");
}

function scopeInfo() {
  if (state.scope === "all") return { label: "全部案件", n: state.cases.length };
  if (state.scope === "list") {
    const f = state.filter, parts = [];
    if (f.type) parts.push(f.type);
    if (f.status !== "全部") parts.push(f.status);
    if (f.group) parts.push(f.group);
    if (f.q) parts.push("搜尋「" + f.q + "」");
    return { label: "目前清單" + (parts.length ? "（" + parts.join("、") + "）" : ""), n: filtered().length };
  }
  return null;
}

function renderScopeLabel() {
  document.querySelectorAll("#scopeSeg button").forEach(b => b.classList.toggle("on", b.dataset.scope === state.scope));
  const el = $("#claudeCase"), info = scopeInfo();
  if (info) el.innerHTML = `範圍：<b>${esc(info.label)}</b>，共 ${info.n} 件。Claude 會在案件根目錄工作，先讀一份範圍內的案件索引。`;
  else if (state.detail && state.current) el.innerHTML = `範圍：<b>${esc(state.detail.case.code)} ${esc(state.detail.case.client)}</b>（只在這件的資料夾裡工作）`;
  else el.textContent = "範圍：本案——請先從左邊選一件案件";
  $("#askInput").disabled = !scopeReady();
  $("#askBtn").disabled = !!state.running || !scopeReady();
  renderQuick();
}

function setScope(scope) {
  if (scope !== state.scope) setAllowFiles(false);
  if (state.running || state.scope === scope) { renderScopeLabel(); return; }
  state.scope = scope;
  STORE.set("casedesk.scope", scope);
  loadChat();
  renderScopeLabel();
}

/* 「允許整理檔案」：只對這次開著的期間有效；換案件、換範圍、重開程式都會自動關掉 */
function setAllowFiles(on) {
  const cb = $("#allowFiles");
  if (!cb) return;
  cb.checked = !!on;
  $("#claude").classList.toggle("files-on", !!on);
  const warn = $("#filesWarn");
  if (warn) {
    warn.hidden = !on;
    warn.textContent = state.scope === "case"
      ? "⚠ 已允許 Claude 刪除、搬移、改名本案資料夾與 Obsidian 筆記庫裡的檔案（刪除的會先放進「_待刪除」資料夾）"
      : "⚠ 已允許 Claude 刪除、搬移、改名範圍內各案件資料夾與 Obsidian 筆記庫裡的檔案（刪除的會先放進「_待刪除」資料夾）";
  }
}

function chatKey(scope = state.scope, cid = state.current) {
  return "casedesk.chat." + (scope === "case" ? cid : "__" + scope + "__");
}
const liveChats = {};    // chatKey → 正在跑的對話物件（串流還在往裡面寫）

/* 對話紀錄存在伺服器（程式資料夾 data/chats，跟著雲端硬碟同步到其他電腦）；
   瀏覽器 localStorage 只當快取，讓畫面先出來，再用伺服器上較新的版本取代。 */
function persistChat(key, chat) {
  chat.updated = Date.now() / 1000;
  STORE.set(key, chat);
  api("/api/chat/" + encodeURIComponent(key), { method: "PUT", body: chat }).catch(() => { });
}
async function loadChat() {
  if (state.scope === "case" && !state.current) { state.chat = { session_id: null, messages: [] }; renderChat(); return; }
  const key = chatKey();
  if (liveChats[key]) { state.chat = liveChats[key]; renderChat(); return; }
  const cached = STORE.get(key, { session_id: null, messages: [] });
  state.chat = cached; renderChat();
  let remote = null;
  try { remote = await api("/api/chat/" + encodeURIComponent(key)); } catch { return; }
  if (chatKey() !== key || liveChats[key] || state.chat !== cached) return;     // 期間已切換或開始對話
  if ((remote.updated || 0) > (cached.updated || 0) && remote.messages?.length) {
    state.chat = remote; STORE.set(key, remote); renderChat();               // 另一台電腦有較新的
  } else if (cached.messages?.length && !(remote.messages?.length)) {
    persistChat(key, cached);                                               // 舊的本機紀錄：補存到伺服器
  }
}
function saveChat() { if (scopeReady()) persistChat(chatKey(), state.chat); }

/* Claude 回答裡的路徑：本案模式相對於案件資料夾；多案模式相對於根目錄 */
function relPath(p, scope = state.scope) {
  if (!p) return "";
  const baseRaw = scope === "case" ? state.detail?.case.path : state.meta?.root;
  if (!baseRaw) return p;
  const base = baseRaw.replace(/\//g, "\\").toLowerCase();
  const q = String(p).replace(/\//g, "\\");
  return q.toLowerCase().startsWith(base) ? q.slice(base.length).replace(/^\\/, "") || "." : p;
}

async function openChatPath(p) {
  try {
    if (state.scope === "case") return openPath(relPath(p));
    await api("/api/open-root", { method: "POST", body: { rel: relPath(p) } });
    toast("已用預設程式開啟：" + String(p).split(/[\\/]/).pop());
  } catch (e) { toast(e.message); }
}

function toolLine(b) {
  const i = b.input || {};
  const label = { Read: "讀取", Write: "寫入", Edit: "修改", Glob: "搜尋檔名", Grep: "搜尋內容", Bash: "執行", Skill: "使用 skill", WebSearch: "網路搜尋", WebFetch: "讀取網頁", TodoWrite: "規劃步驟" }[b.name] || b.name;
  const arg = i.file_path ? relPath(i.file_path) : i.pattern || i.command || i.skill || i.query || i.url || "";
  return { kind: "tool", label, arg: String(arg).slice(0, 160) };
}

function renderChat() {
  const box = $("#chat");
  const msgs = state.chat?.messages || [];
  if (!msgs.length) {
    box.innerHTML = state.scope === "case"
      ? `<div class="chat-hint muted small">Claude 會以本案資料夾為工作目錄，能直接讀 PDF／Word 卷宗、把整理結果存成新檔、更新案件卡的狀態與待辦。<br>平常不會刪除或改名既有檔案；要請它整理資料夾時，打開下方「模型與進階設定」勾選「允許整理檔案」。可以用下方快捷鈕，或直接打字吩咐。</div>`
      : `<div class="chat-hint muted small">多案模式：Claude 在案件根目錄工作，先讀一份範圍內所有案件的索引（狀態、下次期日、待辦數…），需要時再打開個別案件。適合整體盤點、找出漏掉的期日、批次補建案件卡。<br>報告會存到根目錄的「Claude整理（全案）」資料夾。案件多時會跑比較久，也比較耗額度。</div>`;
    return;
  }
  box.innerHTML = msgs.map(m => {
    if (m.role === "user") return `<div class="msg user">${m.scope || m.files ? `<div class="scope-tag">${esc(m.scope || "")}${m.files ? `${m.scope ? "・" : ""}<span class="files-tag">允許整理檔案</span>` : ""}</div>` : ""}${esc(m.text)}</div>`;
    if (m.role === "error") return `<div class="msg err">${esc(m.text)}</div>`;
    const body = (m.parts || []).map(p => p.kind === "tool"
      ? `<div class="tool"><b>${esc(p.label)}</b><span>${esc(p.arg)}</span></div>`
      : `<div class="md">${md(p.text)}</div>`).join("");
    return `<div class="msg bot ${m.live ? "typing" : ""}">${body || (m.live ? `<span class="muted small">思考中</span>` : "")}${m.foot ? `<div class="foot">${esc(m.foot)}</div>` : ""}</div>`;
  }).join("");
  box.scrollTop = box.scrollHeight;
}

let renderQueued = false;
function queueRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderChat(); });
}

async function ask(prompt) {
  if (!prompt.trim() || state.running || !scopeReady()) return false;
  const scope = state.scope, cid = scope === "case" ? state.current : null;
  const key = chatKey(scope, cid), chat = state.chat;
  const info = scopeInfo();
  const allowFiles = !!$("#allowFiles")?.checked;
  chat.messages.push({ role: "user", text: prompt, scope: info ? `${info.label}・${info.n} 件` : "", ...(allowFiles ? { files: true } : {}) });
  const bot = { role: "bot", parts: [], live: true };
  chat.messages.push(bot);
  renderChat(); persistChat(key, chat);
  liveChats[key] = chat;
  setRunning({ cid, scope });
  const t0 = Date.now();
  let sawDelta = false, gcalQueued = false, changed = [], resultOk = false;
  const textPart = () => {
    const last = bot.parts[bot.parts.length - 1];
    if (last && last.kind === "text") return last;
    const p = { kind: "text", text: "" }; bot.parts.push(p); return p;
  };
  const handle = ev => {
    switch (ev.type) {
      case "run": state.running.run_id = ev.run_id; break;
      case "system": if (ev.subtype === "init" && ev.session_id) chat.session_id = ev.session_id; break;
      case "stream_event": {
        const e = ev.event || {};
        if (e.type === "content_block_delta" && e.delta?.type === "text_delta") { sawDelta = true; textPart().text += e.delta.text; }
        else if (e.type === "message_start" && bot.parts.length && bot.parts[bot.parts.length - 1].kind === "text") bot.parts.push({ kind: "text", text: "" });
        break;
      }
      case "assistant":
        for (const b of ev.message?.content || []) {
          if (b.type === "tool_use") bot.parts.push(toolLine(b));
          else if (b.type === "text" && !sawDelta) textPart().text += b.text;
        }
        break;
      case "result":
        if (ev.session_id) chat.session_id = ev.session_id;
        resultOk = !ev.is_error;
        if (!bot.parts.some(p => p.kind === "text" && p.text.trim()) && ev.result) textPart().text = ev.result;
        bot.foot = `${ev.is_error ? "⚠ 執行有誤・" : ""}${((Date.now() - t0) / 1000).toFixed(0)} 秒${ev.num_turns ? "・" + ev.num_turns + " 步" : ""}`;
        break;
      case "error": chat.messages.push({ role: "error", text: ev.message }); break;
      case "casedesk_done": gcalQueued = !!ev.gcal_queued; changed = ev.changed || []; break;
    }
    if (state.chat === chat) queueRender();
  };
  const sel = { model: $("#modelSel").value, effort: $("#effortSel").value, allow_files: allowFiles };
  try {
    const url = scope === "case" ? `/api/case/${cid}/claude` : "/api/claude/multi";
    const body = scope === "case" ? { prompt, session_id: chat.session_id, chat_key: key, ...sel }
      : { prompt, session_id: chat.session_id, chat_key: key, ...sel, scope, label: info.label,
          case_ids: scope === "list" ? filtered().map(c => c.id) : [] };
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (; ;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
        if (line) { try { handle(JSON.parse(line)); } catch { } }
      }
    }
  } catch (e) {
    chat.messages.push({ role: "error", text: "連線中斷：" + e.message });
  }
  bot.live = false;
  if (!bot.foot) bot.foot = "已停止";
  if (changed.length) bot.foot += `・更新了 ${changed.length} 件案件卡`;
  persistChat(key, chat);
  delete liveChats[key];
  setRunning(null);
  if (state.chat === chat) renderChat();
  if (scope === "case") {
    if (state.current === cid) {
      await openCase(cid, true);   // Claude 可能改了案件卡或新增檔案
      if (gcalQueued) watchCaseSync(cid);
    }
  } else if (changed.length) {
    await loadCases();             // 伺服器已重掃；把新的狀態／待辦數拉回來
    if (state.current && changed.includes(state.current)) openCase(state.current, true);
    toast(`Claude 更新了 ${changed.length} 件案件卡${gcalQueued ? "，已送去同步 Google 日曆" : ""}`);
  }
  return resultOk;
}

function setRunning(r) {
  state.running = r;
  $("#stopBtn").hidden = !r;
  $("#claudeStatus").textContent = r ? "Claude 工作中…（多案模式可能要幾分鐘）" : "";
  document.querySelectorAll("#scopeSeg button").forEach(b => b.disabled = !!r);
  renderScopeLabel();
}

async function saveUi(patch) {
  state.ui = { ...state.ui, ...patch };
  try { state.ui = await api("/api/ui", { method: "PUT", body: state.ui }); } catch (e) { toast("偏好設定存檔失敗：" + e.message); }
}
window.saveUi = saveUi;

/* ---------------- 今日總覽 ---------------- */
const addDaysIso = (s, n) => { const [y, m, d] = s.split("-").map(Number); return iso(new Date(y, m - 1, d + n)); };
const WEEKDAY = "日一二三四五六";
const dayLabel = s => { const [y, m, d] = s.split("-").map(Number); return `${m}/${d}（${WEEKDAY[new Date(y, m - 1, d).getDay()]}）`; };

async function loadToday() {
  const t = today(), end = addDaysIso(t, 8);
  const [y, m, d] = t.split("-").map(Number);
  $("#todayDate").textContent = `${y}/${m}/${d}（${WEEKDAY[new Date(y, m - 1, d).getDay()]}）・民國 ${y - 1911} 年`;
  let cal = [], todos = [], H = null;
  try {
    [cal, todos] = await Promise.all([api(`/api/calendar?start=${t}&end=${end}`), api("/api/todos")]);
  } catch (e) { toast(e.message); return; }
  try { H = await Deadline.loadHolidays(); } catch { }
  const overdue = todos.filter(x => !x.done && x.due && x.due < t);
  const todayItems = cal.filter(x => x.date === t && !x.done);
  const week = cal.filter(x => x.date > t && !x.done);
  const inbox = state.cases.filter(c => c.new_docs).sort((a, b) => b.new_docs - a.new_docs);
  const hearingsToday = todayItems.filter(x => x.kind === "hearing").length;

  const stat = (id, ic, label, n, text, cls = "") => `<button class="priority-item ${n ? cls : "zero"}" data-jump="${id}">
      <div class="priority-label">${icon(ic)}${label}</div><div class="priority-date">${n}</div>
      <div class="priority-text">${text}</div></button>`;
  $("#todayStats").innerHTML =
    stat("tvOverdue", "clock", "已逾期", overdue.length, overdue.length ? "未完成且已過期限的待辦" : "沒有逾期的待辦", "overdue") +
    stat("tvToday", "calendar", "今天", todayItems.length, todayItems.length ? `庭期 ${hearingsToday}・期限 ${todayItems.length - hearingsToday}` : "今天沒有庭期與期限", "soon") +
    stat("tvWeek", "calendar", "未來七天", week.length, week.length ? `庭期 ${week.filter(x => x.kind === "hearing").length}・期限 ${week.filter(x => x.kind !== "hearing").length}` : "接下來一週沒有安排") +
    stat("tvInbox", "inbox", "新收文書", inbox.length, inbox.length ? `共 ${inbox.reduce((s, c) => s + c.new_docs, 0)} 份尚未看過` : "沒有新收文件");

  const caseLink = (id, code, client) => `<a class="tv-case" data-open="${esc(id)}" tabindex="0">${esc(code)} ${esc(client)}</a>`;
  const check = x => x.kind === "hearing" ? "<span></span>"
    : `<input type="checkbox" title="標為完成" data-case="${esc(x.case_id)}" data-gcal="${esc(x.gcal || "")}" data-text="${esc(x.text)}" data-due="${esc(x.due || x.date || "")}">`;
  const row = (x, when, cls = "") => `<li class="tv-row ${x.kind === "hearing" ? "hearing" : ""} ${cls}">
      <span class="tv-when">${esc(when)}</span><span class="tv-kind" title="${x.kind === "hearing" ? "庭期" : "期限"}">${icon(x.kind === "hearing" ? "calendar" : "clock")}</span>
      <span class="tv-main">${caseLink(x.case_id, x.code, x.client)}<span class="tv-text">${esc(x.body ?? x.text)}</span></span>${check(x)}</li>`;
  const restName = s => {
    if (!H) return "";
    if (H.extra && H.extra[s]) return H.extra[s];
    const [yy, mm, dd] = s.split("-").map(Number), wd = new Date(yy, mm - 1, dd).getDay();
    return H.holidays && H.holidays[s] && wd !== 0 && wd !== 6 ? H.holidays[s] : "";
  };

  const todayCard = `<div class="card" id="tvToday"><div class="card-title">今天<span class="right muted small">${esc(dayLabel(t))}</span></div>
    ${todayItems.length ? `<ul class="tv-list">${todayItems.map(x => row(x, x.kind === "hearing" ? (x.time || "整日") : "今天")).join("")}</ul>`
      : `<div class="tv-empty">今天沒有庭期與期限。${restName(t) ? "（" + esc(restName(t)) + "）" : ""}</div>`}</div>`;
  const overdueCard = `<div class="card" id="tvOverdue"><div class="card-title">已逾期<span class="right muted small">${overdue.length} 項</span></div>
    ${overdue.length ? `<ul class="tv-list">${overdue.map(x => row({ ...x, kind: "deadline", date: x.due }, x.due.slice(5).replace("-", "/"), "overdue")).join("")}</ul>`
      : `<div class="tv-empty">沒有逾期的待辦。</div>`}</div>`;
  const byDay = {};
  week.forEach(x => (byDay[x.date] = byDay[x.date] || []).push(x));
  let weekHtml = "";
  for (let i = 1; i <= 7; i++) {
    const s = addDaysIso(t, i), list = byDay[s] || [], hol = restName(s);
    if (!list.length && !hol) continue;
    weekHtml += `<div class="tv-day"><b>${esc(dayLabel(s))}</b>${hol ? `<span class="tv-hol">${esc(hol)}</span>` : ""}</div>`;
    weekHtml += list.length ? `<ul class="tv-list">${list.map(x => row(x, x.kind === "hearing" ? (x.time || "整日") : "期限")).join("")}</ul>` : "";
  }
  const weekCard = `<div class="card wide" id="tvWeek"><div class="card-title">未來七天<span class="right muted small">${esc(dayLabel(addDaysIso(t, 1)))} – ${esc(dayLabel(addDaysIso(t, 7)))}</span></div>
    ${weekHtml || `<div class="tv-empty">接下來一週沒有庭期與期限。</div>`}</div>`;
  const inboxCard = `<div class="card wide" id="tvInbox"><div class="card-title">新收文書<span class="right muted small">上次看過之後新增</span></div>
    ${inbox.length ? `<ul class="tv-list">${inbox.slice(0, 12).map(c => `<li class="tv-row"><span class="tv-when">${c.new_docs} 份</span>
        <span class="tv-kind">${icon("inbox")}</span><span class="tv-main">${caseLink(c.id, c.code, c.client)}<span class="tv-text">${esc(c.cause || "")}</span></span><span></span></li>`).join("")}</ul>
        ${inbox.length > 12 ? `<div class="tv-empty">還有 ${inbox.length - 12} 件，可在案件清單用「新收文書」篩選。</div>` : ""}`
      : `<div class="tv-empty">沒有新收文件。</div>`}</div>`;
  $("#todayGrid").innerHTML = todayCard + overdueCard + weekCard + inboxCard;
}

/* ---------------- 待辦總覽 ---------------- */
async function loadTodos() {
  let rows;
  try { rows = await api("/api/todos"); } catch (e) { toast(e.message); return; }
  const showDone = $("#showDone").checked;
  rows = rows.filter(t => showDone || !t.done);
  $("#todoRows").innerHTML = rows.length ? rows.map(t => `
    <tr class="${t.done ? "done" : ""}">
      <td><input type="checkbox" ${t.done ? "checked" : ""} data-case="${t.case_id}" data-gcal="${esc(t.gcal || "")}" data-text="${esc(t.text)}" data-due="${esc(t.due || "")}"></td>
      <td>${t.due ? `<span class="due ${dueClass(t.due, t.done)}">${esc(t.due)}</span>` : `<span class="muted">—</span>`}</td>
      <td><a data-open="${t.case_id}">${esc(t.code)} ${esc(t.client)}</a></td>
      <td class="txt">${esc(t.text)}</td>
      <td>${pill(t.status)}</td>
    </tr>`).join("") : `<tr><td colspan="5" class="muted" style="padding:20px">目前沒有待辦。在案件頁新增待辦，或請 Claude「更新待辦與期日」。</td></tr>`;
}

function switchView(v) {
  document.querySelectorAll(".tab").forEach(t => {
    const on = t.dataset.view === v;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", String(on));
  });
  setDocTitle(v === "today" ? "今日總覽" : v === "calendar" ? "庭期月曆" : v === "todos" ? "待辦總覽"
    : state.detail ? `${state.detail.case.code} ${state.detail.case.client}` : "");
  $("#viewCases").hidden = v !== "cases";
  $("#viewCalendar").hidden = v !== "calendar";
  $("#viewTodos").hidden = v !== "todos";
  $("#viewToday").hidden = v !== "today";
  if (v === "today") loadToday();
  if (v === "todos") loadTodos();
  if (v === "calendar") loadCalendar();
}

/* ---------------- 庭期月曆 ---------------- */
const WEEK = ["日", "一", "二", "三", "四", "五", "六"];
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const calState = { y: new Date().getFullYear(), m: new Date().getMonth() };

function calItem(it, withDate = false) {
  const cls = it.kind === "hearing" ? "hearing" : it.done ? "deadline done" : "deadline";
  const lead = it.kind === "hearing" ? (it.time || "整日") : (it.done ? "✓" : "⏰");
  const title = `${it.date} ${it.time || ""}\n${it.code} ${it.client}${it.cause ? "｜" + it.cause : ""}\n${it.kind === "hearing" ? "庭期" : "期限"}：${it.text}${it.court ? "\n" + it.court : ""}`;
  return `<div class="ev ${cls}" data-open="${it.case_id}" title="${esc(title)}">
    ${withDate ? "" : `<b>${esc(lead)}</b> `}${esc(it.subject || it.client)}・${esc(it.body ?? it.text)}</div>`;
}

async function loadCalendar() {
  const first = new Date(calState.y, calState.m, 1);
  const start = new Date(first); start.setDate(1 - first.getDay());
  const end = new Date(start); end.setDate(start.getDate() + 42);
  $("#calTitle").textContent = `${calState.y} 年 ${calState.m + 1} 月（民國 ${calState.y - 1911} 年）`;
  let items = [];
  try { items = await api(`/api/calendar?start=${iso(start)}&end=${iso(end)}`); } catch (e) { toast(e.message); }
  const byDay = {};
  items.forEach(it => (byDay[it.date] = byDay[it.date] || []).push(it));
  const t = today();
  let html = WEEK.map((w, i) => `<div class="cal-dow ${i === 0 || i === 6 ? "we" : ""}">${w}</div>`).join("");
  for (let i = 0; i < 42; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    const k = iso(d), list = byDay[k] || [];
    const cls = [d.getMonth() !== calState.m ? "other" : "", k === t ? "today" : "", d.getDay() % 6 === 0 ? "we" : ""].join(" ");
    html += `<div class="cal-day ${cls}"><div class="dnum">${d.getDate()}</div>
      ${list.slice(0, 4).map(it => calItem(it)).join("")}
      ${list.length > 4 ? `<div class="more" title="${esc(list.slice(4).map(x => x.client + " " + x.text).join("\n"))}">還有 ${list.length - 4} 筆</div>` : ""}</div>`;
  }
  $("#calGrid").innerHTML = html;
  loadAgenda();
  refreshSyncAllInfo();
}

async function loadAgenda() {
  const s = new Date(), e = new Date(); e.setDate(s.getDate() + 60);
  let items = [];
  try { items = await api(`/api/calendar?start=${iso(s)}&end=${iso(e)}`); } catch { }
  items = items.filter(x => !x.done);
  if (!items.length) { $("#agenda").innerHTML = `<p class="muted small">沒有排定的庭期或期限。<br>在案件頁的「庭期」新增，或請 Claude「更新待辦與期日」。</p>`; return; }
  const groups = {};
  items.forEach(it => (groups[it.date] = groups[it.date] || []).push(it));
  $("#agenda").innerHTML = Object.entries(groups).map(([d, list]) => {
    const dd = new Date(d + "T00:00"), diff = Math.round((dd - new Date(today() + "T00:00")) / 86400000);
    const rel = diff === 0 ? "今天" : diff === 1 ? "明天" : `${diff} 天後`;
    return `<div class="ag-day"><div class="ag-date ${diff <= 7 ? "soon" : ""}">${d.slice(5).replace("-", "/")}（${WEEK[dd.getDay()]}）<span>${rel}</span></div>
      ${list.map(it => `<div class="ag-item ${it.kind}" data-open="${it.case_id}">
        <span class="ag-time">${it.kind === "hearing" ? esc(it.time || "整日") : "期限"}</span>
        <span><b>${esc(it.subject || it.client)}</b>${it.title_code ? ` <span class="muted small">${esc(it.title_code)}</span>` : ""}<br>${esc(it.body ?? it.text)}${it.court ? `<br><span class="muted small">${esc(it.court)}</span>` : ""}</span></div>`).join("")}</div>`;
  }).join("");
}

async function refreshSyncAllInfo() {
  let st; try { st = await api("/api/gcal/status"); } catch { return; }
  $("#syncAll").disabled = !st.connected || !st.enabled || !!st.busy;
  const la = st.last_all;
  $("#syncAllInfo").textContent = st.busy ? st.busy + "…"
    : !st.connected ? "Google 日曆未連結"
      : la ? (la.errors?.length ? "⚠ " + la.errors[0] : `上次全部同步 ${fmtTime(la.at).slice(5)}：${la.cases} 案，更新 ${la.pushed}、刪除 ${la.deleted}`) : "";
  return st;
}

async function syncAll() {
  try { await api("/api/gcal/sync", { method: "POST" }); } catch (e) { toast(e.message); return; }
  for (let i = 0; i < 120; i++) {
    const st = await refreshSyncAllInfo();
    if (st && !st.busy && st.last_all) { toast("全部同步完成"); return; }
    await new Promise(r => setTimeout(r, 1500));
  }
}

/* ---------------- 上方工具列自動縮減 ---------------- */
// 依序：藏根目錄路徑 → 縮小間距 → 按鈕改短字 → 藏品牌文字 → 把按鈕一個個收進「⋯」選單
const TB_STEPS = ["tb-noroot", "tb-tight", "tb-short", "tb-nobrand"];
const TB_MOVABLE = ["rescan", "gcalChip", "themeBtn", "toggleSide", "toggleClaude"];   // 先收不常用的
const TB_TOGGLES = { toggleSide: "Ctrl+B", toggleClaude: "" };
let tbRaf = 0;

function topbarFits() {
  const bar = $(".topbar"), br = bar.getBoundingClientRect();
  const pad = parseFloat(getComputedStyle(bar).paddingRight) || 0;
  if ($("#moreBtn").getBoundingClientRect().right > br.right - pad + 0.5) return false;
  const ri = $("#rootInfo");     // 路徑被擠到剩一小截就乾脆不顯示
  return !ri.textContent || !ri.offsetParent || ri.clientWidth >= Math.min(ri.scrollWidth, 160);
}

function fitTopbar() {
  const bar = $(".topbar");
  if (!bar || !bar.offsetWidth) return;
  bar.classList.remove(...TB_STEPS);
  for (const id of TB_MOVABLE) $("#" + id).classList.remove("tb-moved");
  for (let i = 0; i < TB_STEPS.length && !topbarFits(); i++) bar.classList.add(TB_STEPS[i]);
  for (const id of TB_MOVABLE) { if (topbarFits()) break; $("#" + id).classList.add("tb-moved"); }
  $("#moreBtn").classList.toggle("has-more", TB_MOVABLE.some(id => $("#" + id).classList.contains("tb-moved")));
  $("#moreBtn").classList.toggle("has-warn", $("#gcalChip").classList.contains("tb-moved") && $("#gcalChip").classList.contains("warn"));
}

function scheduleFitTopbar() { cancelAnimationFrame(tbRaf); tbRaf = requestAnimationFrame(fitTopbar); }

function renderMoreOverflow() {
  const moved = TB_MOVABLE.filter(id => $("#" + id).classList.contains("tb-moved"));
  $("#moreOverflow").innerHTML = moved.map(id => {
    const b = $("#" + id), label = (b.querySelector(".full") || b).textContent.trim();
    if (id in TB_TOGGLES) {
      const on = b.classList.contains("on");
      return `<button data-proxy="${id}">${on ? "✓ " : "　 "}${label}<span class="kbd">${TB_TOGGLES[id]}</span></button>`;
    }
    const warn = id === "gcalChip" && b.classList.contains("warn") ? '<span class="kbd warn-mark">⚠ 同步有問題</span>' : "";
    return `<button data-proxy="${id}" title="${esc(b.title)}">${label}${id === "gcalChip" ? "…" : ""}${warn}</button>`;
  }).join("") + (moved.length ? '<div class="ctx-sep"></div>' : "");
}

/* ---------------- Google 日曆設定 ---------------- */
async function updateGcalChip() {
  let st; try { st = await api("/api/gcal/status"); } catch { return; }
  const chip = $("#gcalChip");
  chip.classList.toggle("on", st.connected && st.enabled);
  chip.classList.toggle("warn", !!st.error);
  scheduleFitTopbar();
  chip.title = st.error || (st.connected ? (st.enabled ? "已連結，同步中" : "已連結，但同步未啟用") : "尚未連結 Google 日曆");
  const ready = st.connected && st.enabled;
  if (state.meta && state.meta.gcal_ready !== ready) {
    state.meta.gcal_ready = ready;
    if (state.detail && $("#gcalLine")) $("#gcalLine").innerHTML = gcalLine(state.detail.gcal);
  }
}

async function openGcalDlg() {
  $("#gcalDlg").showModal();
  renderGcalDlg();
}

async function renderGcalDlg() {
  $("#gcalBody").innerHTML = `<p class="muted">讀取中…</p>`; $("#gcalErr").textContent = "";
  let st; try { st = await api("/api/gcal/status?deep=1"); } catch (e) { $("#gcalErr").textContent = e.message; return; }
  const cals = (st.calendars || []).filter(c => c.writable);
  const opt = sel => cals.map(c => `<option value="${esc(c.id)}" ${c.id === sel ? "selected" : ""}>${esc(c.name)}${c.primary ? "（主要）" : ""}</option>`).join("");
  $("#gcalErr").textContent = st.error || "";
  $("#gcalSave").hidden = !st.connected;
  $("#gcalBody").innerHTML = !st.connected ? `
    <div class="gc-box">
      <p>${st.auth_running ? "已在瀏覽器開啟 Google 授權頁，請在那邊完成登入與同意…" : "尚未連結。按下面的按鈕，瀏覽器會開 Google 的授權頁，由你本人登入並同意。"}</p>
      <p class="muted small">會看到「Google 尚未驗證這個應用程式」：點「進階」→「前往（不安全）」即可，這是你自己在 Google Cloud 建的用戶端。</p>
      <button type="button" class="btn primary" id="gcalAuth" ${st.auth_running || !st.credentials_file ? "disabled" : ""}>${st.auth_running ? "等待授權中…" : "連結 Google 日曆"}</button>
    </div>` : `
    <div class="dlg-grid">
      <label>狀態</label><div><span class="ok-text">● 已連結</span>　<button type="button" class="btn ghost small" id="gcalDisconnect">中斷連結</button></div>
      <label for="gcHear">庭期寫入</label><select id="gcHear">${opt(st.calendar_hearing)}</select>
      <label for="gcDead">期限寫入</label><select id="gcDead">${opt(st.calendar_deadline)}</select>
      <label>同步</label><div class="checks">
        <label><input type="checkbox" id="gcEnabled" ${st.enabled ? "checked" : ""}> 啟用同步</label>
        <label><input type="checkbox" id="gcAuto" ${st.auto_sync ? "checked" : ""}> 存檔／Claude 改完後自動同步該案</label>
      </div>
    </div>
    <p class="muted small">事件標題：⚖ 庭期、⏰ 期限、✓ 已完成的期限。庭期提醒前一天與兩小時前；期限提醒三天前與前一天上午九點。</p>`;
  if (st.auth_running) setTimeout(() => $("#gcalDlg").open && renderGcalDlg(), 2000);
}

/* ---------------- 可用工具（skill／連接器） ---------------- */
let caps = null;
const SERVER_LABEL = n => String(n || "").replace(/^claude\.ai\s*/, "");

async function loadCaps(refresh = false) {
  try { caps = await api("/api/claude/capabilities" + (refresh ? "/refresh" : ""), refresh ? { method: "POST" } : {}); }
  catch (e) { caps = { error: e.message }; }
  const dot = $("#toolsDot");
  dot.className = "dot " + (!caps.at ? "" : caps.ok ? "ok" : "bad");
  $("#toolsBtn").title = !caps.at ? "尚未檢查" : caps.ok ? "Claude 可正常使用" : "Claude 目前無法使用：" + (caps.error || "");
  return caps;
}

function renderTools(filter = "") {
  const c = caps || {};
  if (!c.at) { $("#toolsBody").innerHTML = `<p class="muted">還沒檢查過。按左下「重新檢查」。</p>`; return; }
  const servers = (c.mcp_servers || []).filter(s => !/chatcut/i.test(s.name));
  // 與後端 mcp_server_key 相同：「.」與空白變底線，其他非英數字元（例如中文）拿掉
  const keyOf = name => {
    name = String(name || "");
    let k = name.replace(/[^A-Za-z0-9_-]/g, "_");
    if (name.startsWith("claude.ai ")) k = k.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
    return k;
  };
  const toolsOf = (list, name) => (list || []).filter(t => t.split("__")[1] === keyOf(name)).length;
  const kindOf = name => (c.server_kinds || {})[name] || "";
  const f = filter.trim().toLowerCase();
  const skills = (c.skills || []).filter(s => !/^chatcut-|^cowork-|^(design|design-sync|verify|debug|code-review|simplify|batch|fewer-permission-prompts|doctor|loop|schedule|claude-api|workflow-authoring|run|run-skill-generator|plugin-authoring|update-config)$/.test(s))
    .filter(s => !f || s.toLowerCase().includes(f));
  $("#toolsBody").innerHTML = `
    <div class="tl-status ${c.ok ? "ok" : "bad"}">${c.ok ? "● Claude 可正常使用" : "● Claude 目前無法使用"}
      <span class="muted small">檢查於 ${fmtTime(c.at)}</span></div>
    ${c.ok ? "" : `<pre class="tl-err">${esc(c.error || "")}</pre>`}
    <h3>連接器</h3>
    <table class="tl-table"><tbody>${servers.map(s => {
      const ok = toolsOf(c.allowed_mcp, s.name), no = toolsOf(c.blocked_mcp, s.name);
      return `<tr><td>${esc(SERVER_LABEL(s.name))}</td>
        <td><span class="${s.status === "failed" ? "err-text" : "ok-text"}">${s.status === "connected" ? "已連線" : s.status === "pending" ? "連線較慢（使用時才載入）" : esc(s.status)}</span></td>
        <td class="muted small">${kindOf(s.name) === "readonly" ? "全部開放（唯讀查詢）"
          : kindOf(s.name) === "unknown" ? `未列管：只開放查詢類 ${ok} 項${no ? `・封鎖 ${no} 項` : ""}`
          : `開放 ${ok} 項${no ? `・封鎖 ${no} 項` : ""}`}</td></tr>`;
    }).join("") || `<tr><td class="muted">沒有偵測到任何連接器</td></tr>`}</tbody></table>
    <p class="muted small">Gmail 只能讀信與建草稿（不能寄出）；Google 日曆、雲端硬碟只能讀；Claude Docs 不能刪除。
      刪除、搬移、改名檔案的指令一律禁止。Obsidian 筆記庫可讀不可改。</p>
    <h3>Skill <span class="muted small">（${skills.length} 個，點一下插入輸入框）</span></h3>
    <input id="tlFilter" class="tl-filter" placeholder="搜尋 skill…" value="${esc(filter)}">
    <div class="tl-skills">${skills.map(s => `<button type="button" data-skill="${esc(s)}">${esc(s.replace(/^anthropic-skills:/, ""))}</button>`).join("")}</div>`;
}

/* ---------------- 開新案 ---------------- */
let ncOpts = null;
async function openNewCase() {
  $("#ncErr").textContent = "";
  try { ncOpts = await api("/api/newcase/options"); } catch (e) { toast(e.message); return; }
  $("#ncGroup").innerHTML = ncOpts.groups.map((g, i) => `<option value="${i}">${esc(g.label)}${g.count ? `（${g.count}）` : ""}</option>`).join("");
  $("#ncTpl").innerHTML = `<option value="">（不用範本，建空資料夾）</option>` + ncOpts.templates.map(t => `<option>${esc(t)}</option>`).join("");
  $("#ncStatus").innerHTML = ncOpts.statuses.map(s => `<option ${s === "進行中" ? "selected" : ""}>${esc(s)}</option>`).join("");
  $("#ncRetained").value = today();
  ["#ncClient", "#ncCause", "#ncOpponent"].forEach(s => $(s).value = "");
  $("#ncConflict").innerHTML = ""; ncConflictRed = 0;
  const cur = state.cases.find(c => c.id === state.current);
  const gi = Math.max(0, ncOpts.groups.findIndex(g => g.label === (state.filter.group || cur?.group)));
  $("#ncGroup").value = String(gi);
  ncGroupChanged();
  $("#newCaseDlg").showModal();
  $("#ncClient").focus();
}

function ncGroupChanged() {
  const g = ncOpts.groups[+$("#ncGroup").value];
  $("#ncCode").value = g.suggest || "";
  $("#ncTpl").value = g.template || "";
  ncPreview();
}

function ncPreview() {
  const g = ncOpts.groups[+$("#ncGroup").value];
  const name = [$("#ncCode").value.trim().toUpperCase(), $("#ncClient").value.trim(), $("#ncCause").value.trim()].filter(Boolean).join("-");
  $("#ncPreview").innerHTML = `將建立：<code>${esc((g.dir ? g.dir + "\\" : "") + (name || "…"))}</code>`;
}

async function createCase() {
  const g = ncOpts.groups[+$("#ncGroup").value];
  if (ncConflictRed && !confirm(`利益衝突檢查找到 ${ncConflictRed} 筆可能衝突（紅色警示）。確定仍要建立這件案件？`)) return;
  $("#ncErr").textContent = ""; $("#ncCreate").disabled = true;
  try {
    const r = await api("/api/newcase", {
      method: "POST", body: {
        group_dir: g.dir, template: $("#ncTpl").value, code: $("#ncCode").value, client: $("#ncClient").value,
        cause: $("#ncCause").value, status: $("#ncStatus").value, retained: $("#ncRetained").value,
        opponent: $("#ncOpponent").value,
      },
    });
    $("#newCaseDlg").close();
    state.filter = { q: "", status: "使用中", group: "" }; $("#search").value = "";
    await loadCases(true);
    switchView("cases");
    openCase(r.id);
    toast("已建立 " + r.name);
  } catch (e) { $("#ncErr").textContent = e.message; }
  finally { $("#ncCreate").disabled = false; }
}

/* ---------------- 事件 ---------------- */
function bind() {
  document.querySelectorAll(".tab").forEach(t => t.onclick = () => switchView(t.dataset.view));
  $("#search").oninput = e => { state.filter.q = e.target.value; renderList(); };
  $("#statusFilter").onclick = e => { const b = e.target.closest(".chip"); if (b) { state.filter.status = b.dataset.s; renderList(); } };
  $("#groupFilter").onchange = e => { state.filter.group = e.target.value; renderList(); };
  $("#typeFilter").onclick = e => { const b = e.target.closest(".chip"); if (b) { state.filter.type = b.dataset.t; renderList(); } };
  $("#sortSel").onchange = e => { state.sort = e.target.value; STORE.set("casedesk.sort", state.sort); renderList(); };
  $("#caseList").onclick = e => {
    const li = e.target.closest(".case-item");
    if (!li) return;
    if (e.ctrlKey || e.metaKey) openInNewTab({ case: li.dataset.id }, false);    // Ctrl＋點：背景新分頁
    else openCase(li.dataset.id);
  };
  $("#caseList").addEventListener("auxclick", e => {                             // 中鍵：背景新分頁
    const li = e.target.closest(".case-item");
    if (li && e.button === 1) { e.preventDefault(); openInNewTab({ case: li.dataset.id }, false); }
  });
  $("#caseList").addEventListener("mousedown", e => { if (e.button === 1) e.preventDefault(); });   // 不要出現自動捲動

  // 右鍵選單
  $("#caseList").addEventListener("contextmenu", e => {
    const li = e.target.closest(".case-item");
    if (!li) return;
    e.preventDefault();
    const c = state.cases.find(x => x.id === li.dataset.id);
    if (c) showCtx(e.clientX, e.clientY, c);
  });
  $("#ctxMenu").addEventListener("click", e => {
    const b = e.target.closest("button[data-cmd]");
    if (!b) return;
    const id = $("#ctxMenu").dataset.id;
    hideCtx();
    ctxCommand(b.dataset.cmd, id, b.dataset.v);
  });
  document.addEventListener("mousedown", e => { if (!e.target.closest("#ctxMenu")) hideCtx(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") hideCtx(); });
  window.addEventListener("blur", hideCtx);
  $("#caseList").addEventListener("scroll", hideCtx);

  // Claude 範圍、模型、思考強度
  $("#scopeSeg").onclick = e => { const b = e.target.closest("button[data-scope]"); if (b) setScope(b.dataset.scope); };
  $("#allowFiles").onchange = e => {
    if (e.target.checked && !confirm("允許 Claude 刪除、搬移、改名檔案？\n\n" +
        "・只限" + (state.scope === "case" ? "本案資料夾" : "範圍內的案件資料夾") + "與 Obsidian 筆記庫，Claude 會先列出整理計畫，等你同意才動手\n" +
        "・要刪的檔案會先搬進「_待刪除」資料夾，由你自己確認後再清掉\n" +
        "・換案件、換範圍或重開程式會自動關閉")) { e.target.checked = false; return; }
    setAllowFiles(e.target.checked);
  };
  $("#modelSel").onchange = $("#effortSel").onchange = () =>
    saveUi({ claude: { model: $("#modelSel").value, effort: $("#effortSel").value } });

  // 左欄整欄收折：收起後只剩一條細邊，案件內容（進度、卷宗、摘要）佔滿畫面
  const setSideHidden = on => {
    $("#viewCases").classList.toggle("no-side", on);
    $("#toggleSide").classList.toggle("on", !on);
    STORE.set("casedesk.sideHidden", on);
  };
  $("#toggleSide").onclick = () => setSideHidden(!$("#viewCases").classList.contains("no-side"));
  $("#sideCollapse").onclick = () => setSideHidden(true);
  $("#sideRail").onclick = () => setSideHidden(false);
  setSideHidden(STORE.get("casedesk.sideHidden", false));
  document.addEventListener("keydown", e => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "b") {
      e.preventDefault(); setSideHidden(!$("#viewCases").classList.contains("no-side"));
    }
  });

  // 左欄：篩選區收折、欄寬拖曳
  $("#filterToggle").onclick = () => setFilterCollapsed(!$(".sidebar").classList.contains("filters-collapsed"));
  setFilterCollapsed(STORE.get("casedesk.filtersCollapsed", true));
  makeResizable($("#sideResizer"), "--side-w", "casedesk.sideWidth", { min: 200, max: 640, def: 272 });
  makeResizable($("#claudeResizer"), "--claude-w", "casedesk.claudeWidth", { min: 300, max: 900, def: 340, fromRight: true });

  // 分頁／視窗快捷鍵（在系統畫面裡按也有效）
  document.addEventListener("keydown", e => {
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "t") { e.preventDefault(); openInNewTab(); }
    else if (k === "n") { e.preventDefault(); openInNewWindow(); }
    else if (k === "w" && EMBEDDED) { e.preventDefault(); toShell({ type: "closeTab" }); }
    else if (k === "tab" && EMBEDDED) { e.preventDefault(); toShell({ type: "cycleTab", dir: e.shiftKey ? -1 : 1 }); }
    else if (/^[1-9]$/.test(k) && EMBEDDED) { e.preventDefault(); toShell({ type: "gotoTab", index: +k - 1 }); }
  });
  $("#moreBtn").onclick = e => {
    e.stopPropagation();
    const m = $("#moreMenu"), r = e.currentTarget.getBoundingClientRect();
    m.hidden = !m.hidden;
    if (!m.hidden) {
      renderMoreOverflow();
      m.style.top = (r.bottom + 4) + "px"; m.style.left = Math.max(8, r.right - m.offsetWidth) + "px";
    }
  };
  $("#moreMenu").onclick = e => {
    const p = e.target.closest("[data-proxy]");
    if (p) { $("#moreMenu").hidden = true; $("#" + p.dataset.proxy).click(); return; }
    const b = e.target.closest("[data-more]");
    if (!b) return;
    $("#moreMenu").hidden = true;
    const params = state.current && !$("#viewCases").hidden ? { case: state.current } : {};
    if (b.dataset.more === "tab") openInNewTab();
    else if (b.dataset.more === "window") openInNewWindow();
    else if (b.dataset.more === "browser") api("/api/open-browser", { method: "POST", body: { params } }).catch(er => toast(er.message));
    else if (b.dataset.more === "about") $("#aboutDlg").showModal();
    else if (b.dataset.more === "deadline") Deadline.open();
    else if (b.dataset.more === "conflict") openConflictDlg();
  };
  document.addEventListener("mousedown", e => { if (!e.target.closest("#moreMenu, #moreBtn")) $("#moreMenu").hidden = true; });

  // 關於
  $("#brandBtn").onclick = () => $("#aboutDlg").showModal();

  // 可用工具
  $("#toolsBtn").onclick = async () => { $("#toolsDlg").showModal(); renderTools(); };
  $("#toolsRefresh").onclick = async () => {
    $("#toolsRefresh").disabled = true; $("#toolsBody").innerHTML = `<p class="muted">檢查中…（實際啟動一次 Claude，約十幾秒）</p>`;
    await loadCaps(true); $("#toolsRefresh").disabled = false; renderTools();
  };
  $("#toolsBody").addEventListener("input", e => {
    if (e.target.id !== "tlFilter") return;
    const pos = e.target.selectionStart; renderTools(e.target.value);
    const f = $("#tlFilter"); f.focus(); f.setSelectionRange(pos, pos);
  });
  $("#toolsBody").addEventListener("click", e => {
    const b = e.target.closest("[data-skill]");
    if (!b) return;
    const box = $("#askInput");
    if (box.disabled) { toast("請先選一件案件，或把範圍切到「目前清單／全部案件」"); return; }
    box.value = "/" + b.dataset.skill + " " + box.value;
    $("#toolsDlg").close(); box.focus();
  });

  // 外觀
  $("#themeBtn").onclick = () => Theme.open();
  Theme.bind();
  $("#rescan").onclick = async () => { await loadCases(true); toast("已重新掃描"); };
  $("#toggleClaude").onclick = () => {
    const off = $("#viewCases").classList.toggle("no-claude");
    $("#toggleClaude").classList.toggle("on", !off);
    STORE.set("casedesk.claudeHidden", off);
  };
  $("#closeClaude").onclick = () => $("#toggleClaude").click();
  if (STORE.get("casedesk.claudeHidden", true)) $("#viewCases").classList.add("no-claude");
  $("#toggleClaude").classList.toggle("on", !$("#viewCases").classList.contains("no-claude"));

  // 上方工具列：放大畫面或視窗變窄時逐步縮減，放不下的按鈕收進「⋯」
  const bar = $(".topbar"), tbObserver = new ResizeObserver(scheduleFitTopbar);
  for (const el of [bar, $(".brand"), $(".tabs"), ...$(".topbar-right").children]) tbObserver.observe(el);
  window.addEventListener("resize", scheduleFitTopbar);
  fitTopbar();

  document.addEventListener("keydown", e => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && !$("#viewCases").hidden) {
      e.preventDefault();
      if ($("#viewCases").classList.contains("no-side")) $("#sideRail").click();
      $("#search").focus();
    }
  });

  const detail = $("#detail");
  detail.addEventListener("change", e => {
    const t = e.target;
    if (t.id === "statusSel") { const value = t.value; saveCard(m => { m["案件狀態"] = value; }, "狀態已更新"); }
    else if (t.dataset.field) {
      const field = t.dataset.field, value = t.value.trim();
      delete t.dataset.dirty; saveCard(m => { m[field] = value; });
    }
    else if (t.dataset.act === "toggle") {
      const i = +t.closest(".todo").dataset.i;
      saveCard((m, todos) => { todos[i].done = t.checked; }, t.checked ? "已完成" : "已取消完成");
    }
  });
  detail.addEventListener("focusout", e => {
    const t = e.target;
    if (!t.dataset?.field || t.dataset.dirty !== "1") return;
    delete t.dataset.dirty;
    const saved = (state.detail?.card.meta || {})[t.dataset.field] || "";
    const field = t.dataset.field, value = t.value.trim();
    if (value !== saved) saveCard(m => { m[field] = value; });
  });
  detail.addEventListener("click", e => {
    const t = e.target.closest("button") || e.target;
    const tab = t.closest("[data-detail-tab]");
    if (tab) return setDetailTab(tab.dataset.detailTab, true);
    const act = t.closest("[data-act]")?.dataset.act;
    if (t.id === "revealCase") return api(`/api/case/${state.current}/reveal`, { method: "POST", body: { rel: "" } }).catch(er => toast(er.message));
    if (t.id === "refreshFiles") return loadFiles();
    if (t.id === "pinCase") {
      const c = state.detail.case;
      return patchMeta(c.id, { "釘選": c.pinned ? "" : "是" }, c.pinned ? "已取消釘選" : "已釘選");
    }
    if (t.id === "openCard") return openPath(state.meta.card_name);
    const crumb = t.closest("#crumbs a");
    if (crumb) { state.sub = crumb.dataset.sub; return loadFiles(); }
    if (act === "gcalcfg") return openGcalDlg();
    if (act === "gcalsync") {
      return api(`/api/gcal/sync?case_id=${state.current}`, { method: "POST" })
        .then(() => watchCaseSync(state.current)).catch(er => toast(er.message));
    }
    if (act === "hedit" && t.closest("button.edit")) return startRowEdit("hearing", +t.closest(".todo").dataset.i);
    if (act === "edit" && t.closest("button.edit")) return startRowEdit("todo", +t.closest(".todo").dataset.i);
    if (act === "ecancel") return cancelRowEdit();
    if (t.id === "sumEdit") return startSummaryEdit();
    if (t.id === "openDeadline") return Deadline.open();
    if (t.id === "inboxClaude") return inboxToClaude();
    if (t.id === "inboxAck") return inboxAck(null);
    if (t.id === "inboxMore") { state.inboxOpen = state.inboxOpen === state.current ? null : state.current; return renderDetail(); }
    if (act === "iback") return inboxAck([t.closest("[data-rel]").dataset.rel]);
    if (act === "ibopen") return openPath(t.closest("[data-rel]").dataset.rel);
    if (t.id === "sumSave") return saveSummary(true);
    if (t.id === "sumCancel") {
      if (summaryDirty() && !confirm("放棄還沒儲存的摘要修改？")) return;
      state.sumEdit = null; return renderDetail();
    }
    if (act === "hdel") {
      const i = +t.closest(".todo").dataset.i, h = state.detail.card.hearings[i];
      if (confirm(`刪除這筆庭期？\n${h.date} ${h.time} ${h.text}\n（已同步的話，Google 日曆上的事件也會一併刪除）`))
        saveCard((m, todos, hs) => { hs.splice(i, 1); }, "已刪除庭期");
      return;
    }
    if (act === "del") {
      const i = +t.closest(".todo").dataset.i;
      if (confirm("刪除這條待辦？\n" + state.detail.card.todos[i].text)) saveCard((m, todos) => { todos.splice(i, 1); }, "已刪除");
      return;
    }
    const row = t.closest("tr[data-rel]");
    if (row && act === "open") {
      if (row.dataset.dir) { state.sub = row.dataset.rel; loadFiles(); } else openPath(row.dataset.rel);
    } else if (row && act === "reveal") {
      api(`/api/case/${state.current}/reveal`, { method: "POST", body: { rel: row.dataset.rel } }).catch(er => toast(er.message));
    }
  });
  // 雙擊：待辦／庭期文字 → 就地修改；摘要內容 → 編輯摘要（點在子案標籤上也算）
  detail.addEventListener("dblclick", e => {
    const el = e.target.closest("[data-act]");
    if (!el || e.target.closest("button, input, select, textarea")) return;
    if (el.dataset.act === "hedit") startRowEdit("hearing", +el.closest(".todo").dataset.i);
    else if (el.dataset.act === "edit") startRowEdit("todo", +el.closest(".todo").dataset.i);
    else if (el.dataset.act === "sumedit") { window.getSelection()?.removeAllRanges(); startSummaryEdit(); }
  });
  detail.addEventListener("keydown", e => {
    const tab = e.target.closest("[data-detail-tab]");
    if (tab && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const tabs = [...detail.querySelectorAll("[data-detail-tab]")], i = tabs.indexOf(tab);
      const next = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      setDetailTab(tabs[next].dataset.detailTab, true); tabs[next].focus();
      return;
    }
    if (e.key === "Escape" && e.target.closest(".row-edit")) { e.preventDefault(); cancelRowEdit(); }
    if (e.target.id === "sumText") {
      if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === "s" || e.key === "Enter")) { e.preventDefault(); saveSummary(true); }
      else if (e.key === "Escape") { e.preventDefault(); $("#sumCancel").click(); }
    }
  });
  detail.addEventListener("input", e => {
    if (e.target.dataset.field) e.target.dataset.dirty = "1";
    if (e.target.id === "sumText") fitTextarea(e.target);
  });
  // 離開摘要編輯框（點到別處、切換案件）就自動存，但留在編輯模式
  detail.addEventListener("focusout", e => {
    if (e.target.id !== "sumText") return;
    const to = e.relatedTarget;
    if (to && (to.id === "sumCancel" || to.id === "sumSave")) return;
    if (summaryDirty()) saveSummary(false, true);
  });
  detail.addEventListener("submit", e => {
    if (e.target.classList.contains("row-edit")) { e.preventDefault(); submitRowEdit(e.target); return; }
    if (e.target.id === "hearingAdd") {
      e.preventDefault();
      const date = $("#hDate").value, time = $("#hTime").value, text = withSub("hSub", $("#hText").value.trim());
      if (!date) return;
      const typed = ["#hDate", "#hTime", "#hText"].map(s => [s, $(s).value]);
      typed.forEach(([s]) => $(s).value = "");                    // 已送出：重畫時不要再放回來
      saveCard((m, todos, hs) => { hs.push({ date, time, text, gcal: "" }); }, "已新增庭期")
        .then(ok => { if (!ok) typed.forEach(([s, v]) => { if ($(s)) $(s).value = v; }); });
      return;
    }
    if (e.target.id !== "todoAdd") return;
    e.preventDefault();
    if (!$("#todoText").value.trim()) return;
    const text = withSub("tSub", $("#todoText").value.trim()), due = $("#todoDue").value;
    const typed = [["#todoText", $("#todoText").value], ["#todoDue", $("#todoDue").value]];
    typed.forEach(([s]) => $(s).value = "");                      // 已送出：重畫時不要再放回來
    saveCard((m, todos) => { todos.push({ done: false, due, text }); }, "已新增待辦")
      .then(ok => { if (!ok) typed.forEach(([s, v]) => { if ($(s)) $(s).value = v; }); });
  });

  $("#askForm").onsubmit = e => { e.preventDefault(); const v = $("#askInput").value; $("#askInput").value = ""; ask(v); };
  $("#askInput").addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("#askForm").requestSubmit(); } });
  $("#quick").onclick = e => { const b = e.target.closest("button[data-q]"); if (b) ask(quickSet()[+b.dataset.q][1]); };
  $("#stopBtn").onclick = () => { if (state.running?.run_id) api(`/api/claude/stop/${state.running.run_id}`, { method: "POST" }); };
  $("#newChat").onclick = () => {
    if (!scopeReady() || state.running) return;
    state.chat = { session_id: null, messages: [] }; saveChat(); renderChat();
  };
  $("#chat").addEventListener("click", e => {
    const c = e.target.closest("code.path");
    if (c && scopeReady()) openChatPath(c.dataset.path);
  });

  // 庭期月曆
  $("#calPrev").onclick = () => { calState.m--; if (calState.m < 0) { calState.m = 11; calState.y--; } loadCalendar(); };
  $("#calNext").onclick = () => { calState.m++; if (calState.m > 11) { calState.m = 0; calState.y++; } loadCalendar(); };
  $("#calToday").onclick = () => { const n = new Date(); calState.y = n.getFullYear(); calState.m = n.getMonth(); loadCalendar(); };
  $("#syncAll").onclick = syncAll;
  $("#viewCalendar").addEventListener("click", e => {
    const el = e.target.closest("[data-open]");
    if (el) { switchView("cases"); openCase(el.dataset.open); }
  });

  // Google 日曆設定
  $("#gcalChip").onclick = openGcalDlg;
  $("#gcalDlg").addEventListener("close", updateGcalChip);
  $("#gcalBody").addEventListener("click", async e => {
    if (e.target.id === "gcalAuth") {
      try { await api("/api/gcal/auth", { method: "POST" }); } catch (er) { $("#gcalErr").textContent = er.message; }
      setTimeout(renderGcalDlg, 600);
    } else if (e.target.id === "gcalDisconnect") {
      if (!confirm("中斷與 Google 日曆的連結？\n（日曆上已建立的事件不會被刪除）")) return;
      await api("/api/gcal/disconnect", { method: "POST" }); renderGcalDlg();
    }
  });
  $("#gcalForm").addEventListener("submit", async e => {
    if (e.submitter?.value !== "default") return;
    e.preventDefault();
    try {
      await api("/api/gcal/config", {
        method: "PUT", body: {
          calendar_hearing: $("#gcHear").value, calendar_deadline: $("#gcDead").value,
          enabled: $("#gcEnabled").checked, auto_sync: $("#gcAuto").checked,
        },
      });
      $("#gcalDlg").close(); toast("Google 日曆設定已儲存");
    } catch (er) { $("#gcalErr").textContent = er.message; }
  });

  // 開新案
  $("#newCaseBtn").onclick = openNewCase;
  $("#ncGroup").onchange = ncGroupChanged;
  ["#ncCode", "#ncClient", "#ncCause"].forEach(s => $(s).addEventListener("input", ncPreview));
  ["#ncClient", "#ncOpponent"].forEach(s => $(s).addEventListener("input", ncConflictCheck));
  // 利益衝突檢查、法定期間計算
  $("#conflictDlg form").addEventListener("submit", e => {
    if (e.submitter?.value !== "default") return;
    e.preventDefault(); runConflictDlg();
  });
  $("#cfResult").addEventListener("click", e => {
    const a = e.target.closest("[data-open-case]");
    if (!a) return;
    $("#conflictDlg").close(); switchView("cases"); openCase(a.dataset.openCase);
  });
  Deadline.bind();
  setInterval(pollInboxCounts, 60000);
  setTimeout(pollInboxCounts, 12000);
  $("#ncCode").addEventListener("blur", () => {
    const v = $("#ncCode").value.trim().toUpperCase();
    if (/^[A-Z]{1,3}$/.test(v)) { $("#ncCode").value = ncOpts.next_by_prefix[v] || v + "001"; ncPreview(); }
  });
  $("#newCaseForm").addEventListener("submit", e => {
    if (e.submitter?.value !== "default") return;
    e.preventDefault(); createCase();
  });

  $("#showDone").onchange = loadTodos;
  // 今日總覽：點案件打開、勾選完成、點上方數字跳到該區
  $("#viewToday").addEventListener("click", e => {
    const a = e.target.closest("[data-open]");
    if (a) { switchView("cases"); openCase(a.dataset.open); return; }
    const j = e.target.closest("[data-jump]");
    if (j) $("#" + j.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (e.target.closest("#todayRefresh")) { loadCases(true).then(loadToday); }
  });
  $("#viewToday").addEventListener("keydown", e => {
    if (e.key === "Enter" && e.target.matches("[data-open]")) e.target.click();
  });
  $("#viewToday").addEventListener("change", async e => {
    const cb = e.target; if (!cb.dataset.case) return;
    try {
      const d = await api(`/api/case/${cb.dataset.case}`);
      const todos = d.card.todos.map(t => ({ ...t }));
      const t = todos.find(x => cb.dataset.gcal ? x.gcal === cb.dataset.gcal
        : x.text === cb.dataset.text && (x.due || "") === cb.dataset.due);
      if (!t) { toast("這條待辦已被修改或刪除，已重新整理"); loadToday(); return; }
      t.done = cb.checked;
      await api(`/api/case/${cb.dataset.case}/card`, { method: "PUT", body: { meta: d.card.meta, todos, base_mtime: d.card.mtime } });
      toast("已完成"); loadToday();
    } catch (er) { toast(er.message); loadToday(); }
  });
  $("#todoRows").addEventListener("click", e => {
    const a = e.target.closest("a[data-open]");
    if (a) { switchView("cases"); openCase(a.dataset.open); }
  });
  $("#todoRows").addEventListener("change", async e => {
    const cb = e.target; if (!cb.dataset.case) return;
    try {
      const d = await api(`/api/case/${cb.dataset.case}`);
      const todos = d.card.todos.map(t => ({ ...t }));
      const t = todos.find(x => cb.dataset.gcal ? x.gcal === cb.dataset.gcal
        : x.text === cb.dataset.text && (x.due || "") === cb.dataset.due);
      if (!t) { toast("這條待辦已被修改或刪除，已重新整理"); loadTodos(); return; }
      t.done = cb.checked;
      await api(`/api/case/${cb.dataset.case}/card`, { method: "PUT", body: { meta: d.card.meta, todos, base_mtime: d.card.mtime } });
      toast(cb.checked ? "已完成" : "已取消完成"); loadTodos();
    } catch (er) { toast(er.message); }
  });
}

(async function init() {
  Theme.init(null);                              // 先用上次的外觀（本機快取），避免閃一下預設色
  bind();
  state.sort = STORE.get("casedesk.sort", "recent");
  $("#sortSel").value = state.sort;
  state.scope = STORE.get("casedesk.scope", "case");
  await loadMeta();
  try { state.ui = await api("/api/ui"); } catch { state.ui = {}; }
  if (state.ui.theme) { Theme.saved = { ...THEME_DEFAULT, ...state.ui.theme }; applyTheme(Theme.saved); }
  $("#modelSel").value = state.ui.claude?.model || "";
  $("#effortSel").value = state.ui.claude?.effort || "";
  await loadCases();
  const qs = new URLSearchParams(location.search);
  if (qs.get("view") && ["today", "calendar", "todos"].includes(qs.get("view"))) switchView(qs.get("view"));
  else if (qs.get("case")) await openCase(qs.get("case"));
  else switchView("today");                       // 開程式先看今天與本週
  loadChat();
  renderScopeLabel();
  updateGcalChip();
  loadCaps();
})();
