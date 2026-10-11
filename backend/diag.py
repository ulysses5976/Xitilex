# -*- coding: utf-8 -*-
"""每台電腦的診斷報告：寫到程式資料夾的 data/diag/<電腦名稱>.json（跟著雲端硬碟同步）。

多台電腦共用時，A 電腦出問題，在 B 電腦就能讀到 A 的狀況：用哪個 Python、原生視窗元件
有沒有裝、這次是用視窗還是瀏覽器開的（以及原因）、Claude Code 有沒有登入、查到哪些 skill 與連接器。
只記狀態，不記案件內容。

© 2026 無名小律師（楊朝淵律師）. Released under the MIT License.
"""
from __future__ import annotations
import json
import os
import platform
import sys
import time
from pathlib import Path

from . import settings

DIR = settings.DATA / "diag"


def _host() -> str:
    return (os.environ.get("COMPUTERNAME") or platform.node() or "unknown").strip() or "unknown"


def _path() -> Path:
    return DIR / (_host() + ".json")


def _read() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(d: dict) -> None:
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        tmp = _path().with_suffix(".saving")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, _path())
    except OSError as e:
        print("診斷報告寫不進去：%r" % e)


def _caps_summary() -> dict:
    from . import claude_runner
    c = claude_runner.load_capabilities() or {}
    skills = [s if isinstance(s, str) else (s or {}).get("name", "") for s in c.get("skills", []) or []]
    return {"checked_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(c["at"])) if c.get("at") else "",
            "ok": c.get("ok"), "error": c.get("error", ""), "skills_count": len(skills), "skills": skills,
            "mcp_servers": [s.get("name") for s in c.get("mcp_servers", []) or [] if isinstance(s, dict)]}


def record_launch(mode: str, reason: str = "", cfg: dict | None = None) -> None:
    """啟動時記一筆：視窗或瀏覽器、原因、Python 與元件狀態。"""
    try:
        import webview
        wv = getattr(webview, "__version__", "") or "已安裝"
    except Exception as e:
        wv = "沒有安裝或載入失敗：%r" % e
    from . import claude_runner
    local_skills = Path.home() / ".claude" / "skills"
    d = _read()
    d.update({
        "host": _host(),
        "launched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "mode": mode, "fallback_reason": reason,
        "python": sys.executable, "python_version": sys.version.split()[0],
        "pywebview": wv,
        "claude_bin": (cfg or {}).get("claude_bin", ""),
        "claude_login": claude_runner.credential_state(),
        "local_skill_folders": sorted(p.name for p in local_skills.iterdir() if p.is_dir()) if local_skills.is_dir() else [],
        "local_json": settings.load_local(),
        "capabilities": _caps_summary(),
    })
    _write(d)


def record_capabilities() -> None:
    """重新檢查 Claude 可用工具之後，更新報告裡的那一段。"""
    d = _read()
    d["capabilities"] = _caps_summary()
    d["host"] = _host()
    _write(d)
