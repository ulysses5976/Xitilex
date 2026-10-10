# -*- coding: utf-8 -*-
"""掃描雲端硬碟同步夾，把案件資料夾認出來。

判準（依你現有的命名慣例）：
  * 代號型：CM001-王小明-加重強盜、LB008A-陳大文-定暫時狀態處分
  * 日期型：20250106-王小明、1140402-陳大文等二人（陪偵、義辯）
認到案件資料夾就不再往下鑽；其他資料夾最多往下 max_depth 層。
"""
from __future__ import annotations
import hashlib
import os
import re
import time
from pathlib import Path

from . import card

CODE_RE = re.compile(r"^(?P<code>[A-Z]{1,3}\d{2,4}[A-Z]?)-(?P<rest>.+)$")
DATE_RE = re.compile(r"^(?P<code>\d{7,8})-(?P<rest>.+)$")
CAT_RE = re.compile(r"^[0-9A-Z]{2,3}\s+(.+)$")

PREFIX_CAT = {"CM": "刑事訴訟", "CV": "民事訴訟", "LB": "勞動事件", "FA": "家事案件",
              "CE": "強制執行", "CI": "消費者債務清理", "EA": "遺產管理人",
              "LC": "法律顧問", "CA": "法律顧問"}

# 案件種類：代號字首優先（CV 放在家事資料夾裡仍是民事），其次看所在資料夾
TYPE_BY_PREFIX = {"CM": "刑事", "CV": "民事", "FA": "家事", "LB": "勞動", "CI": "消債",
                  "CE": "強制執行", "EA": "遺產管理", "SP": "法律顧問", "LC": "法律顧問",
                  "CA": "法律顧問"}
TYPE_BY_FOLDER = [("陪偵", "陪偵"), ("義務辯護", "義務辯護"), ("刑事", "刑事"), ("民事", "民事"),
                  ("家事", "家事"), ("勞動", "勞動"), ("消費者債務", "消債"), ("強制執行", "強制執行"),
                  ("遺產管理", "遺產管理"), ("顧問", "法律顧問"), ("法律諮詢", "法律諮詢"),
                  ("受僱時期", "受僱時期")]
TYPES = ["民事", "刑事", "家事", "勞動", "消債", "強制執行", "遺產管理", "法律顧問",
         "陪偵", "義務辯護", "法律諮詢", "受僱時期", "其他"]
PIN_TRUE = ("是", "true", "yes", "1", "釘選")


def case_type(code: str, group: str) -> str:
    pre = re.match(r"[A-Z]+", code)
    if pre and pre.group(0) in TYPE_BY_PREFIX:
        return TYPE_BY_PREFIX[pre.group(0)]
    for kw, t in TYPE_BY_FOLDER:
        if kw in group:
            return t
    return "其他"


_cache: dict = {"at": 0.0, "cases": {}, "root": ""}


def case_id(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]


def _category(parts: list[str], code: str) -> str:
    for p in parts:
        m = CAT_RE.match(p)
        if m:
            return m.group(1).replace("案件", "").strip() or p
    pre = re.match(r"[A-Z]+", code)
    return PREFIX_CAT.get(pre.group(0), "未分類") if pre else "未分類"


def _make_case(path: Path, root: Path, cfg: dict) -> dict | None:
    name = path.name
    m = CODE_RE.match(name) or DATE_RE.match(name)
    if not m:
        return None
    rest = m.group("rest").split("-")
    rel = str(path.relative_to(root))
    parents = list(path.relative_to(root).parts[:-1])
    c = {
        "id": case_id(rel), "name": name, "rel": rel, "path": str(path),
        "code": m.group("code"), "client": rest[0].strip(),
        "cause": "-".join(rest[1:]).strip(),
        "category": _category(parents, m.group("code")),
        "group": parents[0] if parents else "（根目錄）",
        "mtime": path.stat().st_mtime,
        "status": "", "next_date": "", "open_todos": 0, "has_card": False,
        "pinned": False,
    }
    c["ctype_auto"] = case_type(c["code"], c["group"])
    c["ctype"] = c["ctype_auto"]
    _apply_card(c, cfg)
    return c


def _apply_card(c: dict, cfg: dict) -> None:
    d = card.read(Path(c["path"]) / cfg["card_name"])
    c["has_card"] = d is not None
    if d:
        c["status"] = d["meta"].get("案件狀態", "")
        c["next_date"] = d["next"]
        c["open_todos"] = sum(1 for t in d["todos"] if not t["done"])
        c["mtime"] = max(c["mtime"], d["mtime"])
        c["pinned"] = str(d["meta"].get("釘選", "")).strip().lower() in PIN_TRUE
        if d["meta"].get("案件類型") in TYPES:
            c["ctype"] = d["meta"]["案件類型"]
        c["opponent"] = str(d["meta"].get("對造", "") or "")              # 利益衝突檢查用
        c["sub_parties"] = [s["name"] for s in d.get("subcases", [])]
    else:
        c["opponent"], c["sub_parties"] = "", []
        c["status"], c["next_date"], c["open_todos"], c["pinned"] = "", "", 0, False
        c["ctype"] = c["ctype_auto"]
    if not c["status"] and c["group"] in cfg.get("closed_groups", []):
        c["status"] = "已結案"


def scan(cfg: dict, force: bool = False) -> dict:
    root = Path(cfg["root"])
    if not force and _cache["cases"] and _cache["root"] == str(root) \
            and time.time() - _cache["at"] < 300:
        return _cache["cases"]
    excl = set(cfg.get("exclude_dirs", []))
    cases: dict = {}

    def walk(d: Path, depth: int):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            if not e.is_dir() or e.name.startswith(".") or e.name in excl:
                continue
            p = Path(e.path)
            c = _make_case(p, root, cfg)
            if c:
                cases[c["id"]] = c
            elif depth < cfg.get("max_depth", 3):
                walk(p, depth + 1)

    if root.exists():
        walk(root, 1)
    _cache.update(at=time.time(), cases=cases, root=str(root))
    return cases


def get(cfg: dict, cid: str) -> dict | None:
    c = scan(cfg).get(cid)
    if c is None:
        c = scan(cfg, force=True).get(cid)
    return c


def refresh_one(cfg: dict, cid: str) -> dict | None:
    c = _cache["cases"].get(cid)
    if c:
        _apply_card(c, cfg)
    return c
