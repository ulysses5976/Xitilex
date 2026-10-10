# -*- coding: utf-8 -*-
"""國定假日與補行上班日：法定期間計算器用來判斷「期間末日是否為休息日」。

資料來源：行政院人事行政總處「政府行政機關辦公日曆表」（經 github.com/ruyut/TaiwanCalendar 整理成
JSON，從 jsDelivr 下載）。每年一個檔，放在程式資料夾 data/holidays/，跟著雲端硬碟同步到其他電腦。
颱風等臨時停止上班日由律師自己加在 data/holidays/extra.json。

© 2026 無名小律師（楊朝淵律師）. Released under the MIT License.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import threading
import urllib.request
from pathlib import Path

from . import settings

DIR = settings.DATA / "holidays"
EXTRA = DIR / "extra.json"
SRC = "https://cdn.jsdelivr.net/gh/ruyut/TaiwanCalendar/data/{year}.json"
SOURCE_NOTE = "行政院人事行政總處 政府行政機關辦公日曆表（經 github.com/ruyut/TaiwanCalendar）"
_lock = threading.Lock()


def _iso(d8: str) -> str:
    return "%s-%s-%s" % (d8[:4], d8[4:6], d8[6:8])


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".saving")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, path)


def load() -> dict:
    """合併各年度：{"years": [...], "holidays": {日期: 說明}, "workdays": [週末補班日], "extra": {日期: 說明}}"""
    out = {"years": [], "holidays": {}, "workdays": [], "extra": {}, "source": SOURCE_NOTE}
    if DIR.exists():
        for p in sorted(DIR.glob("[0-9][0-9][0-9][0-9].json")):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out["years"].append(int(d["year"]))
                out["holidays"].update({_iso(k): v for k, v in d["holidays"].items()})
                out["workdays"] += [_iso(k) for k in d.get("workdays", [])]
            except (OSError, ValueError, KeyError, TypeError):
                continue
    try:
        out["extra"] = {k: str(v) for k, v in json.loads(EXTRA.read_text(encoding="utf-8")).items()
                        if _valid(k)}
    except (OSError, ValueError, AttributeError):
        pass
    return out


def _valid(day: str) -> bool:
    try:
        dt.date.fromisoformat(day)
        return True
    except (TypeError, ValueError):
        return False


def save_extra(extra: dict) -> dict:
    clean = {k: str(v or "停止上班").strip()[:40] for k, v in (extra or {}).items() if _valid(k)}
    with _lock:
        _write_json(EXTRA, dict(sorted(clean.items())))
    return load()


def _download(year: int) -> dict:
    with urllib.request.urlopen(SRC.format(year=year), timeout=20) as r:
        rows = json.loads(r.read().decode("utf-8"))
    if not isinstance(rows, list) or len(rows) not in (365, 366):
        raise ValueError("%d 年的資料天數不對（%s 天）" % (year, len(rows) if isinstance(rows, list) else "?"))
    for x in rows:
        if not (isinstance(x, dict) and str(x.get("date", "")).startswith(str(year))
                and len(x["date"]) == 8 and isinstance(x.get("isHoliday"), bool)):
            raise ValueError("%d 年的資料格式不對" % year)
    return {"source": SOURCE_NOTE, "year": year,
            "holidays": {x["date"]: (x.get("description") or "") for x in rows if x["isHoliday"]},
            "workdays": [x["date"] for x in rows if not x["isHoliday"] and x.get("week") in ("六", "日")]}


def refresh(years: list[int] | None = None) -> dict:
    """下載（或更新）假日資料。預設：去年、今年、明年。"""
    y0 = dt.date.today().year
    years = years or [y0 - 1, y0, y0 + 1]
    done, failed = [], {}
    for y in years:
        try:
            data = _download(int(y))
            with _lock:
                _write_json(DIR / ("%d.json" % y), data)
            done.append(y)
        except Exception as e:                  # 明年的資料可能還沒公布
            failed[y] = str(e)[:200]
    return {"updated": done, "failed": failed, **load()}


def refresh_if_missing() -> None:
    """啟動時在背景補下載：今年或明年（下半年起）的資料不在就試著抓，失敗就算了。"""
    y0 = dt.date.today().year
    want = [y0] + ([y0 + 1] if dt.date.today().month >= 7 else [])
    have = set(load()["years"])
    missing = [y for y in want if y not in have]
    if missing:
        try:
            refresh(missing)
        except Exception:
            pass
