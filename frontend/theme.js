"use strict";
/* 外觀：十種經典配色＋自訂顏色、字體、字級。
   主題只定五個基本色（背景、面板、文字、次要文字、強調色），其餘（分隔線、淡底…）用
   color-mix 由基本色推算，所以任何自訂組合都能自洽。深淺由背景亮度自動判斷。 */

const THEMES = {
  "forest-desk":    { name: "墨綠案頭", group: "desk", bg: "#17231d", panel: "#1c2b23", text: "#e5ece5", muted: "#a3b5a6", accent: "#b5ceaa", gold: "#c7b07c" },
  "paper-desk":     { name: "宣紙案頭", group: "desk", bg: "#f3f1eb", panel: "#fcfbf7", text: "#27372e", muted: "#626e62", accent: "#344f3c", gold: "#82704a" },
  paper:            { name: "宣紙",            bg: "#f6f5f2", panel: "#ffffff", text: "#22201c", muted: "#7a756c", accent: "#2f5d8a" },
  ink:              { name: "墨夜",            bg: "#18191b", panel: "#212225", text: "#e6e3dd", muted: "#9a958c", accent: "#7fa8d6" },
  "solarized-light":{ name: "Solarized 淺",    bg: "#eee8d5", panel: "#fdf6e3", text: "#3c4c52", muted: "#7b8b8f", accent: "#268bd2" },
  "solarized-dark": { name: "Solarized 深",    bg: "#002b36", panel: "#073642", text: "#d3dcdc", muted: "#8a9a9a", accent: "#2aa198" },
  github:           { name: "GitHub 淺",       bg: "#f6f8fa", panel: "#ffffff", text: "#1f2328", muted: "#59636e", accent: "#0969da" },
  latte:            { name: "Catppuccin 拿鐵", bg: "#e6e9ef", panel: "#eff1f5", text: "#4c4f69", muted: "#6c6f85", accent: "#8839ef" },
  nord:             { name: "Nord 北境",       bg: "#2e3440", panel: "#3b4252", text: "#eceff4", muted: "#a5afc2", accent: "#88c0d0" },
  dracula:          { name: "Dracula 吸血鬼",  bg: "#21222c", panel: "#282a36", text: "#f8f8f2", muted: "#a2a9cc", accent: "#bd93f9" },
  gruvbox:          { name: "Gruvbox 復古",    bg: "#1d2021", panel: "#282828", text: "#ebdbb2", muted: "#a89984", accent: "#fabd2f" },
  monokai:          { name: "Monokai",         bg: "#1e1f1c", panel: "#272822", text: "#f8f8f2", muted: "#a8a48e", accent: "#a6e22e" },

  // ---- 綠色系 ----
  matcha:           { name: "抹茶",   group: "green", bg: "#eef2e6", panel: "#f9fbf4", text: "#2b3524", muted: "#66755a", accent: "#557a26" },
  mint:             { name: "薄荷",   group: "green", bg: "#e6f4ee", panel: "#f6fcf9", text: "#1d382e", muted: "#5a7a6e", accent: "#127a59" },
  bamboo:           { name: "竹青",   group: "green", bg: "#e7eee2", panel: "#f7faf4", text: "#24312a", muted: "#617265", accent: "#3a7649" },
  jade:             { name: "翡翠",   group: "green", bg: "#e4efea", panel: "#f6fbf9", text: "#1c3832", muted: "#5a7770", accent: "#00775f" },
  sage:             { name: "鼠尾草", group: "green", bg: "#e8ebe4", panel: "#f5f6f2", text: "#2c3329", muted: "#6a7366", accent: "#4f7444" },
  forest:           { name: "墨綠",   group: "green", bg: "#14201a", panel: "#1b2a22", text: "#e1ebe3", muted: "#94a89a", accent: "#7fc49a" },
  pine:             { name: "松針",   group: "green", bg: "#0f1d1b", panel: "#162825", text: "#dce9e5", muted: "#8fa7a0", accent: "#4fc1a7" },
  moss:             { name: "青苔",   group: "green", bg: "#1a1f14", panel: "#23291b", text: "#e6ead9", muted: "#a0a88d", accent: "#a4c45a" },
  everforest:       { name: "Everforest", group: "green", bg: "#272e33", panel: "#2e383c", text: "#d3c6aa", muted: "#9da9a0", accent: "#a7c080" },
  chalkboard:       { name: "黑板",   group: "green", bg: "#1d2b25", panel: "#24362e", text: "#eef2ea", muted: "#a5b8ab", accent: "#f0d270" },
};

const FONTS = [
  ["微軟正黑體", '"Microsoft JhengHei UI", "Microsoft JhengHei", sans-serif'],
  ["思源黑體", '"Noto Sans TC", "Source Han Sans TC", "思源黑體", "Microsoft JhengHei UI", sans-serif'],
  ["思源宋體", '"Noto Serif TC", "Source Han Serif TC", "思源宋體", PMingLiU, serif'],
  ["新細明體", 'PMingLiU, "新細明體", serif'],
  ["標楷體", 'DFKai-SB, "標楷體", BiauKai, serif'],
  ["Segoe UI", '"Segoe UI", "Microsoft JhengHei UI", sans-serif'],
];

const COLOR_KEYS = [["bg", "背景"], ["panel", "面板"], ["text", "文字"], ["muted", "次要文字"], ["accent", "強調色"]];
const THEME_DEFAULT = { preset: "forest-desk", custom: {}, font: "微軟正黑體", fontCustom: "", size: 16 };

function hexLum(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return 0.5;
  const n = parseInt(m[1], 16), ch = [n >> 16, (n >> 8) & 255, n & 255].map(v => {
    v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
}

const darkMQ = window.matchMedia("(prefers-color-scheme: dark)");
function presetKey(t) { return t.preset === "auto" ? (darkMQ.matches ? "ink" : "paper") : (THEMES[t.preset] ? t.preset : "paper"); }

function themeColors(t) {
  const base = THEMES[presetKey(t)], out = { ...base };
  for (const [k] of COLOR_KEYS) if (t.custom && t.custom[k]) out[k] = t.custom[k];
  return out;
}

function applyTheme(t) {
  t = { ...THEME_DEFAULT, ...(t || {}) };
  const c = themeColors(t), r = document.documentElement, st = r.style;
  r.dataset.scheme = hexLum(c.bg) < 0.25 ? "dark" : "light";
  st.setProperty("--bg", c.bg);
  st.setProperty("--panel", c.panel);
  st.setProperty("--text", c.text);
  st.setProperty("--muted", c.muted);
  st.setProperty("--accent", c.accent);
  st.setProperty("--gold", c.gold || c.accent);
  st.setProperty("--panel-2", `color-mix(in srgb, ${c.panel} 55%, ${c.bg})`);
  st.setProperty("--line", `color-mix(in srgb, ${c.text} 16%, ${c.panel})`);
  st.setProperty("--line-2", `color-mix(in srgb, ${c.text} 8%, ${c.panel})`);
  st.setProperty("--accent-soft", `color-mix(in srgb, ${c.accent} 16%, ${c.panel})`);
  // 強調色上的字：黑白兩色挑對比較高的那個（原本的門檻太高，中等亮度的強調色配白字看不清楚）
  const la = hexLum(c.accent);
  st.setProperty("--on-accent", (la + 0.05) / (0.0116 + 0.05) > 1.05 / (la + 0.05) ? "#1b1b1b" : "#ffffff");
  const stack = (FONTS.find(f => f[0] === t.font) || FONTS[0])[1];
  st.setProperty("--font", t.fontCustom ? `"${t.fontCustom.replace(/"/g, "")}", ${stack}` : stack);
  st.setProperty("--fs", Math.min(22, Math.max(11, +t.size || 16)) + "px");
  if (window.parent !== window) window.parent.postMessage({ type: "appearance" }, location.origin);
}

/* ---------------- 外觀對話框 ---------------- */
const Theme = {
  saved: { ...THEME_DEFAULT }, draft: null,

  init(fromServer) {
    let local = null;
    try { local = JSON.parse(localStorage.getItem("casedesk.theme") || "null"); } catch { }
    this.saved = { ...THEME_DEFAULT, ...(fromServer || local || {}) };
    applyTheme(this.saved);
    darkMQ.addEventListener("change", () => applyTheme(this.draft || this.saved));
  },

  open() {
    this.draft = JSON.parse(JSON.stringify(this.saved));
    this.render();
    document.querySelector("#themeDlg").showModal();
  },

  render() {
    const t = this.draft, c = themeColors(t);
    const tile = (key, th) => {
      const sel = t.preset === key ? "sel" : "";
      return `<button type="button" class="th-tile ${sel}" data-preset="${key}" style="background:${th.bg};color:${th.text}">
        <span class="th-panel" style="background:${th.panel}"><b style="color:${th.accent}">Aa</b> 案件<i style="background:${th.accent}"></i>
        <em style="color:${th.muted}">CM097・刑事</em></span><span class="th-name">${th.name}</span></button>`;
    };
    const auto = { name: "跟隨 Windows", bg: "linear-gradient(135deg,#f6f5f2 50%,#18191b 50%)", panel: "#ffffff", text: "#22201c", muted: "#7a756c", accent: "#2f5d8a" };
    document.querySelector("#themeBody").innerHTML = `
      <h3>案頭配色</h3>
      <div class="th-grid">${Object.entries(THEMES).filter(([, th]) => th.group === "desk").map(([k, th]) => tile(k, th)).join("")}</div>
      <h3>經典配色</h3>
      <div class="th-grid">${tile("auto", auto)}${Object.entries(THEMES).filter(([, th]) => !th.group).map(([k, th]) => tile(k, th)).join("")}</div>
      <h3>綠色系</h3>
      <div class="th-grid">${Object.entries(THEMES).filter(([, th]) => th.group === "green").map(([k, th]) => tile(k, th)).join("")}</div>
      <h3>自訂顏色 <span class="muted small">（在所選配色上微調；按 ↺ 恢復配色原值）</span></h3>
      <div class="th-colors">${COLOR_KEYS.map(([k, label]) => `
        <label class="th-color"><span>${label}</span><input type="color" data-color="${k}" value="${c[k]}">
          <button type="button" class="btn ghost small" data-reset="${k}" ${t.custom[k] ? "" : "disabled"} title="恢復配色原值">↺</button></label>`).join("")}
      </div>
      <h3>字體</h3>
      <div class="th-row">
        <select id="thFont">${FONTS.map(([n]) => `<option ${n === t.font ? "selected" : ""}>${n}</option>`).join("")}</select>
        <input id="thFontCustom" placeholder="或輸入電腦上其他字型名稱（例如 Noto Sans TC）" value="${(t.fontCustom || "").replace(/"/g, "&quot;")}">
      </div>
      <h3>字體大小</h3>
      <div class="th-row">
        <input type="range" id="thSize" min="12" max="20" step="1" value="${t.size}">
        <span id="thSizeLabel">${t.size} px</span>
        <span class="muted small">預設 16 px</span>
      </div>`;
  },

  bind() {
    const body = document.querySelector("#themeBody"), dlg = document.querySelector("#themeDlg");
    body.addEventListener("click", e => {
      const tile = e.target.closest("[data-preset]");
      if (tile) { this.draft.preset = tile.dataset.preset; this.draft.custom = {}; this.preview(true); return; }
      const rs = e.target.closest("[data-reset]");
      if (rs) { delete this.draft.custom[rs.dataset.reset]; this.preview(true); }
    });
    body.addEventListener("input", e => {
      const el = e.target;
      if (el.dataset.color) { this.draft.custom[el.dataset.color] = el.value; this.preview(false); }
      else if (el.id === "thSize") { this.draft.size = +el.value; document.querySelector("#thSizeLabel").textContent = el.value + " px"; this.preview(false); }
      else if (el.id === "thFontCustom") { this.draft.fontCustom = el.value.trim(); this.preview(false); }
    });
    body.addEventListener("change", e => {
      if (e.target.id === "thFont") { this.draft.font = e.target.value; this.preview(false); }
      if (e.target.dataset.color) this.render();      // 讓 ↺ 按鈕的可用狀態更新
    });
    document.querySelector("#themeReset").onclick = () => { this.draft = { ...THEME_DEFAULT, custom: {} }; this.preview(true); };
    // 直接接按鈕的 submit（同步觸發），不靠 dialog 的 close 事件——後者在背景分頁可能延遲
    dlg.querySelector("form").addEventListener("submit", e => {
      if (!this.draft) return;
      if (e.submitter?.value === "save") this.save();
      else applyTheme(this.saved);                     // 取消：還原
      this.draft = null;
    });
    dlg.addEventListener("cancel", () => { applyTheme(this.saved); this.draft = null; });   // Esc
  },

  preview(rerender) { applyTheme(this.draft); if (rerender) this.render(); },

  async save() {
    this.saved = this.draft;
    applyTheme(this.saved);
    try { localStorage.setItem("casedesk.theme", JSON.stringify(this.saved)); } catch { }
    if (window.saveUi) await window.saveUi({ theme: this.saved });
  },
};
