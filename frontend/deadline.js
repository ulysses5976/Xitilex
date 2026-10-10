"use strict";
/* 律法夕惕者 Xitilex：法定期間計算器。© 2026 無名小律師（楊朝淵律師）. Released under the MIT License.

   計算方式（民事訴訟法第161條、刑事訴訟法第65條、行政訴訟法第88條均依民法規定）：
   1. 送達生效日：一般送達＝送達當日；寄存送達＝寄存日起經 10 日；公示送達＝民事經 20 日、刑事經 30 日。
   2. 始日不算入（民法第120條第2項），自生效日翌日起算。
      以日定期間：末日＝生效日＋N 日。
      以月定期間（民法第121條第2項）：起算日為某月 1 日者，末日為最後一個月的月底；
      否則為最後一個月與起算日相當日之前一日；最後一個月沒有相當日時，以該月月底為末日。
   3. 加上在途期間（民訴第162條、刑訴第66條；有住居法院所在地的訴訟代理人時不扣除）。
   4. 末日為星期六、日、國定假日或其他休息日（含颱風等停止上班日）時，順延到下一個上班日（民法第122條）；
      週末補行上班日視為上班日。 */

const Deadline = (() => {
  const KINDS = [
    { g: "民事", items: [
      ["civ-appeal", "上訴", 20, "d", "民事訴訟法第440條"],
      ["civ-3rd", "第三審上訴理由書", 20, "d", "民事訴訟法第471條第1項（提起上訴後20日內）", "提起上訴日", "plain"],
      ["civ-int", "抗告", 10, "d", "民事訴訟法第487條"],
      ["civ-retrial", "再審之訴", 30, "d", "民事訴訟法第500條第1項"],
      ["civ-payorder", "支付命令異議", 20, "d", "民事訴訟法第516條第1項"],
      ["civ-restore", "聲請回復原狀", 10, "d", "民事訴訟法第164條第1項（遲誤原因消滅後10日內）", "遲誤原因消滅日", "plain"],
    ] },
    { g: "非訟／家事／消債", items: [
      ["nc-int", "非訟事件抗告", 10, "d", "非訟事件法第42條第1項"],
      ["fam-int", "家事非訟事件抗告", 10, "d", "家事事件法第97條準用非訟事件法第42條"],
      ["cdr-int", "消債事件抗告", 10, "d", "消費者債務清理條例第15條準用民事訴訟法第487條"],
    ] },
    { g: "刑事", items: [
      ["cr-appeal", "上訴", 20, "d", "刑事訴訟法第349條"],
      ["cr-3rd", "第三審上訴理由書", 20, "d", "刑事訴訟法第382條第1項（提起上訴後20日內）", "提起上訴日", "plain"],
      ["cr-int", "抗告", 10, "d", "刑事訴訟法第406條"],
      ["cr-quasi", "準抗告", 10, "d", "刑事訴訟法第416條第3項"],
      ["cr-recon", "聲請再議", 10, "d", "刑事訴訟法第256條第1項"],
      ["cr-private", "聲請准許提起自訴", 10, "d", "刑事訴訟法第258條之1第1項"],
    ] },
    { g: "行政", items: [
      ["adm-pet", "訴願", 30, "d", "訴願法第14條第1項", "處分達到日"],
      ["adm-suit", "撤銷訴訟起訴", 2, "m", "行政訴訟法第106條第1項（訴願決定書送達後2個月）"],
      ["adm-appeal", "上訴", 20, "d", "行政訴訟法第241條"],
      ["adm-int", "抗告", 10, "d", "行政訴訟法第268條"],
    ] },
    { g: "自訂", items: [
      ["custom-d", "自訂天數（補正期間等）", 0, "d", ""],
      ["custom-m", "自訂月數", 0, "m", ""],
    ] },
  ];
  const SERVE = [
    ["normal", "一般送達（送達當日生效）", 0],
    ["deposit", "寄存送達（自寄存日起經10日生效）", 10],
    ["public-civ", "公示送達－民事（經20日生效，民訴第152條）", 20],
    ["public-cr", "公示送達－刑事（經30日生效，刑訴第60條）", 30],
  ];
  const WD = "日一二三四五六";
  let H = null;                                        // 假日資料
  let ctx = { cid: null };

  /* ---------- 日期工具（一律用 UTC，避免時區造成差一天） ---------- */
  const parse = s => { const [y, m, d] = s.split("-").map(Number); return new Date(Date.UTC(y, m - 1, d)); };
  const iso = d => d.toISOString().slice(0, 10);
  const addDays = (d, n) => new Date(d.getTime() + n * 86400000);
  const lastDay = (y, m) => new Date(Date.UTC(y, m + 1, 0)).getUTCDate();      // m：0–11
  const show = d => `${iso(d)}（${WD[d.getUTCDay()]}）`;

  function addMonthsFromStart(start, n) {            // start＝起算日（始日不算入之後的第一天）
    const y = start.getUTCFullYear(), m = start.getUTCMonth(), day = start.getUTCDate();
    const ty = y + Math.floor((m + n - 1) / 12), tm = (m + n - 1) % 12;          // 最後一個月
    if (day === 1) return new Date(Date.UTC(ty, tm, lastDay(ty, tm)));           // 自月之始日起算
    const ly = y + Math.floor((m + n) / 12), lm = (m + n) % 12;                   // 相當日所在的月
    if (day > lastDay(ly, lm)) return new Date(Date.UTC(ly, lm, lastDay(ly, lm))); // 沒有相當日
    return addDays(new Date(Date.UTC(ly, lm, day)), -1);                           // 相當日之前一日
  }

  function restReason(d) {
    const s = iso(d), y = d.getUTCFullYear();
    if (H.extra[s]) return H.extra[s];
    if (H.holidays[s] !== undefined && !(H.workdaySet.has(s))) {
      const wd = d.getUTCDay();
      return H.holidays[s] || (wd === 0 ? "星期日" : wd === 6 ? "星期六" : "放假日");
    }
    if (H.workdaySet.has(s)) return "";
    if (!H.yearSet.has(y)) { const wd = d.getUTCDay(); return wd === 0 ? "星期日" : wd === 6 ? "星期六" : ""; }
    return "";
  }

  function compute({ kind, n, base, serve, travel }) {
    const k = findKind(kind), steps = [], warn = [];
    const unit = k[3], N = k[2] || n;
    if (!N || N < 1) return { error: "請填期間長度" };
    if (!base) return { error: "請填" + (k[5] || "送達日") };
    const sv = k[6] === "plain" ? SERVE[0] : SERVE.find(s => s[0] === serve) || SERVE[0];
    let eff = parse(base);
    if (sv[2]) {
      eff = addDays(eff, sv[2]);
      steps.push(`${sv[1].split("（")[0]}：${show(parse(base))} 起經 ${sv[2]} 日，於 ${show(eff)} 發生送達效力`);
    } else {
      steps.push(`${k[5] || "送達日"}：${show(eff)}（始日不算入，自 ${show(addDays(eff, 1))} 起算）`);
    }
    let end;
    if (unit === "d") {
      end = addDays(eff, N);
      steps.push(`${N} 日期間 → 末日 ${show(end)}`);
    } else {
      end = addMonthsFromStart(addDays(eff, 1), N);
      steps.push(`${N} 個月期間（民法第121條第2項）→ 末日 ${show(end)}`);
    }
    if (travel > 0) {
      end = addDays(end, travel);
      steps.push(`加計在途期間 ${travel} 日 → ${show(end)}`);
    }
    let moved = 0;
    for (let r = restReason(end); r && moved < 30; r = restReason(end)) {
      steps.push(`${show(end)} 是休息日（${r}），順延一日`);
      end = addDays(end, 1); moved++;
    }
    if (moved) steps.push(`→ 末日順延至 ${show(end)}`);
    const years = new Set([parse(base).getUTCFullYear(), end.getUTCFullYear()]);
    for (const y of years) if (!H.yearSet.has(y)) warn.push(`沒有 ${y} 年的國定假日資料，只依星期六、日判斷；請按下方「更新假日資料」或自行核對。`);
    return { end: iso(end), endText: show(end), steps, warn, kind: k, eff: iso(eff) };
  }

  /* [代碼, 名稱, 期間長度, 單位 d/m, 條文, 基準日名稱, plain（不適用送達方式）, 類別] */
  function findKind(id) {
    const full = (it, g) => { const [a, b, n, u, cite = "", baseLabel = "", mode = ""] = it; return [a, b, n, u, cite, baseLabel, mode, g]; };
    for (const g of KINDS) for (const it of g.items) if (it[0] === id) return full(it, g.g);
    return full(KINDS[0].items[0], KINDS[0].g);
  }

  async function loadHolidays(force) {
    if (H && !force) return H;
    const d = force ? await api("/api/holidays/refresh", { method: "POST" }) : await api("/api/holidays");
    H = { ...d, workdaySet: new Set(d.workdays), yearSet: new Set(d.years) };
    return H;
  }

  /* 給 Claude 的提示用：今天起 N 天內的國定假日、補假、臨時停班日 */
  async function restDaysText(days = 120) {
    try { await loadHolidays(); } catch { return ""; }
    const t0 = parse(today()), out = [];
    for (let i = 0; i < days; i++) {
      const d = addDays(t0, i), s = iso(d), wd = d.getUTCDay();
      if (H.extra[s]) out.push(`${s} ${H.extra[s]}`);
      else if (H.holidays[s] !== undefined && wd !== 0 && wd !== 6) out.push(`${s}（${WD[wd]}）${H.holidays[s] || "放假"}`);
      else if (H.workdaySet.has(s)) out.push(`${s}（${WD[wd]}）補行上班`);
    }
    return out.join("、");
  }

  /* ---------- 對話框 ---------- */
  function kindOptions() {
    return KINDS.map(g => `<optgroup label="${esc(g.g)}">${g.items.map(it =>
      `<option value="${it[0]}">${esc(g.g === "自訂" ? it[1] : g.g + "・" + it[1])}${it[2] ? `（${it[3] === "m" ? it[2] + " 個月" : it[2] + " 日"}）` : ""}</option>`).join("")}</optgroup>`).join("");
  }

  async function open() {
    const dlg = $("#deadlineDlg");
    ctx = { cid: state.detail && !$("#viewCases").hidden ? state.detail.case.id : null };
    if (!$("#dlKind").options.length) {
      $("#dlKind").innerHTML = kindOptions();
      $("#dlServe").innerHTML = SERVE.map(s => `<option value="${s[0]}">${esc(s[1])}</option>`).join("");
    }
    const c = ctx.cid ? state.detail.case : null;
    $("#dlCase").textContent = c ? `${c.code} ${c.client}${c.cause ? "｜" + c.cause : ""}` : "（沒有開啟案件：只能計算，不能直接加入待辦）";
    $("#dlSubWrap").innerHTML = c ? subSelect("dlSub") : "";
    $("#dlAddBox").hidden = !c;
    $("#dlAddBtn").hidden = !c;
    if (!$("#dlBase").value) $("#dlBase").value = today();
    $("#dlErr").textContent = "";
    dlg.showModal();
    try { await loadHolidays(); } catch (e) { $("#dlErr").textContent = "讀不到假日資料：" + e.message; H = { holidays: {}, workdays: [], years: [], extra: {}, workdaySet: new Set(), yearSet: new Set() }; }
    renderHolidayInfo();
    update(true);
  }

  function renderHolidayInfo() {
    const ys = [...H.yearSet].sort();
    const ex = Object.entries(H.extra || {});
    $("#dlHolInfo").innerHTML = `國定假日資料：${ys.length ? ys.join("、") + " 年" : "無"}（${esc(H.source || "行政院人事行政總處")}）・
      <a class="link" id="dlRefresh">更新假日資料</a>・<a class="link" id="dlExtraToggle">臨時停班日（${ex.length}）</a>`;
    $("#dlExtraList").innerHTML = ex.length ? ex.map(([d, r]) =>
      `<li><span>${esc(d)}（${WD[parse(d).getUTCDay()]}）${esc(r)}</span><button type="button" class="del" data-extra-del="${esc(d)}" title="移除">✕</button></li>`).join("")
      : `<li class="muted small">目前沒有。颱風等臨時停止上班日請在這裡加，三台電腦共用。</li>`;
  }

  function current() {
    return { kind: $("#dlKind").value, n: +$("#dlN").value || 0, base: $("#dlBase").value, serve: $("#dlServe").value,
             travel: Math.max(0, Math.min(60, +$("#dlTravel").value || 0)) };
  }

  let lastAuto = { text: "", remind: "" };
  function update(resetText) {
    if (!H) return;
    const inp = current(), k = findKind(inp.kind);
    const custom = !k[2];
    $("#dlN").hidden = $("#dlNLabel").hidden = !custom;
    $("#dlNLabel").textContent = k[3] === "m" ? "月數" : "天數";
    $("#dlBaseLabel").textContent = k[5] || "送達日";
    $("#dlServeRow").hidden = $("#dlServeLabel").hidden = k[6] === "plain";
    const r = compute(inp);
    if (r.error) { $("#dlResult").innerHTML = `<div class="muted">${esc(r.error)}</div>`; $("#dlAddBtn").disabled = true; return; }
    $("#dlAddBtn").disabled = false;
    $("#dlResult").innerHTML = `
      <div class="dl-end"><span class="muted small">期限末日</span><b>${esc(r.endText)}</b>
        <span class="muted small">${esc(k[4] || "")}</span></div>
      <ol class="dl-steps">${r.steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol>
      ${r.warn.map(w => `<div class="dl-warn">⚠ ${esc(w)}</div>`).join("")}
      <div class="muted small">請以法院實際送達證書與最新法規為準；期間性質（不變期間或得延長）請自行判斷。</div>`;
    // 待辦文字：使用者沒自己改過才自動更新
    const label = (k[7] === "自訂" ? "期限" : k[7] + k[1] + "期間") + "末日";
    const auto = `${label}（${k[5] || "送達"} ${inp.base}${inp.serve !== "normal" && k[6] !== "plain" ? "，" + (SERVE.find(s => s[0] === inp.serve) || SERVE[0])[1].split("（")[0] : ""}）`;
    if (resetText || $("#dlText").value === lastAuto.text || !$("#dlText").value) $("#dlText").value = auto;
    const remind = `準備${k[7] === "自訂" ? "" : k[1]}（${r.end} 期限）`;
    if (resetText || $("#dlRemindText").value === lastAuto.remind || !$("#dlRemindText").value) $("#dlRemindText").value = remind;
    lastAuto = { text: auto, remind };
    $("#dlResult").dataset.end = r.end;
  }

  async function addTodo() {
    const end = $("#dlResult").dataset.end;
    if (!end || !ctx.cid) return;
    if (!state.detail || state.detail.case.id !== ctx.cid) { toast("案件已切換，請重新開啟期限計算"); return; }
    const text = withSub("dlSub", $("#dlText").value.trim());
    if (!text) { toast("請填待辦內容"); return; }
    const items = [{ done: false, due: end, text }];
    if ($("#dlRemind").checked) {
      const n = Math.max(1, Math.min(60, +$("#dlRemindN").value || 3));
      let rd = addDays(parse(end), -n);
      for (let i = 0; i < 14 && restReason(rd); i++) rd = addDays(rd, -1);     // 提醒落在假日就提早到前一個上班日
      items.push({ done: false, due: iso(rd), text: withSub("dlSub", $("#dlRemindText").value.trim() || "提醒") });
    }
    $("#deadlineDlg").close();
    await saveCard((m, todos) => { todos.push(...items); }, items.length > 1 ? "已加入期限與提前提醒" : "已加入期限待辦");
  }

  function bind() {
    const dlg = $("#deadlineDlg");
    ["#dlKind", "#dlBase", "#dlServe", "#dlTravel", "#dlN"].forEach(s => $(s).addEventListener("input", () => update(s === "#dlKind")));
    $("#dlKind").addEventListener("change", () => update(true));
    dlg.querySelector("form").addEventListener("submit", e => {
      if (e.submitter?.value !== "default") return;
      e.preventDefault(); addTodo();
    });
    dlg.addEventListener("click", async e => {
      if (e.target.id === "dlRefresh") {
        e.target.textContent = "更新中…";
        try { const r = await loadHolidays(true); toast(r.updated?.length ? `已更新 ${r.updated.join("、")} 年假日資料` : "沒有可更新的資料"); }
        catch (er) { toast("更新失敗：" + er.message); }
        renderHolidayInfo(); update(false);
      } else if (e.target.id === "dlExtraToggle") {
        $("#dlExtraBox").hidden = !$("#dlExtraBox").hidden;
      } else if (e.target.dataset.extraDel) {
        const ex = { ...H.extra }; delete ex[e.target.dataset.extraDel];
        await saveExtra(ex);
      } else if (e.target.id === "dlExtraAdd") {
        const d = $("#dlExtraDate").value, r = $("#dlExtraReason").value.trim() || "停止上班";
        if (!d) { toast("請選日期"); return; }
        await saveExtra({ ...H.extra, [d]: r });
        $("#dlExtraDate").value = ""; $("#dlExtraReason").value = "";
      }
    });
  }

  async function saveExtra(ex) {
    try {
      const d = await api("/api/holidays/extra", { method: "PUT", body: { extra: ex } });
      H = { ...d, workdaySet: new Set(d.workdays), yearSet: new Set(d.years) };
      renderHolidayInfo(); update(false);
    } catch (e) { toast("存檔失敗：" + e.message); }
  }

  return { open, bind, compute, loadHolidays, restDaysText, _setHolidays: d => { H = { ...d, workdaySet: new Set(d.workdays), yearSet: new Set(d.years) }; } };
})();
