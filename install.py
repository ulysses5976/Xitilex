# -*- coding: utf-8 -*-
"""律法夕惕者 Xitilex — 新電腦首次安裝（雙擊「安裝.cmd」執行）。

會做這幾件事，每一步都可以重複執行（已經做過的會略過）：
  1. 安裝需要的 Python 套件
  2. 找到這台電腦的 Google 雲端硬碟與案件資料夾
  3. 檢查 Claude Code 有沒有安裝、有沒有登入
  4. 把「判決查驗」連接器註冊給 Claude Code（若這台有裝）
  5. 在桌面建立「律法夕惕者」捷徑（並移除舊名稱「夕惕者」的捷徑）

© 2026 無名小律師（楊朝淵律師）. Released under the MIT License.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
OK, WARN, BAD = "  ✓ ", "  ! ", "  ✗ "
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def step(title):
    print("\n" + title)


def clean_env():
    """叫起 claude 時不要帶著 Claude Code 工作階段的環境變數。"""
    return {k: v for k, v in os.environ.items()
            if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC_BASE_URL") or k.startswith("MCP_"))}


def main():
    print("律法夕惕者 Xitilex — 首次安裝")
    print("Vigilantibus, non dormientibus, iura subveniunt.")
    problems = []

    # 1. Python 套件 ------------------------------------------------------------
    step("1. 安裝 Python 套件")
    if sys.version_info < (3, 10):
        print(BAD + "Python 版本太舊（需要 3.10 以上），目前是 %s" % sys.version.split()[0])
        problems.append("升級 Python")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
    print((OK + "套件已安裝") if r.returncode == 0 else (BAD + "套件安裝失敗，請把上面的訊息拍給 Claude 看"))
    if r.returncode != 0:
        problems.append("Python 套件")

    from backend import settings, claude_runner          # 套件裝好後才匯入

    # 記下這台電腦的 Python 位置，讓「律法夕惕者.exe」找得到（pythonw＝不開主控台視窗）
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    settings.save_local({"python": str(py), "pythonw": str(pyw if pyw.exists() else py)})
    try:
        import webview  # noqa: F401
        print(OK + "原生視窗元件（pywebview）可用")
    except Exception as e:
        print(WARN + "原生視窗元件載入失敗（%r），系統會改用瀏覽器開啟" % e)

    # 2. 雲端硬碟 ----------------------------------------------------------------
    step("2. 尋找 Google 雲端硬碟與案件資料夾")
    cfg = settings.load()
    if cfg.get("root") and Path(cfg["root"]).is_dir():
        print(OK + "案件資料夾：%s" % cfg["root"])
    else:
        mark = settings.drive_mark(json.loads(settings.CONFIG.read_text(encoding="utf-8")))
        print(WARN + "自動偵測不到案件資料夾「%s」。" % mark)
        p = input("    請貼上雲端硬碟根目錄（裡面有「%s」），或直接貼上案件資料夾的完整路徑"
                  "（直接按 Enter 跳過）：" % mark).strip().strip('"')
        if p and (Path(p) / mark).is_dir():
            settings.save_local({"drive": p})
            print(OK + "已記住（只存在這台電腦）")
        elif p and Path(p).is_dir():
            settings.save_local({"root": p})
            print(OK + "已記住案件資料夾（只存在這台電腦）")
        else:
            print(BAD + "還是找不到，系統開啟後到時再處理")
            problems.append("雲端硬碟路徑")
    cfg = settings.load()
    if cfg.get("vault_path") and Path(cfg["vault_path"]).is_dir():
        print(OK + "Obsidian 筆記庫：%s" % cfg["vault_path"])
    else:
        print(WARN + "找不到 Obsidian 筆記庫（不影響其他功能，只是 Claude 讀不到筆記）")

    # 3. Claude Code -------------------------------------------------------------
    step("3. 檢查 Claude Code")
    claude = cfg.get("claude_bin")
    if not claude:
        print(BAD + "找不到 Claude Code。請先安裝 Claude Code，再執行一次本安裝。")
        problems.append("安裝 Claude Code")
    else:
        print(OK + "Claude Code：%s" % claude)
        state = claude_runner.credential_state()
        if state == "正常":
            print(OK + "已登入（實際能不能用，開系統後看 Claude 面板「工具」的小圓點）")
        else:
            print(BAD + "命令列 Claude 尚未登入：%s" % state)
            print("    → 開一般 PowerShell，輸入 claude，再輸入 /login 完成登入。")
            problems.append("登入 Claude Code")

    # 4. 判決查驗連接器 -------------------------------------------------------------
    step("4. 註冊「判決查驗」連接器")
    if claude:
        listed = subprocess.run([claude, "mcp", "list"], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", env=clean_env(), timeout=120, creationflags=NOWIN).stdout
        if "judicial-tw" in listed:
            print(OK + "已註冊")
        else:
            desk = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
            try:
                entry = json.loads(desk.read_text(encoding="utf-8"))["mcpServers"]["judicial-tw"]
                entry.setdefault("type", "stdio")
                r = subprocess.run([claude, "mcp", "add-json", "--scope", "user", "judicial-tw",
                                    json.dumps(entry, ensure_ascii=False)], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", env=clean_env(), timeout=60, creationflags=NOWIN)
                print((OK + "已依桌面版的設定註冊") if r.returncode == 0 else (BAD + "註冊失敗：" + (r.stderr or r.stdout)[-300:]))
            except (OSError, ValueError, KeyError):
                print(WARN + "這台的 Claude 桌面版設定裡沒有 judicial-tw，略過（判決查驗功能這台不能用）")

    # 5. 捷徑：桌面＋開始功能表 ------------------------------------------------------
    step("5. 建立桌面與開始功能表捷徑")
    if sys.platform == "win32":
        exe = ROOT / "律法夕惕者.exe"
        ps = (
            "$ws=New-Object -ComObject WScript.Shell;"
            "foreach($f in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){"
            "  Remove-Item -LiteralPath (Join-Path $f '夕惕者.lnk') -ErrorAction SilentlyContinue;"
            "  $s=$ws.CreateShortcut((Join-Path $f '律法夕惕者.lnk'));"
            "  $s.TargetPath='%s';$s.WorkingDirectory='%s';$s.IconLocation='%s,0';"
            "  $s.Description='律法夕惕者 Xitilex — 案件管理';$s.Save()}"
            "'ok'"
        ) % (exe, ROOT, exe)
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NOWIN)
        if r.returncode == 0 and exe.exists():
            print(OK + "已建立「律法夕惕者」捷徑（桌面、開始功能表）")
        else:
            print(BAD + "建立失敗：" + (r.stderr or "找不到 律法夕惕者.exe")[-300:])
    else:
        print(WARN + "不是 Windows，略過捷徑")

    # 結果 ------------------------------------------------------------------------
    print("\n" + "=" * 50)
    if problems:
        print("還有要處理的：" + "、".join(problems))
    else:
        print("安裝完成。雙擊桌面的「律法夕惕者」就能開啟。")
    print("第一次開啟後，請在右上角按「Google 日曆」→「連結 Google 日曆」授權這台電腦。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                                   # 讓視窗停住，看得到錯誤
        print("\n安裝過程出錯：%r" % e)
