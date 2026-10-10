# -*- coding: utf-8 -*-
"""Google 日曆單向同步：案件卡 → 日曆。

設計
----
* 案件卡是正本，日曆只是投影。要改庭期請在系統（或案件卡）改，直接改日曆會被下次同步蓋掉。
* 每筆庭期／有期限的待辦，在案件卡裡就帶著自己的事件 id（`<!--gcal:…-->`）。
  同步一律用這個 id 去 update，不存在才 insert——所以重推不會重複，換電腦也不會。
* 事件掛上 extendedProperties：casedesk=1、casedesk_case=案件、casedesk_hash=內容雜湊。
  內容沒變就跳過；從案件卡刪掉的項目，靠這些標記找出來從日曆刪除。
  不需要任何本機紀錄檔。
* 安全閥：找不到案件根目錄、或一次要刪超過一半的事件時，不刪，只回報。

授權
----
data/credentials.json 是 OAuth「桌面應用程式」用戶端（沿用 casemgr 那一份）。
token 存在 %LOCALAPPDATA%\\casedesk\\token.json——那是日曆的鑰匙，不放進會同步的資料夾。
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
import queue
import re
import threading
import time
from pathlib import Path

from . import card, scanner, settings, titles

SCOPES = ["https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.readonly"]
CRED_PATH = settings.ROOT / "data" / "credentials.json"
LOCAL_DIR = settings.LOCAL_DIR
TOKEN_PATH = LOCAL_DIR / "token.json"

_state = {"auth_running": False, "auth_error": "", "last": {}, "all": None, "busy": ""}
_q: "queue.Queue[tuple]" = queue.Queue()
_worker: threading.Thread | None = None


# ------------------------------------------------------------------ 授權

def _creds():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    if not TOKEN_PATH.exists():
        return None
    c = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if c.expired and c.refresh_token:
        c.refresh(Request())          # 失敗會丟 RefreshError，讓上層顯示原因
        TOKEN_PATH.write_text(c.to_json(), encoding="utf-8")
    return c if c.valid else None


def service():
    from googleapiclient.discovery import build
    c = _creds()
    if not c:
        raise RuntimeError("尚未連結 Google 日曆")
    return build("calendar", "v3", credentials=c, cache_discovery=False)


def status(cfg: dict, deep: bool = False) -> dict:
    g = cfg.get("google", {})
    st = {"enabled": bool(g.get("enabled")), "auto_sync": bool(g.get("auto_sync")),
          "credentials_file": CRED_PATH.exists(), "connected": False, "error": "",
          "auth_running": _state["auth_running"], "busy": _state["busy"],
          "calendar_hearing": g.get("calendar_hearing", ""),
          "calendar_deadline": g.get("calendar_deadline", ""),
          "last_all": _state["all"]}
    if _state["auth_error"]:
        st["error"] = _state["auth_error"]
    if not CRED_PATH.exists():
        st["error"] = "缺少 data/credentials.json（Google OAuth 桌面用戶端）"
        return st
    if not TOKEN_PATH.exists():
        return st
    try:
        c = _creds()
        st["connected"] = bool(c)
        if deep and c:
            items = service().calendarList().list().execute().get("items", [])
            st["calendars"] = [{"id": i["id"], "name": i.get("summaryOverride") or i.get("summary", ""),
                                "primary": bool(i.get("primary")),
                                "writable": i.get("accessRole") in ("owner", "writer")}
                               for i in items]
    except Exception as e:
        msg = str(e)
        if "invalid_grant" in msg:
            msg = "Google 授權已失效（可能是授權過期或被撤銷），請重新連結。"
        st["error"], st["connected"] = msg, False
    return st


def start_auth() -> None:
    """在背景開瀏覽器讓你本人完成 Google 授權。"""
    if _state["auth_running"]:
        return

    def run():
        _state.update(auth_running=True, auth_error="")
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(str(CRED_PATH), SCOPES)
            creds = flow.run_local_server(
                port=0, prompt="consent", open_browser=True, timeout_seconds=600,
                authorization_prompt_message="",
                success_message="授權完成，可以關掉這個分頁回到案件管理系統。")
            LOCAL_DIR.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        except Exception as e:
            _state["auth_error"] = "授權沒有完成：%s" % e
        finally:
            _state["auth_running"] = False

    threading.Thread(target=run, daemon=True).start()


def disconnect() -> None:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()


# ------------------------------------------------------------------ 事件內容

PAREN_RE = re.compile(r"[（(]([^（）()]+)[）)]\s*$")


def _base(case: dict, d: dict, kind: str) -> dict:
    m = d["meta"]
    lines = ["案件：%s" % case["name"]]
    for k in ("案號", "法院", "股別", "對造"):
        if m.get(k):
            lines.append("%s：%s" % (k, m[k]))
    lines += ["資料夾：%s" % case["path"], "",
              "由案件管理系統同步。請在系統或案件卡修改，直接改這裡會被下次同步覆蓋。"]
    return {"description": "\n".join(lines), "status": "confirmed",
            "extendedProperties": {"private": {"casedesk": "1", "casedesk_case": case["id"],
                                               "casedesk_kind": kind}}}


ATTEND_RE = re.compile(r"出席|出庭|到庭|赴.{0,6}(庭|院)")      # 不含「開庭」：「整理開庭筆錄」不是去開庭
FILING_RE = re.compile(r"狀|陳報|提出|繳|聲請|寄|送|補正|回報|閱卷|聯絡|通知")


def is_attendance_dup(t: dict, hearing_days: set) -> bool:
    """待辦是「去開某一場庭」、而同一天已經有那場庭期 → 視為重複。
    同一天到期的書狀、陳報等期限不算（那是另一件事，要留著提醒）。"""
    text = t.get("text") or ""
    return t.get("due") in hearing_days and bool(ATTEND_RE.search(text)) and not FILING_RE.search(text)


def build_events(case: dict, d: dict, cfg: dict) -> list[tuple[str, str, dict]]:
    """回傳 [(日曆 id, 事件 id, 事件內容)]。"""
    g = cfg.get("google", {})
    tz = g.get("timezone", "Asia/Taipei")
    subs = d.get("subcases") or []
    out = []
    cal_h = g.get("calendar_hearing") or "primary"
    cal_d = g.get("calendar_deadline") or cal_h
    mins = int(g.get("hearing_minutes", 60))

    for h in d["hearings"]:
        if not h["gcal"]:
            continue
        ev = _base(case, d, "hearing")
        opp = d["meta"].get("對造", "")
        ev["summary"] = titles.event_title(case, subs, h["text"], "開庭", opponent=opp)
        # 地點取事由最後一個括號（法庭）；「（對某某）」是當事人資訊不是地點，先拿掉。
        # 子案的庭可能在別的法院，不套總案的「法院」欄。
        pm = PAREN_RE.search(titles.strip_against(h["text"] or "", opp).strip())
        court = "" if titles.split_sub(h["text"], subs) else d["meta"].get("法院", "")
        ev["location"] = " ".join(x for x in (court, pm.group(1) if pm else "") if x)
        if h["time"]:
            st = dt.datetime.fromisoformat("%sT%s" % (h["date"], h["time"]))
            ev["start"] = {"dateTime": st.isoformat(), "timeZone": tz}
            ev["end"] = {"dateTime": (st + dt.timedelta(minutes=mins)).isoformat(), "timeZone": tz}
        else:
            day = dt.date.fromisoformat(h["date"])
            ev["start"] = {"date": day.isoformat()}
            ev["end"] = {"date": (day + dt.timedelta(days=1)).isoformat()}
        ev["reminders"] = {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": m} for m in g.get("reminders_hearing", [1440, 120])]}
        out.append((cal_h, h["gcal"], ev))

    hearing_days = {h["date"] for h in d["hearings"]}
    for t in d["todos"]:
        if not t["due"] or not t["gcal"]:
            continue
        if is_attendance_dup(t, hearing_days):
            continue                       # 「出席某某庭」跟同一天的庭期重複，日曆上只留庭期
        ev = _base(case, d, "deadline")
        ev["summary"] = titles.event_title(case, subs, t["text"], "期限", done=t["done"],
                                           opponent=d["meta"].get("對造", ""))
        day = dt.date.fromisoformat(t["due"])
        ev["start"] = {"date": day.isoformat()}
        ev["end"] = {"date": (day + dt.timedelta(days=1)).isoformat()}
        ev["transparency"] = "transparent"
        ev["reminders"] = {"useDefault": False, "overrides": [] if t["done"] else [
            {"method": "popup", "minutes": m} for m in g.get("reminders_deadline", [3780, 900])]}
        out.append((cal_d, t["gcal"], ev))

    for _, _, ev in out:
        h = hashlib.sha1(json.dumps(ev, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        ev["extendedProperties"]["private"]["casedesk_hash"] = h
    return out


# ------------------------------------------------------------------ 同步

def _list(svc, cal: str, case_id: str | None) -> dict[str, dict]:
    """列出某日曆裡由本系統建立的事件 {id: {hash, case, cal}}。"""
    out, token = {}, None
    flt = "casedesk_case=%s" % case_id if case_id else "casedesk=1"
    while True:
        r = svc.events().list(calendarId=cal, privateExtendedProperty=flt, maxResults=2500,
                              showDeleted=False, pageToken=token,
                              fields="nextPageToken,items(id,status,extendedProperties)").execute()
        for e in r.get("items", []):
            p = (e.get("extendedProperties") or {}).get("private") or {}
            out[e["id"]] = {"hash": p.get("casedesk_hash"), "case": p.get("casedesk_case"), "cal": cal}
        token = r.get("nextPageToken")
        if not token:
            return out


def _upsert(svc, cal: str, eid: str, ev: dict, exists: bool) -> None:
    from googleapiclient.errors import HttpError
    if exists:
        svc.events().update(calendarId=cal, eventId=eid, body=ev).execute()
        return
    try:
        svc.events().insert(calendarId=cal, body={**ev, "id": eid}).execute()
    except HttpError as e:
        if e.resp.status != 409:      # 409：曾經建立過（例如在日曆上被刪掉），改用 update 復原
            raise
        svc.events().update(calendarId=cal, eventId=eid, body=ev).execute()


def _calendars(cfg: dict) -> list[str]:
    """要掃描的日曆：目前寫入的兩個，加上以前用過的（換日曆後把舊事件搬走）。"""
    g = cfg.get("google", {})
    cals = [g.get("calendar_hearing") or "primary", g.get("calendar_deadline") or g.get("calendar_hearing") or "primary"]
    return list(dict.fromkeys(cals + list(g.get("previous_calendars", []))))


def _title(c: dict) -> str:
    return " ".join(x for x in (c["code"], c["client"], c["cause"]) if x)


def sync_case(cfg: dict, case: dict, svc=None) -> dict:
    svc = svc or service()
    res = {"pushed": 0, "skipped": 0, "deleted": 0, "at": time.time(), "error": ""}
    d = card.ensure_ids(Path(case["path"]) / cfg["card_name"], _title(case))
    if not d:   # 讀不到案件卡（可能雲端硬碟還在同步）——寧可不動，也不要把日曆清空
        res["error"] = "讀不到案件卡，略過"
        return res
    wanted = build_events(case, d, cfg)
    have = {}
    for cal in _calendars(cfg):
        have.update(_list(svc, cal, case["id"]))
    for cal, eid, ev in wanted:
        cur = have.get(eid)
        if cur and cur["hash"] == ev["extendedProperties"]["private"]["casedesk_hash"] and cur["cal"] == cal:
            res["skipped"] += 1
            continue
        if cur and cur["cal"] != cal:
            svc.events().delete(calendarId=cur["cal"], eventId=eid).execute()
            cur = None
        _upsert(svc, cal, eid, ev, exists=bool(cur))
        res["pushed"] += 1
    keep = {eid for _, eid, _ in wanted}
    for eid, info in have.items():
        if eid not in keep:
            svc.events().delete(calendarId=info["cal"], eventId=eid).execute()
            res["deleted"] += 1
    return res


def sync_all(cfg: dict, svc=None) -> dict:
    svc = svc or service()
    res = {"cases": 0, "pushed": 0, "skipped": 0, "deleted": 0, "held": 0,
           "errors": [], "at": time.time()}
    if not Path(cfg["root"]).exists():
        res["errors"].append("找不到案件根目錄，為安全起見這次不同步。")
        return res
    cases = [c for c in scanner.scan(cfg, force=True).values() if c["has_card"]]
    have = {}
    for cal in _calendars(cfg):
        have.update(_list(svc, cal, None))
    keep = set()
    for c in cases:
        try:
            d = card.ensure_ids(Path(c["path"]) / cfg["card_name"], _title(c))
            events = build_events(c, d, cfg) if d else None
        except Exception as e:           # 一件出錯不拖累其他案件
            d, events = None, None
            res["errors"].append("%s：%s" % (c["name"], e))
        if events is None:
            # 讀不到或解析失敗：這件既有的日曆事件一律保留，免得被當成孤兒刪掉
            keep.update(eid for eid, i in have.items() if i["case"] == c["id"])
            continue
        res["cases"] += 1
        for cal, eid, ev in events:
            keep.add(eid)
            cur = have.get(eid)
            try:
                if cur and cur["hash"] == ev["extendedProperties"]["private"]["casedesk_hash"] and cur["cal"] == cal:
                    res["skipped"] += 1
                    continue
                if cur and cur["cal"] != cal:
                    svc.events().delete(calendarId=cur["cal"], eventId=eid).execute()
                    cur = None
                _upsert(svc, cal, eid, ev, exists=bool(cur))
                res["pushed"] += 1
            except Exception as e:
                res["errors"].append("%s：%s" % (c["name"], e))
    orphans = [(eid, i) for eid, i in have.items() if eid not in keep]
    if orphans and len(orphans) > 5 and len(orphans) > len(have) / 2:
        res["held"] = len(orphans)
        res["errors"].append("有 %d 筆日曆事件在案件卡裡找不到，數量異常，這次先不刪除。"
                             "請確認雲端硬碟是否同步完成。" % len(orphans))
    else:
        for eid, info in orphans:
            try:
                svc.events().delete(calendarId=info["cal"], eventId=eid).execute()
                res["deleted"] += 1
            except Exception as e:
                res["errors"].append("刪除 %s 失敗：%s" % (eid, e))
    return res


# ------------------------------------------------------------------ 背景佇列

def _run_worker():
    while True:
        kind, arg = _q.get()
        cfg = settings.load()
        try:
            if kind == "all":
                _state["busy"] = "全部同步中"
                _state["all"] = sync_all(cfg)
            else:
                c = scanner.get(cfg, arg)
                if c:
                    _state["busy"] = "同步 %s" % c["code"]
                    _state["last"][arg] = sync_case(cfg, c)
                else:
                    _state["last"][arg] = {"error": "找不到這件案件（資料夾可能已改名）", "at": time.time()}
        except Exception as e:
            msg = str(e)
            if "invalid_grant" in msg:
                msg = "Google 授權已失效，請到日曆設定重新連結。"
            if kind == "all":
                _state["all"] = {"errors": [msg], "at": time.time()}
            else:
                _state["last"][arg] = {"error": msg, "at": time.time()}
        finally:
            _state["busy"] = ""


def _ensure_worker():
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run_worker, daemon=True)
        _worker.start()


def ready(cfg: dict) -> bool:
    return bool(cfg.get("google", {}).get("enabled")) and TOKEN_PATH.exists()


def enqueue_case(cfg: dict, case_id: str, manual: bool = False) -> bool:
    if not ready(cfg) or not (manual or cfg["google"].get("auto_sync")):
        return False
    _ensure_worker()
    _state["last"].pop(case_id, None)
    _q.put(("case", case_id))
    return True


def enqueue_all(cfg: dict) -> bool:
    if not ready(cfg):
        return False
    _ensure_worker()
    _state["all"] = None
    _q.put(("all", None))
    return True


def case_status(case_id: str) -> dict | None:
    return _state["last"].get(case_id)
