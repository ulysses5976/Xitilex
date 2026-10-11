# -*- coding: utf-8 -*-
"""HTTP API。只綁 127.0.0.1，單人本機使用。"""
from __future__ import annotations
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import card, claude_runner, conflict, diag, gcal, holidays, inbox, newcase, scanner, settings, titles

app = FastAPI(title="律法夕惕者 Xitilex")
CFG = settings.load()


@app.middleware("http")
async def local_only(request: Request, call_next):
    """擋掉從其他網站打進來的請求。

    只綁 127.0.0.1 還不夠：惡意網頁可以用 DNS rebinding 把自己的網域指到 127.0.0.1，
    或直接送跨站表單，叫本系統開檔、叫 Claude 讀案件資料。所以要求 Host 必須是本機，
    會改變狀態的請求若帶了 Origin，也必須是本機。"""
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host not in ("127.0.0.1", "localhost"):
        return JSONResponse({"detail": "拒絕：非本機位址"}, status_code=403)
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD", "OPTIONS") and origin:
        o = origin.split("://", 1)[-1].split(":")[0].lower()
        if o not in ("127.0.0.1", "localhost"):
            return JSONResponse({"detail": "拒絕：跨站請求"}, status_code=403)
    resp = await call_next(request)
    # 前端檔案每次都要跟伺服器確認是否有新版，否則程式更新後瀏覽器會繼續跑舊的 app.js
    if request.url.path in ("/", "/app") or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp

KIND = {
    ".pdf": "pdf", ".doc": "word", ".docx": "word", ".odt": "word", ".rtf": "word",
    ".xls": "excel", ".xlsx": "excel", ".csv": "excel", ".ppt": "ppt", ".pptx": "ppt",
    ".md": "md", ".txt": "text", ".eml": "mail", ".msg": "mail",
    ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".heic": "image",
    ".tif": "image", ".tiff": "image", ".mp3": "audio", ".m4a": "audio", ".wav": "audio",
    ".mp4": "video", ".mov": "video", ".zip": "zip", ".rar": "zip", ".7z": "zip",
}


def _case(cid: str) -> dict:
    c = scanner.get(CFG, cid)
    if not c:
        raise HTTPException(404, "找不到這件案件，可能資料夾已改名，請重新整理。")
    return c


def _inside(case: dict, rel: str) -> Path:
    """把相對路徑解析成案件資料夾內的實際路徑；跑出資料夾外一律拒絕。"""
    base = Path(case["path"]).resolve()
    p = (base / (rel or "")).resolve()
    if p != base and base not in p.parents:
        raise HTTPException(400, "路徑不在案件資料夾內")
    if not p.exists():
        raise HTTPException(404, "檔案不存在：%s" % rel)
    return p


# ------------------------------------------------------------------ 案件

@app.get("/api/meta")
def meta():
    return {"root": CFG["root"], "root_exists": Path(CFG["root"]).exists(),
            "statuses": CFG["statuses"], "fields": card.FIELDS,
            "claude_bin": CFG["claude_bin"], "card_name": CFG["card_name"],
            "claude_credentials": claude_runner.credential_state(),
            "gcal_ready": gcal.ready(CFG), "types": scanner.TYPES,
            "models": claude_runner.MODELS, "efforts": claude_runner.EFFORTS}


@app.get("/api/cases")
def cases(refresh: int = 0):
    cs = scanner.scan(CFG, force=bool(refresh))
    n = inbox.counts()
    for c in cs.values():
        c["new_docs"] = n.get(c["id"], 0)
    if refresh:                                    # 「重新掃描」時新收文書也一起重算
        threading.Thread(target=inbox.scan_all, args=(CFG, list(cs.values())), daemon=True).start()
    return sorted(cs.values(), key=lambda c: -c["mtime"])


@app.get("/api/case/{cid}")
def case_detail(cid: str):
    c = _case(cid)
    d = card.read(Path(c["path"]) / CFG["card_name"]) or \
        {"meta": {}, "todos": [], "hearings": [], "notes": [], "next": "", "subcases": [],
         "title": "", "mtime": 0}
    scanner.refresh_one(CFG, cid)
    try:
        news = inbox.new_files(c, CFG)
    except OSError:
        news = []
    c["new_docs"] = inbox.counts().get(cid, 0)
    return {"case": c, "card": d, "gcal": gcal.case_status(cid), "inbox": news}


class CardIn(BaseModel):
    meta: dict
    todos: list[dict]
    hearings: list[dict] | None = None
    base_mtime: float | None = None    # 前端讀到的案件卡版本；不一致代表別處改過


@app.put("/api/case/{cid}/card")
def save_card(cid: str, body: CardIn):
    c = _case(cid)
    if body.meta.get("案件狀態") and body.meta["案件狀態"] not in CFG["statuses"]:
        raise HTTPException(400, "案件狀態不在清單內")
    title = " ".join(x for x in (c["code"], c["client"], c["cause"]) if x)
    path = Path(c["path"]) / CFG["card_name"]
    with card.lock(path):
        # 前端送的是整張卡。若這段時間 Claude、Obsidian 或另一台電腦改過這張卡，
        # 直接寫入會把對方的修改蓋掉——改回報衝突，讓畫面重新載入。
        if body.base_mtime is not None:
            cur = path.stat().st_mtime if path.exists() else 0
            if abs(cur - body.base_mtime) > 1e-3:
                raise HTTPException(409, "這張案件卡剛被其他地方（Claude、Obsidian 或另一台電腦）修改過，"
                                         "已重新載入最新內容，請再操作一次。")
        card.write(path, body.meta, body.todos, body.hearings, title)
    scanner.refresh_one(CFG, cid)
    queued = gcal.enqueue_case(CFG, cid)
    return {**case_detail(cid), "gcal_queued": queued}


class SummaryIn(BaseModel):
    text: str
    base: str | None = None            # 開始編輯時看到的摘要；跟檔案現況不同代表別處改過


def _norm_summary(s: str) -> str:
    return card.clean_section_text(s or "").strip()


@app.put("/api/case/{cid}/summary")
def save_summary(cid: str, body: SummaryIn):
    """案件頁直接打字的「案件摘要」：只改這一段，其他內容原樣保留。"""
    c = _case(cid)
    if len(body.text) > 200_000:
        raise HTTPException(400, "摘要太長了（超過 20 萬字）")
    title = " ".join(x for x in (c["code"], c["client"], c["cause"]) if x)
    path = Path(c["path"]) / CFG["card_name"]
    with card.lock(path):
        d = card.read(path)
        cur = card.section(d, card.SUMMARY_HEADING)
        if body.base is not None and _norm_summary(cur) != _norm_summary(body.base):
            raise HTTPException(409, "案件摘要在你編輯的期間被其他地方（Claude、Obsidian 或另一台電腦）改過。"
                                     "你打的內容還留在編輯框裡；確認後再按一次儲存就會以你的版本為準。")
        card.write(path, d["meta"] if d else {}, d["todos"] if d else [], None, title,
                   sections={card.SUMMARY_HEADING: body.text})
    scanner.refresh_one(CFG, cid)
    gcal.enqueue_case(CFG, cid)        # 第一次建卡時可能補配了日曆事件編號
    return case_detail(cid)


class MetaIn(BaseModel):
    meta: dict


@app.patch("/api/case/{cid}/meta")
def patch_meta(cid: str, body: MetaIn):
    """只改 frontmatter 幾個欄位（釘選、狀態、種類…），庭期與待辦原樣保留。
    案件還沒有案件卡時會建立一張。"""
    c = _case(cid)
    m = {k: v for k, v in body.meta.items() if k in card.FIELDS and k != "下次期日"}
    if m.get("案件狀態") and m["案件狀態"] not in CFG["statuses"]:
        raise HTTPException(400, "案件狀態不在清單內")
    if m.get("案件類型") and m["案件類型"] not in scanner.TYPES:
        raise HTTPException(400, "案件種類不在清單內")
    title = " ".join(x for x in (c["code"], c["client"], c["cause"]) if x)
    path = Path(c["path"]) / CFG["card_name"]
    with card.lock(path):
        d = card.read(path)
        card.write(path, m, d["todos"] if d else [], None, title)
    scanner.refresh_one(CFG, cid)
    return scanner.get(CFG, cid)


# ------------------------------------------------------------------ Claude 對話紀錄（跨電腦）
#
# 存在程式資料夾的 data/chats/（程式放在雲端硬碟，所以三台電腦看到同一份）。
# 瀏覽器的 localStorage 只當快取。

CHAT_DIR = settings.DATA / "chats"


def _chat_path(key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)[:120]
    if not safe:
        raise HTTPException(400, "對話代碼不正確")
    return CHAT_DIR / (safe + ".json")


def load_chat(key: str) -> dict:
    try:
        d = json.loads(_chat_path(key).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


@app.get("/api/chat/{key}")
def get_chat(key: str):
    return load_chat(key) or {"session_id": None, "messages": [], "updated": 0}


@app.put("/api/chat/{key}")
def put_chat(key: str, body: dict):
    if not isinstance(body.get("messages"), list):
        raise HTTPException(400, "格式不正確")
    body["updated"] = time.time()
    body["host"] = platform.node()
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    settings._write_json(_chat_path(key), body)
    return {"ok": True, "updated": body["updated"]}


def _continue_on_this_machine(prompt: str, session_id: str | None, chat_key: str) -> tuple[str, str | None]:
    """要接續的 Claude 對話若是在別台電腦開始的，這台沒有它的工作階段檔，--resume 會失敗。
    這時改開新的工作階段，並把先前的對話內容附給 Claude 當脈絡。"""
    if not session_id or claude_runner.local_session_exists(session_id):
        return prompt, session_id
    history = claude_runner.transcript_for(load_chat(chat_key).get("messages") or [], prompt)
    if not history:
        return prompt, None
    return ("【先前的對話（在另一台電腦上進行，供你接續參考；其中提到的檔案都在同一個雲端硬碟）】\n"
            + history + "\n\n【律師這次的指示】\n" + prompt), None


# ------------------------------------------------------------------ 介面偏好

@app.get("/api/ui")
def get_ui():
    return CFG.get("ui", {})


@app.put("/api/ui")
def put_ui(body: dict):
    settings.save_section("ui", body)
    CFG["ui"] = settings.load().get("ui", {})
    return CFG["ui"]


@app.get("/api/todos")
def all_todos():
    """跨案件待辦總覽：只看有案件卡的案件。"""
    out = []
    for c in scanner.scan(CFG).values():
        if not c["has_card"]:
            continue
        d = card.read(Path(c["path"]) / CFG["card_name"])
        for i, t in enumerate(d["todos"] if d else []):
            out.append({**t, "index": i, "case_id": c["id"], "code": c["code"],
                        "client": c["client"], "cause": c["cause"],
                        "status": c["status"]})
    out.sort(key=lambda t: (t["done"], t["due"] or "9999", t["code"]))
    return out


# ------------------------------------------------------------------ 庭期月曆

@app.get("/api/calendar")
def calendar(start: str, end: str):
    """start ≤ 日期 < end 的庭期與有期限的待辦（跨所有有案件卡的案件）。"""
    out = []
    for c in scanner.scan(CFG).values():
        if not c["has_card"]:
            continue
        d = card.read(Path(c["path"]) / CFG["card_name"])
        if not d:
            continue
        base = {"case_id": c["id"], "code": c["code"], "client": c["client"],
                "cause": c["cause"], "status": c["status"], "court": d["meta"].get("法院", "")}
        subs = d.get("subcases") or []
        hearing_days = {h["date"] for h in d["hearings"]}

        def labelled(text):
            subject, body, code = titles.subject_body(c, subs, text, d["meta"].get("對造", ""))
            return {"subject": subject, "body": body, "title_code": code}

        for h in d["hearings"]:
            if start <= h["date"] < end:
                out.append({**base, "kind": "hearing", "date": h["date"], "time": h["time"],
                            "text": h["text"], "done": False, **labelled(h["text"])})
        for t in d["todos"]:
            if t["due"] and start <= t["due"] < end and not gcal.is_attendance_dup(t, hearing_days):
                out.append({**base, "kind": "deadline", "date": t["due"], "time": "",
                            "text": t["text"], "done": t["done"], "gcal": t.get("gcal", ""),
                            **labelled(t["text"])})
    out.sort(key=lambda x: (x["date"], x["time"] or "99:99", x["kind"]))
    return out


# ------------------------------------------------------------------ Google 日曆

@app.get("/api/gcal/status")
def gcal_status(deep: int = 0):
    return gcal.status(CFG, deep=bool(deep))


@app.post("/api/gcal/auth")
def gcal_auth():
    gcal.start_auth()
    return {"ok": True}


@app.post("/api/gcal/disconnect")
def gcal_disconnect():
    gcal.disconnect()
    return {"ok": True}


class GcalCfgIn(BaseModel):
    enabled: bool | None = None
    auto_sync: bool | None = None
    calendar_hearing: str | None = None
    calendar_deadline: str | None = None


@app.put("/api/gcal/config")
def gcal_config(body: GcalCfgIn):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    # 換了寫入的日曆：記住舊日曆，之後同步時會從舊日曆把本系統的事件搬走，不留重複
    g = CFG.get("google", {})
    prev = list(g.get("previous_calendars", []))
    for k in ("calendar_hearing", "calendar_deadline"):
        if k in patch and g.get(k) and patch[k] != g[k] and g[k] not in prev:
            prev.append(g[k])
    patch["previous_calendars"] = prev
    settings.save_google(patch)
    CFG.clear()
    CFG.update(settings.load())
    return gcal.status(CFG)


@app.post("/api/gcal/sync")
def gcal_sync(case_id: str = ""):
    ok = gcal.enqueue_case(CFG, case_id, manual=True) if case_id else gcal.enqueue_all(CFG)
    if not ok:
        raise HTTPException(400, "Google 日曆尚未連結或未啟用")
    return {"ok": True}


@app.get("/api/gcal/case/{cid}")
def gcal_case(cid: str):
    return {"status": gcal.case_status(cid), "busy": gcal._state["busy"]}


# ------------------------------------------------------------------ 開新案

@app.get("/api/newcase/options")
def newcase_options():
    return newcase.options(CFG)


class NewCaseIn(BaseModel):
    opponent: str = ""
    group_dir: str = ""
    template: str = ""
    code: str
    client: str
    cause: str = ""
    status: str = "進行中"
    retained: str = ""


@app.post("/api/newcase")
def newcase_create(body: NewCaseIn):
    try:
        r = newcase.create(CFG, body.group_dir, body.template, body.code, body.client,
                           body.cause, body.status, body.retained, body.opponent)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(500, "建立資料夾失敗：%s" % e)
    return r


# ------------------------------------------------------------------ 檔案

@app.get("/api/case/{cid}/files")
def list_files(cid: str, sub: str = ""):
    c = _case(cid)
    d = _inside(c, sub)
    if not d.is_dir():
        raise HTTPException(400, "不是資料夾")
    items = []
    with os.scandir(d) as it:
        for e in it:
            if e.name.startswith((".", "~$")) or e.name == "desktop.ini" \
                    or e.name.endswith(".saving"):
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            is_dir = e.is_dir()
            ext = os.path.splitext(e.name)[1].lower()
            items.append({
                "name": e.name, "dir": is_dir,
                "rel": str(Path(sub) / e.name) if sub else e.name,
                "kind": "folder" if is_dir else KIND.get(ext, "file"),
                "ext": ext.lstrip("."), "size": 0 if is_dir else st.st_size,
                "mtime": st.st_mtime,
                "gdoc": ext in (".gdoc", ".gsheet", ".gslides"),
            })
    items.sort(key=lambda x: (not x["dir"], x["name"]))
    return {"sub": sub, "items": items}


def open_with_default_app(p: Path) -> None:
    """用電腦的預設程式開啟（Windows：等同在檔案總管雙擊；Mac：open）。"""
    if sys.platform == "win32":
        os.startfile(str(p))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def reveal_in_file_manager(p: Path) -> None:
    """在檔案總管（Mac：Finder）中顯示；是檔案的話會反白選取。"""
    if sys.platform == "win32":
        if p.is_dir():
            os.startfile(str(p))
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)] if p.is_dir() else ["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])


class PathIn(BaseModel):
    rel: str = ""


@app.post("/api/case/{cid}/open")
def open_file(cid: str, body: PathIn):
    """用 Windows 預設程式開啟（等同在檔案總管雙擊）。"""
    p = _inside(_case(cid), body.rel)
    try:
        open_with_default_app(p)
    except OSError as e:
        raise HTTPException(500, "開啟失敗：%s" % e)
    return {"ok": True}


@app.post("/api/case/{cid}/reveal")
def reveal(cid: str, body: PathIn):
    """在檔案總管中顯示（檔案會被反白選取）。"""
    p = _inside(_case(cid), body.rel)
    reveal_in_file_manager(p)
    return {"ok": True}


# ------------------------------------------------------------------ Claude

class AskIn(BaseModel):
    prompt: str
    session_id: str | None = None
    model: str = ""
    effort: str = ""
    chat_key: str = ""                 # 對話紀錄代碼：換電腦接續時用來取得先前的對話
    allow_files: bool = False          # 律師在面板上開啟「允許整理檔案」（刪除、搬移、改名）


@app.post("/api/case/{cid}/claude")
def ask_claude(cid: str, body: AskIn):
    c = _case(cid)
    ctx = claude_runner.case_context(CFG, c, allow_files=body.allow_files)

    def finish():
        scanner.refresh_one(CFG, cid)
        queued = gcal.enqueue_case(CFG, cid)          # Claude 可能改了庭期或待辦
        return {"type": "casedesk_done", "at": time.time(), "gcal_queued": queued}

    prompt, sid = _continue_on_this_machine(body.prompt, body.session_id, body.chat_key)
    it = claude_runner.stream(CFG, ctx, prompt, sid, body.model, body.effort)
    return _ndjson(it, finish)


_END = object()


def _ndjson(it, finish, first: dict | None = None) -> StreamingResponse:
    """把 Claude 的事件串流成 NDJSON。

    用 async 產生器包住：瀏覽器重新整理或關掉分頁時，Starlette 會取消這個產生器，
    finally 就能把還在跑的 Claude 停掉，並照樣做收尾（重新整理清單、送去同步日曆）。
    sync 產生器做不到——斷線時它卡在背景執行緒裡，根本不會被通知。"""
    async def agen():
        run_id, finished = None, False
        try:
            if first:
                yield json.dumps(first, ensure_ascii=False) + "\n"
            while True:
                ev = await anyio.to_thread.run_sync(next, it, _END, abandon_on_cancel=True)
                if ev is _END:
                    break
                if ev.get("type") == "run":
                    run_id = ev["run_id"]
                yield json.dumps(ev, ensure_ascii=False) + "\n"
            finished = True
            yield json.dumps(finish(), ensure_ascii=False) + "\n"
        finally:
            if not finished:
                if run_id:
                    claude_runner.stop(run_id)
                try:
                    finish()
                except Exception:
                    pass

    return StreamingResponse(agen(), media_type="application/x-ndjson")


class MultiAskIn(AskIn):
    scope: str = "all"                 # all：全部案件；list：前端目前清單
    case_ids: list[str] = []
    label: str = ""


def _card_mtimes(cases: list[dict]) -> dict:
    out = {}
    for c in cases:
        p = Path(c["path"]) / CFG["card_name"]
        out[c["id"]] = p.stat().st_mtime if p.exists() else 0
    return out


@app.post("/api/claude/multi")
def ask_claude_multi(body: MultiAskIn):
    """多案模式：Claude 在案件根目錄工作，範圍是全部案件或目前清單。"""
    allc = scanner.scan(CFG)
    if body.scope == "list":
        cases = [allc[i] for i in body.case_ids if i in allc]
        label = body.label or "目前清單"
    else:
        cases = sorted(allc.values(), key=lambda c: -c["mtime"])
        label = "全部案件"
    if not cases:
        raise HTTPException(400, "範圍內沒有案件")
    ctx = claude_runner.multi_context(CFG, cases, label, gcal.LOCAL_DIR / "claude",
                                      allow_files=body.allow_files)
    before = _card_mtimes(cases)

    def finish():
        # 找出 Claude 動過的案件卡：重掃、並送去同步日曆
        after = _card_mtimes(cases)
        changed = [cid for cid in after if after[cid] != before.get(cid)]
        scanner.scan(CFG, force=True)
        queued = [cid for cid in changed if gcal.enqueue_case(CFG, cid)]
        return {"type": "casedesk_done", "at": time.time(), "changed": changed,
                "gcal_queued": bool(queued)}

    prompt, sid = _continue_on_this_machine(body.prompt, body.session_id, body.chat_key)
    it = claude_runner.stream(CFG, ctx, prompt, sid, body.model, body.effort)
    return _ndjson(it, finish, first={"type": "casedesk_scope", "n": len(cases), "label": label})


@app.post("/api/open-root")
def open_under_root(body: PathIn):
    """多案模式下，Claude 回答裡的路徑是相對於根目錄的，從這裡開啟。"""
    base = Path(CFG["root"]).resolve()
    p = (base / body.rel).resolve()
    if p != base and base not in p.parents:
        raise HTTPException(400, "路徑不在案件根目錄內")
    if not p.exists():
        raise HTTPException(404, "檔案不存在：%s" % body.rel)
    open_with_default_app(p)
    return {"ok": True}


@app.get("/api/claude/capabilities")
def claude_capabilities():
    """上次探測到的可用 skill／連接器（快取）。"""
    return claude_runner.load_capabilities() or {"at": 0}


@app.post("/api/claude/capabilities/refresh")
def claude_capabilities_refresh():
    """重新探測（約十幾秒）：順便確認命令列 Claude 的登入是否有效。"""
    caps = claude_runner.probe_capabilities(CFG, CFG["root"])
    diag.record_capabilities(CFG)
    return caps


CAPS_MAX_AGE = 3 * 86400               # 可用工具清單超過三天就在背景重查


def _probe_on_start():
    """這台電腦還沒查過、上次查失敗（例如當時 Claude 還沒登入）、或已經超過三天，就在背景重查一次。
    清單存在各台電腦本機，不會跟著雲端硬碟同步，所以每台都要自己查。"""
    caps = claude_runner.load_capabilities()
    if not caps or not caps.get("ok") or time.time() - float(caps.get("at") or 0) > CAPS_MAX_AGE:
        try:
            claude_runner.probe_capabilities(CFG, CFG["root"])
        except Exception:
            pass
    diag.record_capabilities(CFG)


@app.on_event("startup")
def _startup():
    threading.Thread(target=_probe_on_start, daemon=True).start()
    threading.Thread(target=holidays.refresh_if_missing, daemon=True).start()
    inbox.start_background(CFG, lambda: scanner.scan(CFG))


# ------------------------------------------------------------------ 新收文書提醒

class InboxAckIn(BaseModel):
    files: list[str] | None = None     # 不給＝這件全部標為看過


@app.get("/api/inbox/counts")
def inbox_counts():
    return {"at": inbox.scanned_at(), "counts": inbox.counts()}


@app.post("/api/case/{cid}/inbox/ack")
def inbox_ack(cid: str, body: InboxAckIn):
    c = _case(cid)
    left = inbox.ack(c, CFG, body.files)
    return {"left": left, "inbox": inbox.new_files(c, CFG)}


# ------------------------------------------------------------------ 法定期間：假日資料

@app.get("/api/holidays")
def get_holidays():
    return holidays.load()


@app.post("/api/holidays/refresh")
def refresh_holidays():
    return holidays.refresh()


class ExtraDaysIn(BaseModel):
    extra: dict


@app.put("/api/holidays/extra")
def put_extra_days(body: ExtraDaysIn):
    return holidays.save_extra(body.extra)


# ------------------------------------------------------------------ 利益衝突檢查

class ConflictIn(BaseModel):
    names: list[str]
    exclude: str = ""                  # 檢查某件案件自己時，排除它本身


@app.post("/api/conflict")
def conflict_check(body: ConflictIn):
    names = [n for x in body.names for n in conflict.split_names(x)][:30]
    return {"results": conflict.check(names, list(scanner.scan(CFG).values()), CFG, body.exclude)}


@app.post("/api/claude/stop/{run_id}")
def stop_claude(run_id: str):
    return {"ok": claude_runner.stop(run_id)}


# ------------------------------------------------------------------ 前端

@app.get("/")
def shell():
    """分頁外殼：每個分頁是一個 /app。"""
    return FileResponse(settings.FRONTEND / "shell.html")


@app.get("/app")
def index():
    return FileResponse(settings.FRONTEND / "index.html")


# ------------------------------------------------------------------ 視窗（原生視窗模式）
#
# 以原生視窗執行時，run.py 會把「開新視窗」的函式掛在 WINDOW_HOOK。
# 一般瀏覽器模式沒有掛，前端就改用瀏覽器自己的新視窗。

WINDOW_HOOK = {"new": None, "quit": None}


@app.post("/api/app/handover")
def app_handover():
    """新啟動的程式要用原生視窗開，但這台已經有一個瀏覽器模式的伺服器在跑（關掉瀏覽器它也不會結束）：
    請這個舊的結束，由新的接手。原生視窗模式不交接（直接開新視窗即可）。"""
    if WINDOW_HOOK["new"] or not WINDOW_HOOK["quit"]:
        return {"ok": False}
    threading.Timer(0.5, WINDOW_HOOK["quit"]).start()
    return {"ok": True}


class WindowIn(BaseModel):
    params: dict = {}


@app.post("/api/open-browser")
def open_browser(body: WindowIn):
    """用電腦預設的瀏覽器開啟（例如要列印、或想用瀏覽器的分頁）。"""
    import urllib.parse, webbrowser
    params = {k: str(v) for k, v in (body.params or {}).items() if k in ("case", "view")}
    webbrowser.open("http://%s:%d/%s" % (CFG["host"], CFG["port"],
                                          ("?" + urllib.parse.urlencode(params)) if params else ""))
    return {"ok": True}


@app.post("/api/window/new")
def window_new(body: WindowIn):
    if not WINDOW_HOOK["new"]:
        return {"ok": False}
    params = {k: str(v) for k, v in (body.params or {}).items() if k in ("case", "view")}
    WINDOW_HOOK["new"](params)
    return {"ok": True}


app.mount("/static", StaticFiles(directory=str(settings.FRONTEND)), name="static")
