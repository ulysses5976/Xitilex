# -*- coding: utf-8 -*-
"""案件卡（_案件卡.md）的讀寫。

案件卡放在每個案件資料夾裡，是案件狀態、庭期與待辦的唯一正本：
  * 你在系統上改 → 寫回這個檔
  * Claude 被要求更新 → 也是直接改這個檔
  * 用任何 Markdown 軟體（Obsidian、記事本）打開都看得懂

格式：
    ---
    案件狀態: 待開庭
    案號: 115年度勞訴字第88號
    下次期日: 2026-10-28 14:30 言詞辯論（第12法庭）   ← 由「庭期」段自動算出
    ...
    ---

    # LB010 王小明 確認僱傭關係存在

    ## 庭期
    - 2026-10-28 14:30 言詞辯論（第12法庭） <!--gcal:cd0f…-->

    ## 待辦事項
    - [ ] 2026-10-15 提出準備三狀 <!--gcal:cd3a…-->
    - [x] 閱卷

    ## 案件摘要
    ……（其餘段落原樣保留，系統不動）

`<!--gcal:…-->` 是 Google 日曆事件編號：在系統存檔時就先配好，同步時用它
update，所以重推不會重複、換電腦也不會重複。Obsidian 閱讀模式不會顯示它。

寫回時只重產 frontmatter、「庭期」與「待辦事項」兩段，其他段落逐字保留。
只有在第一次編輯（或 Claude 建立）時才會產生檔案，掃描本身從不寫入。
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

FIELDS = ["案件狀態", "案件類型", "案號", "法院", "股別", "對造", "下次期日", "委任日", "釘選"]
TODO_HEADING = "待辦事項"
HEARING_HEADING = "庭期"
MANAGED = (HEARING_HEADING, TODO_HEADING)
SUBCASE_HEADING = "子案"
SUMMARY_HEADING = "案件摘要"               # 案件頁上可以直接打字的那一段
SUBCASE_RE = re.compile(r"^[-*]\s+([A-Z]{1,3}\d{2,5}[A-Z]?)\s+(.+?)\s*$")

GCAL_RE = re.compile(r"\s*<!--\s*gcal:([0-9a-v]{5,64})\s*-->\s*$")
# 只認頂層（不縮排）的項目；縮排的是子項目，原樣掛在上一個項目底下
TODO_RE = re.compile(r"^[-*] \[( |x|X)\]\s*(?:(\d{4}-\d{2}-\d{2})\s+)?(.*)$")
HEARING_RE = re.compile(
    r"^[-*]\s+(?:\[.\]\s*)?(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?\s*(.*)$")
DATE_HEAD_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?\s*(.*)$")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def lock(path: Path) -> threading.Lock:
    """同一張案件卡的讀改寫要排隊（存檔與日曆同步可能同時發生）。"""
    with _locks_guard:
        return _locks.setdefault(str(path).lower(), threading.Lock())


def new_gcal_id() -> str:
    # Google 日曆自訂事件 id 只能用 base32hex（0-9、a-v），長度 5–1024
    return "cd" + "".join(secrets.choice("0123456789abcdefghijklmnopqrstuv") for _ in range(24))


def _valid_date(s: str) -> bool:
    try:
        dt.date.fromisoformat(s)
        return True
    except (TypeError, ValueError):
        return False


def _norm_time(t: str) -> str:
    """'9:05' → '09:05'；不合法的時間回傳 None。"""
    if not t:
        return ""
    try:
        h, m = t.split(":")
        return dt.time(int(h), int(m)).strftime("%H:%M")
    except (ValueError, TypeError):
        return None


def _split_frontmatter(text: str) -> tuple[dict, str, list]:
    """回傳 (meta, 本文, 原始區塊)。

    原始區塊是 [(key 或 None, [原始行…])]：縮排行、清單行（Obsidian 的 tags 清單）
    都掛在上一個 key 底下，寫回時本系統不管的 key 一律原樣輸出，不會被壓扁。"""
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text, []
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text, []
    meta, blocks = {}, []
    for line in text[3:end].split("\n")[1:]:
        line = line.rstrip("\r")
        is_key = line and not line[0].isspace() and not line.startswith(("#", "- ")) and ":" in line
        if not is_key:
            if blocks:
                blocks[-1][1].append(line)
            elif line.strip():
                blocks.append((None, [line]))
            continue
        k, v = line.split(":", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            try:
                v = json.loads(v) if v[0] == '"' else v[1:-1]
            except ValueError:
                v = v[1:-1]
        meta[k] = v
        blocks.append((k, [line]))
    body = text[end + 4:]
    body = body[body.find("\n") + 1:] if "\n" in body else ""
    return meta, body, blocks


def _sections(body: str) -> tuple[str, list[list]]:
    """把本文切成 (開頭, [[標題, [行…]], ...])，只認 ## 二級標題。"""
    pre, secs, cur = [], [], None
    for line in body.split("\n"):
        line = line.rstrip("\r")
        if line.startswith("## "):
            cur = [line[3:].strip(), []]
            secs.append(cur)
        elif cur is None:
            pre.append(line)
        else:
            cur[1].append(line)
    return "\n".join(pre), secs


def _take_gcal(s: str) -> tuple[str, str]:
    m = GCAL_RE.search(s)
    return (s[:m.start()].rstrip(), m.group(1)) if m else (s.strip(), "")


def _parse_todo(line: str) -> dict | None:
    m = TODO_RE.match(line)
    if not m:
        return None
    t, gid = _take_gcal(m.group(3))
    due = m.group(2) or ""
    if due and not _valid_date(due):            # 2026-02-30 這種：當成文字保留，不當期限
        t, due = (due + " " + t).strip(), ""
    return {"done": m.group(1) != " ", "due": due, "text": t, "gcal": gid, "extra": []}


def _parse_hearing(line: str) -> dict | None:
    m = HEARING_RE.match(line)
    if not m or not _valid_date(m.group(1)):
        return None                              # 不是合法日期 → 不算庭期，原樣保留
    t, gid = _take_gcal(m.group(3))
    tm = _norm_time(m.group(2))
    if tm is None:                               # 25:99 這種：時間併回事由
        t, tm = (m.group(2) + " " + t).strip(), ""
    return {"date": m.group(1), "time": tm, "text": t, "gcal": gid, "extra": []}


def _parse_section(lines: list[str], parser) -> tuple[list[dict], list[str]]:
    """逐行解析受管理的段落。認得的行變成項目；認不得的（子項目、說明文字）
    掛在上一個項目底下（extra），第一個項目之前的放進 lead，寫回時都原樣保留。"""
    items, lead, cur = [], [], None
    for line in lines:
        it = parser(line)
        if it:
            items.append(it)
            cur = it
        elif line.strip():
            (cur["extra"] if cur else lead).append(line)
    return items, lead


def next_hearing(hearings: list[dict]) -> dict | None:
    today = dt.date.today().isoformat()
    up = sorted((h for h in hearings if h["date"] >= today),
                key=lambda h: (h["date"], h["time"] or "99:99"))
    return up[0] if up else None


def hearing_label(h: dict | None) -> str:
    if not h:
        return ""
    return " ".join(x for x in (h["date"], h["time"], h["text"]) if x)


def parse(text: str) -> dict:
    meta, body, _ = _split_frontmatter(text)
    pre, secs = _sections(body)
    todos, hearings, lead = [], [], {TODO_HEADING: [], HEARING_HEADING: []}
    for h, lines in secs:                        # 同名段落出現兩次也合併成一份
        if h == TODO_HEADING:
            items, ld = _parse_section(lines, _parse_todo)
            todos += items
            lead[h] += ld
        elif h == HEARING_HEADING:
            items, ld = _parse_section(lines, _parse_hearing)
            hearings += items
            lead[h] += ld

    # 舊式卡片（還沒有「## 庭期」段）只在 frontmatter 寫了下次期日 → 視為一筆庭期，
    # 下次存檔時正式寫進庭期段。已經有庭期段的卡片不做這件事，否則改期或刪掉的
    # 庭期會因為 frontmatter 還留著舊日期而「復活」。
    if not any(h == HEARING_HEADING for h, _ in secs):
        m = DATE_HEAD_RE.match(str(meta.get("下次期日", "")).strip())
        if m and _valid_date(m.group(1)):
            tm = _norm_time(m.group(2)) or ""
            hearings.append({"date": m.group(1), "time": tm, "text": m.group(3).strip(),
                             "gcal": "", "extra": []})
    hearings.sort(key=lambda h: (h["date"], h["time"] or "99:99"))

    # 「## 子案」：一件案子底下有多個訴訟（例如集團客戶 SP001 底下的多件訴訟）。每行「- 子案號 對造名稱」。
    # 這段本系統只讀不寫（寫回時原樣保留），由律師或 Claude 維護。
    subcases = []
    for h, lines in secs:
        if h == SUBCASE_HEADING:
            for line in lines:
                m = SUBCASE_RE.match(line)
                if m:
                    subcases.append({"code": m.group(1), "name": m.group(2).strip()})

    notes = [{"heading": h, "content": "\n".join(c).strip("\n")}
             for h, c in secs if h not in MANAGED and h != SUBCASE_HEADING]
    return {"meta": meta, "todos": todos, "hearings": hearings, "notes": notes, "lead": lead,
            "subcases": subcases,
            "next": hearing_label(next_hearing(hearings)),
            "title": next((l[2:].strip() for l in pre.splitlines() if l.startswith("# ")), "")}


def section(d: dict | None, heading: str) -> str:
    """取出某個自由段落（例如「案件摘要」）的內容；同名段落有好幾個就接起來。"""
    if not d:
        return ""
    return "\n\n".join(n["content"] for n in d.get("notes", []) if n["heading"] == heading).strip("\n")


def clean_section_text(text: str) -> str:
    """使用者打的段落內容：統一換行、去掉行尾空白；一級／二級標題降成三級，
    否則下次讀檔時會被當成新段落，把摘要切斷。"""
    lines = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.rstrip()
        if re.match(r"^#{1,2}\s", line):
            line = "### " + line.lstrip("#").lstrip()
        lines.append(line)
    return "\n".join(lines).strip("\n")


def read(path: Path) -> dict | None:
    if not path.exists():
        return None
    raw = _retry(path.read_bytes)
    try:
        d = parse(raw.decode("utf-8"))
    except UnicodeDecodeError:
        d = parse(raw.decode("utf-8", errors="replace"))
    d["mtime"] = path.stat().st_mtime
    return d


def _yaml_value(v: str) -> str:
    v = str(v or "").replace("\n", " ").strip()
    if v == "" or re.search(r"(: |#|^[\[\]{}&*!|>'\"%@`-])", v):
        return json.dumps(v, ensure_ascii=False) if v else ""
    return v


def _gcal_tail(item: dict) -> str:
    return " <!--gcal:%s-->" % item["gcal"] if item.get("gcal") else ""


def _todo_line(t: dict) -> str:
    box = "x" if t.get("done") else " "
    due = (t.get("due") or "").strip()
    text = (t.get("text") or "").replace("\n", " ").strip()
    return "- [%s] %s%s%s" % (box, (due + " ") if due else "", text, _gcal_tail(t))


def _hearing_line(h: dict) -> str:
    head = " ".join(x for x in (h.get("date", ""), h.get("time", "")) if x)
    text = (h.get("text") or "").replace("\n", " ").strip()
    return "- %s%s%s" % (head, (" " + text) if text else "", _gcal_tail(h))


def assign_ids(todos: list[dict], hearings: list[dict]) -> bool:
    """有日期的項目都配一個日曆事件 id。回傳是否有新配的。"""
    changed = False
    for it in [t for t in todos if t.get("due")] + hearings:
        if not it.get("gcal"):
            it["gcal"] = new_gcal_id()
            changed = True
    return changed


def _clean_todos(todos: list[dict]) -> list[dict]:
    out = []
    for t in todos:
        t = dict(t)
        t["text"] = (t.get("text") or "").replace("\n", " ").strip()
        due = (t.get("due") or "").strip()
        if due and not _valid_date(due):
            t["text"], due = (due + " " + t["text"]).strip(), ""
        t["due"] = due
        if t["text"]:
            out.append(t)
    return out


def _clean_hearings(hearings: list[dict]) -> list[dict]:
    out = []
    for h in hearings:
        h = dict(h)
        if not _valid_date((h.get("date") or "").strip()):
            continue
        h["date"] = h["date"].strip()
        tm = _norm_time((h.get("time") or "").strip())
        h["time"] = tm or ""
        h["text"] = (h.get("text") or "").replace("\n", " ").strip()
        out.append(h)
    out.sort(key=lambda h: (h["date"], h["time"] or "99:99"))
    return out


def _keep_extras(items: list[dict], old_items: list[dict]) -> None:
    """前端送回的項目若沒帶 extra（例如舊版畫面），從檔案裡同一筆（依事件 id，
    其次依內容）補回來，子項目才不會在存檔時消失。"""
    by_id = {o["gcal"]: o for o in old_items if o.get("gcal")}
    by_txt = {(o.get("text"), o.get("due") or o.get("date")): o for o in old_items}
    for it in items:
        if it.get("extra"):
            continue
        o = by_id.get(it.get("gcal")) or by_txt.get((it.get("text"), it.get("due") or it.get("date")))
        it["extra"] = list(o["extra"]) if o else []


def write(path: Path, meta: dict, todos: list[dict], hearings: list[dict] | None,
          default_title: str, sections: dict[str, str] | None = None) -> None:
    """寫回案件卡。hearings 傳 None 表示沿用檔案裡現有的庭期。
    sections 給 {段落標題: 新內容} 時，改寫（或新增）那些自由段落，例如「案件摘要」。

    只重產本系統管理的 frontmatter 欄位，以及「庭期」「待辦事項」兩段的項目行；
    其他 frontmatter（含清單）、其他段落、段落裡認不得的行，一律原樣保留。"""
    blocks, body, old = [], "", None
    if path.exists():
        text = _retry(lambda: path.read_text(encoding="utf-8"))
        _, body, blocks = _split_frontmatter(text)
        old = parse(text)
    hearings = _clean_hearings(old["hearings"] if hearings is None and old else (hearings or []))
    todos = _clean_todos(todos)
    if old:
        _keep_extras(todos, old["todos"])
        _keep_extras(hearings, old["hearings"])
    assign_ids(todos, hearings)

    pre, secs = _sections(body)
    if not pre.strip():
        pre = "\n# %s\n" % default_title

    # ---- frontmatter：原有順序保留；本系統管理的欄位重產，其他原樣
    managed_keys = FIELDS + ["更新"]
    values = {k: v for k, v in meta.items() if k in FIELDS}
    values["下次期日"] = hearing_label(next_hearing(hearings))
    values["更新"] = time.strftime("%Y-%m-%d %H:%M")
    old_vals = {k: (ls[0].split(":", 1)[1].strip() if k else "") for k, ls in blocks}
    fm, done_keys = [], set()
    for k, lines in blocks:
        if k in managed_keys:
            if k in done_keys:
                continue
            done_keys.add(k)
            v = values.get(k, None)
            if v is None:                        # 前端沒送這個欄位 → 保留原值
                fm.append(lines[0])
            else:
                fm.append("%s: %s" % (k, _yaml_value(v)))
        else:
            fm.extend(lines)
    for k in managed_keys:
        if k not in done_keys and str(values.get(k, "") or "").strip():
            fm.append("%s: %s" % (k, _yaml_value(values[k])))

    # ---- 本文：受管理段落只出現一次（重複的合併進第一個）
    old_lead = old["lead"] if old else {TODO_HEADING: [], HEARING_HEADING: []}
    blocks_md = {
        HEARING_HEADING: old_lead[HEARING_HEADING] +
            [l for h in hearings for l in [_hearing_line(h)] + list(h.get("extra") or [])],
        TODO_HEADING: old_lead[TODO_HEADING] +
            [l for t in todos for l in [_todo_line(t)] + list(t.get("extra") or [])],
    }
    present = [h for h, _ in secs]
    for name in reversed(MANAGED):
        if name not in present:
            secs.insert(0, [name, []])
    sections = {h: clean_section_text(t) for h, t in (sections or {}).items() if h not in MANAGED}
    for h in sections:
        if h not in present:
            secs.append([h, []])
    out = ["---"] + fm + ["---", pre.rstrip("\n")]
    emitted = set()
    for h, lines in secs:
        if h in MANAGED or h in sections:
            if h in emitted:                     # 同名段落只留一個
                continue
            emitted.add(h)
        if h in MANAGED:
            out += ["", "## " + h] + blocks_md[h]
        else:
            content = sections[h] if h in sections else "\n".join(lines).strip("\n")
            out += ["", "## " + h] + (["", content] if content.strip() else [])
    text = "\n".join(out).rstrip("\n") + "\n"

    tmp = path.with_name(path.name + ".saving")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    _retry(lambda: os.replace(tmp, path))


def _retry(fn, tries: int = 12):
    """Windows 上檔案正被讀取（另一個請求、Google Drive 同步程式、防毒軟體）時，
    取代或開啟會短暫得到 PermissionError；稍等再試，總共最多約 3 秒。"""
    for i in range(tries):
        try:
            return fn()
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.05 * (i + 1))


def ensure_ids(path: Path, default_title: str) -> dict | None:
    """Claude 或其他軟體改過的卡片可能缺事件 id；補上後寫回。回傳最新內容。"""
    with lock(path):
        d = read(path)
        if not d:
            return None
        if any(not t["gcal"] for t in d["todos"] if t["due"]) or \
                any(not h["gcal"] for h in d["hearings"]):
            write(path, d["meta"], d["todos"], d["hearings"], default_title)
            d = read(path)
        return d
