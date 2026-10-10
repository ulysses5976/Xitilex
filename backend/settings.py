# -*- coding: utf-8 -*-
"""設定載入。

多台電腦共用：程式放在 Google 雲端硬碟（「我的雲端硬碟\\律法夕惕者 Xitilex」），三台跑同一份。
每台電腦的使用者名稱、雲端硬碟掛載位置可能不同，所以 config.json 裡的路徑用 {drive} 代表
「雲端硬碟根目錄」，執行時再換成這台電腦的實際位置：
    1. 程式本身就放在雲端硬碟裡 → 程式資料夾的上一層就是雲端硬碟根目錄
    2. 否則找 家目錄\\我的雲端硬碟 (…)、各磁碟機的「我的雲端硬碟」「My Drive」
每台電腦自己的特殊設定（例如路徑真的不一樣）放在 %LOCALAPPDATA%\\casedesk\\local.json，
它會覆蓋 config.json 的同名欄位，而且不會同步到其他電腦。
"""
from __future__ import annotations
import json
import os
import shutil
import string
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
CONFIG = ROOT / "config.json"
CONFIG_EXAMPLE = ROOT / "config.example.json"     # 第一次執行、還沒有 config.json 時以此為範本
DATA = ROOT / "data"                              # 跟著程式同步：OAuth 用戶端設定、Claude 對話紀錄
if os.environ.get("CASEDESK_DATA"):                # 測試用沙盒：資料另放，不碰正式的 data
    DATA = Path(os.environ["CASEDESK_DATA"])
LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "casedesk"   # 每台各自一份
LOCAL_CONFIG = LOCAL_DIR / "local.json"
LOCAL_KEYS = ("root", "vault_path", "claude_bin", "port", "drive", "python", "pythonw")
DRIVE_MARK = "工作相關資料"                         # 預設：用來認出「這就是那個雲端硬碟」（實際取自 config 的 root）


def _find_claude() -> str:
    for p in (shutil.which("claude"),
              str(Path.home() / ".local" / "bin" / "claude.exe"),
              str(Path.home() / "AppData" / "Roaming" / "npm" / "claude.cmd")):
        if p and Path(p).exists():
            return p
    return ""


def drive_mark(cfg: dict) -> str:
    """config 的 root 寫成「{drive}\\案件資料夾」時，雲端硬碟根目錄底下應該有的那個資料夾名稱。"""
    root = str(cfg.get("root") or "")
    if "{drive}" in root:
        rest = root.split("{drive}", 1)[1].strip("\\/")
        if rest:
            return rest.replace("/", "\\").split("\\")[0]
    return DRIVE_MARK


def find_drive(mark: str = DRIVE_MARK) -> str:
    """這台電腦上 Google 雲端硬碟的根目錄（找不到回傳空字串）。"""
    cands = [ROOT.parent]
    home = Path.home()
    try:
        cands += sorted(p for p in home.iterdir() if p.is_dir() and
                        (p.name.startswith("我的雲端硬碟") or p.name.startswith("My Drive")))
    except OSError:
        pass
    for letter in string.ascii_uppercase[3:]:            # D: 以後（雲端硬碟串流模式常見 G:）
        for name in ("我的雲端硬碟", "My Drive"):
            cands.append(Path("%s:\\" % letter) / name)
    for p in cands:
        try:
            if (p / mark).is_dir():
                return str(p)
        except OSError:
            continue
    return ""


def _expand(v, drive: str):
    if isinstance(v, str) and "{drive}" in v:
        return str(Path(v.replace("{drive}", drive))) if drive else ""
    return v


def load_local() -> dict:
    try:
        d = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def load() -> dict:
    if not CONFIG.exists() and CONFIG_EXAMPLE.exists():   # 剛下載的新安裝：從範本建立設定檔
        shutil.copyfile(CONFIG_EXAMPLE, CONFIG)
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    local = load_local()
    for k in LOCAL_KEYS:                               # 這台電腦自己的設定優先
        if local.get(k):
            cfg[k] = local[k]
    drive = cfg.get("drive") or find_drive(drive_mark(cfg))
    cfg["drive"] = drive
    for k in ("root", "vault_path"):
        cfg[k] = _expand(cfg.get(k, ""), drive)
    # 測試用：指向沙盒資料夾／另一個連接埠，不碰真實案件
    if os.environ.get("CASEDESK_ROOT"):
        cfg["root"] = os.environ["CASEDESK_ROOT"]
    if os.environ.get("CASEDESK_VAULT"):
        cfg["vault_path"] = os.environ["CASEDESK_VAULT"]
    if os.environ.get("CASEDESK_PORT"):
        cfg["port"] = int(os.environ["CASEDESK_PORT"])
    # 沙盒與正式版共用同一份 Google 授權；沙盒預設不同步，免得假案件寫進真的日曆
    if os.environ.get("CASEDESK_GCAL") == "off":
        cfg.setdefault("google", {})["enabled"] = False
    if not cfg.get("claude_bin") or not Path(cfg["claude_bin"]).exists():
        cfg["claude_bin"] = _find_claude()
    return cfg


def _write_json(path: Path, raw: dict) -> None:
    """寫入時先寫暫存檔再取代；雲端硬碟同步程式可能短暫鎖住檔案，稍等再試。"""
    tmp = path.with_name(path.name + ".saving")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for i in range(12):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if i == 11:
                raise
            time.sleep(0.05 * (i + 1))


def save_section(key: str, value: dict) -> None:
    """整段覆寫 config.json 的某一區（例如 ui）。"""
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    raw[key] = value
    _write_json(CONFIG, raw)


def save_google(patch: dict) -> None:
    """只改 config.json 的 google 區塊（其他欄位與環境變數覆寫都不動）。"""
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    g = raw.setdefault("google", {})
    for k in ("enabled", "auto_sync", "calendar_hearing", "calendar_deadline", "previous_calendars"):
        if k in patch:
            g[k] = patch[k]
    _write_json(CONFIG, raw)


def save_local(patch: dict) -> None:
    """寫入這台電腦自己的設定（不同步）。"""
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    raw = load_local()
    raw.update({k: v for k, v in patch.items() if k in LOCAL_KEYS})
    _write_json(LOCAL_CONFIG, raw)
