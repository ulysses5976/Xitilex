# -*- coding: utf-8 -*-
"""新收文書提醒：找出案件資料夾裡「還沒看過」的新文件（法院通知、判決、對造書狀、當事人資料…）。

怎麼判斷「新」：
  * 每件案件記一份「已看過的檔案」（data/inbox/<案件id>.json，跟著雲端硬碟同步，三台電腦共用）。
    一個檔案只要路徑在清單裡，或「大小＋修改時間」跟清單裡某個檔案相同（＝被搬移或改名過），就算看過。
  * 還沒有清單的案件，以第一次啟用這個功能的時間為準：之後才修改的檔案算新。
  * 律師自己寫的東西不算：資料夾名稱含「本所撰擬」「本所出狀」「本案相關研究」「Claude整理」「_待刪除」
    的整個略過（可在 config.json 的 inbox_skip_dirs 調整）；也只看文件類的副檔名。

全部案件約三萬個檔案，掃一次幾秒；背景每 10 分鐘掃一次，打開案件時另外即時重算那一件。

© 2026 無名小律師（楊朝淵律師）. Released under the MIT License.
"""
from __future__ import annotations
import json
import os
import re
import threading
import time
from pathlib import Path

from . import settings

DIR = settings.DATA / "inbox"
BASELINE = DIR / "_baseline.json"
EXTS = {".pdf", ".doc", ".docx", ".odt", ".rtf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic",
        ".msg", ".eml", ".xls", ".xlsx"}
SKIP_DIR_WORDS = ["本所撰擬", "本所出狀", "本案相關研究", "Claude整理", "_待刪除"]
MAX_LIST = 300                       # 一件案件最多列出幾個新檔（當事人一次給幾百個檔時）

_lock = threading.Lock()
_counts: dict[str, int] = {}
_last_scan = {"at": 0.0}


def _safe_id(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", cid)[:80]


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".saving")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for i in range(12):                 # Windows：雲端硬碟同步程式正在讀檔時會短暫失敗
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    os.replace(tmp, p)


def baseline() -> float:
    """第一次啟用的時間。之前就在資料夾裡的檔案一律當作看過，不會一次跳出幾萬個「新」檔。"""
    d = _read_json(BASELINE)
    if isinstance(d, dict) and isinstance(d.get("at"), (int, float)):
        return float(d["at"])
    at = time.time()
    _write_json(BASELINE, {"at": at, "note": "新收文書提醒啟用時間：早於此時的檔案視為已看過"})
    return at


def _skip_words(cfg: dict) -> list[str]:
    return list(cfg.get("inbox_skip_dirs") or SKIP_DIR_WORDS)


def list_files(case_path: str, cfg: dict) -> list[dict]:
    words, out = _skip_words(cfg), []
    base = Path(case_path)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith((".", "~")) and not any(w in d for w in words)]
        for f in files:
            if f.startswith(("~$", ".")) or os.path.splitext(f)[1].lower() not in EXTS:
                continue
            p = os.path.join(root, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out.append({"rel": os.path.relpath(p, base), "size": st.st_size, "mtime": st.st_mtime})
    return out


def _record(cid: str) -> dict | None:
    d = _read_json(DIR / (_safe_id(cid) + ".json"))
    return d if isinstance(d, dict) and isinstance(d.get("seen"), dict) else None


def _fp(f: dict) -> tuple:
    return (int(f["size"]), int(round(f["mtime"] * 1000)))


def _norm_fp(v) -> tuple | None:
    """紀錄裡的 [大小, 修改時間]；早期版本存的是秒，換成毫秒。"""
    if not (isinstance(v, list) and len(v) == 2):
        return None
    size, t = int(v[0]), int(v[1])
    return (size, t * 1000 if t < 10 ** 11 else t)


def _same(a, b) -> bool:
    """大小相同、修改時間相差 2 秒內（不同電腦經雲端硬碟同步，時間精度可能不同）。"""
    return bool(a) and a[0] == b[0] and abs(a[1] - b[1]) <= 2000


def _split(cid: str, files: list[dict]) -> tuple[list[dict], list[dict]]:
    """(新檔, 看過的檔)"""
    rec = _record(cid)
    if rec:
        seen = {k: _norm_fp(v) for k, v in rec["seen"].items()}
        # 「大小＋修改時間」相同只在原檔已經不在原位時才算（＝被搬移或改名），
        # 免得一批大小相同、同時存進來的新檔被誤認為看過
        here = {f["rel"] for f in files}
        moved = [v for k, v in seen.items() if k not in here and v]

        def is_new(f):
            fp = _fp(f)
            if f["rel"] in seen:                  # 同一個位置：內容換過（同名的新文件取代舊檔）也算新
                return not _same(seen[f["rel"]], fp)
            return not any(_same(v, fp) for v in moved)
    else:
        t0 = baseline()
        is_new = lambda f: f["mtime"] > t0
    new = [f for f in files if is_new(f)]
    old = [f for f in files if not is_new(f)]
    return new, old


def new_files(case: dict, cfg: dict) -> list[dict]:
    """這件案件的新文件（新的在前）。順便更新清單上的計數。"""
    new, _ = _split(case["id"], list_files(case["path"], cfg))
    new.sort(key=lambda f: -f["mtime"])
    with _lock:
        _counts[case["id"]] = len(new)
    return new[:MAX_LIST] if len(new) > MAX_LIST else new


def ack(case: dict, cfg: dict, rels: list[str] | None = None) -> int:
    """標為看過：rels 給清單就只標那些，不給就整件全部標。回傳剩下幾個新檔。"""
    files = list_files(case["path"], cfg)
    new, old = _split(case["id"], files)
    marked = {f["rel"] for f in new} if rels is None else set(rels)
    seen = {f["rel"]: list(_fp(f)) for f in old}
    seen.update({f["rel"]: list(_fp(f)) for f in new if f["rel"] in marked})
    _write_json(DIR / (_safe_id(case["id"]) + ".json"), {"seen": seen, "at": time.time()})
    left = sum(1 for f in new if f["rel"] not in marked)
    with _lock:
        _counts[case["id"]] = left
    return left


def counts() -> dict[str, int]:
    with _lock:
        return dict(_counts)


def scan_all(cfg: dict, cases: list[dict]) -> None:
    baseline()
    result = {}
    for c in cases:
        try:
            new, _ = _split(c["id"], list_files(c["path"], cfg))
            result[c["id"]] = len(new)
        except OSError:
            continue
    with _lock:
        _counts.clear()
        _counts.update(result)
    _last_scan["at"] = time.time()


def start_background(cfg: dict, get_cases, every: int = 600) -> None:
    """背景定期重掃（啟動後先掃一次）。"""
    def loop():
        time.sleep(3)
        while True:
            try:
                scan_all(cfg, list(get_cases().values()))
            except Exception as e:
                print("新收文書掃描失敗：%r" % e)
            time.sleep(every)
    threading.Thread(target=loop, daemon=True, name="inbox-scan").start()


def scanned_at() -> float:
    return _last_scan["at"]
