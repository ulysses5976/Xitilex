# -*- coding: utf-8 -*-
"""啟動「律法夕惕者 Xitilex」。

平常由「律法夕惕者.exe」（或桌面捷徑）以無主控台的 pythonw 執行，開出原生視窗。
參數：
  （無）           原生視窗（pywebview＋Windows 內建的 Edge 引擎）；已在執行中就只開一個新視窗
  --browser        改用電腦預設的瀏覽器開（原生視窗出問題時的備用方式）
  --no-browser     只啟動伺服器，不開任何視窗（開發測試用）
  --case=<id>      開啟時直接打開某件案件

© 2026 無名小律師（楊朝淵律師）. Released under the MIT License.
"""
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request

# 直接以程式所在資料夾為匯入起點（資料夾叫什麼都可以，例如「律法夕惕者 Xitilex」）
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from backend import settings  # noqa: E402

APP_ID = "NamelessLawyer.Xitilex"
TITLE = "律法夕惕者 Xitilex"
ICON = os.path.join(HERE, "frontend", "xitilex.ico")
GEOMETRY = settings.LOCAL_DIR / "window.json"
ZOOM_FILE = settings.LOCAL_DIR / "zoom.json"
ZOOM_STEPS = [0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
_zoom_lock = threading.Lock()          # 連按快捷鍵時，一次只處理一個縮放


def _saved_zoom() -> float:
    try:
        z = float(json.loads(ZOOM_FILE.read_text(encoding="utf-8")).get("zoom", 1.0))
        return z if 0.25 <= z <= 5 else 1.0
    except (OSError, ValueError, AttributeError):
        return 1.0


def _on_ui_thread(win, fn):
    """WebView2 只能在視窗自己的執行緒上操作。"""
    from System import Func, Type
    form = win.native
    return form.Invoke(Func[Type](fn)) if form.InvokeRequired else fn()


def _set_zoom(win, factor: float) -> float:
    def apply():
        win.native.webview.ZoomFactor = factor
        return None
    _on_ui_thread(win, apply)
    return factor


def _remember_zoom(z: float):
    settings.LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    ZOOM_FILE.write_text(json.dumps({"zoom": round(z, 4)}), encoding="utf-8")


def _get_zoom(win) -> float:
    box = {}

    def read():
        box["z"] = float(win.native.webview.ZoomFactor)
        return None
    _on_ui_thread(win, read)
    return box.get("z", 1.0)


def _redirect_output_if_windowless():
    """pythonw 沒有主控台，print 與錯誤訊息改寫進記錄檔（出問題時查得到）。"""
    if sys.stdout is not None and sys.stderr is not None:
        return
    settings.LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    log = settings.LOCAL_DIR / "xitilex.log"
    if log.exists() and log.stat().st_size > 2_000_000:
        log.replace(log.with_suffix(".log.1"))
    f = open(log, "a", encoding="utf-8", buffering=1)
    f.write("\n===== %s 啟動 =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    sys.stdout = sys.stderr = f


def _trust_windows_certs():
    # 防毒（Avast 等）的 HTTPS 掃描會用自己的根憑證攔截連線；那張憑證在 Windows
    # 憑證庫裡，但 Python 預設只認 certifi，連 Google 會 CERTIFICATE_VERIFY_FAILED。
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        print("（提示：py -3 -m pip install truststore 可避免防毒軟體造成的憑證錯誤）")


def _message(text: str):
    """沒有主控台時，用 Windows 訊息框告訴使用者。"""
    print(text)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x40)


def _arg(name: str) -> str:
    for a in sys.argv[1:]:
        if a.startswith("--%s=" % name):
            return a.split("=", 1)[1]
    return ""


def _already_running(base: str) -> bool:
    try:
        with urllib.request.urlopen(base + "api/meta", timeout=1.5) as r:
            return r.status == 200 and "statuses" in json.loads(r.read())
    except Exception:
        return False


def _webview_available() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def _handover(base: str) -> bool:
    """請已在跑的瀏覽器模式伺服器結束，等它讓出連接埠。成功回傳 True。"""
    try:
        req = urllib.request.Request(base + "api/app/handover", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        if not json.loads(urllib.request.urlopen(req, timeout=5).read()).get("ok"):
            return False
    except Exception:
        return False
    for _ in range(40):                          # 最多等 8 秒
        time.sleep(0.2)
        if not _already_running(base):
            time.sleep(0.5)
            return True
    return False


def _record_launch(mode: str, reason: str, cfg: dict):
    """寫診斷報告（data/diag/<電腦名稱>.json），其他電腦也看得到這台怎麼開的、為什麼。"""
    try:
        from backend import diag
        diag.record_launch(mode, reason, cfg)
    except Exception as e:
        print("診斷報告寫入失敗：%r" % e)


def _start_server(cfg: dict):
    import uvicorn
    from backend.server import app
    server = uvicorn.Server(uvicorn.Config(app, host=cfg["host"], port=cfg["port"], log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(150):
        if server.started:
            return server
        if not t.is_alive():
            break
        time.sleep(0.1)
    raise RuntimeError("伺服器啟動失敗（連接埠 %d 可能被其他程式佔用）" % cfg["port"])


# ------------------------------------------------------------------ 原生視窗

def _load_geometry() -> dict:
    try:
        g = json.loads(GEOMETRY.read_text(encoding="utf-8"))
        return g if isinstance(g, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_geometry(win, state: dict):
    try:
        g = {"maximized": state.get("maximized", False)}
        if not g["maximized"]:
            g.update(width=int(win.width), height=int(win.height), x=int(win.x), y=int(win.y))
        else:
            g.update({k: v for k, v in _load_geometry().items() if k in ("width", "height", "x", "y")})
        settings.LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        GEOMETRY.write_text(json.dumps(g), encoding="utf-8")
    except Exception as e:
        print("記不住視窗大小：%r" % e)


class WindowApi:
    """給頁面呼叫的視窗操作（window.pywebview.api.*）。底線開頭的屬性不會暴露給頁面。"""

    def __init__(self):
        self._win = None

    def close_window(self):
        if self._win:
            self._win.destroy()

    def zoom(self, direction):
        """Ctrl＋＋／－／0：1 放大、-1 縮小、2 恢復 100%。回傳新的倍率，並記住（各台電腦各自記）。"""
        if not self._win:
            return 1.0
        try:
            with _zoom_lock:
                cur = _get_zoom(self._win)
                if int(direction) == 2:
                    new = 1.0
                elif int(direction) > 0:
                    new = next((z for z in ZOOM_STEPS if z > cur + 0.001), ZOOM_STEPS[-1])
                else:
                    new = next((z for z in reversed(ZOOM_STEPS) if z < cur - 0.001), ZOOM_STEPS[0])
                _set_zoom(self._win, new)
                _remember_zoom(new)
            return new
        except Exception as e:
            print("縮放失敗：%r" % e)
            return 0

    def remember_zoom(self):
        """用 Ctrl＋滑鼠滾輪縮放時，頁面通知這裡把目前倍率記下來（下次開啟沿用）。"""
        if not self._win:
            return 0
        try:
            with _zoom_lock:
                z = _get_zoom(self._win)
                _remember_zoom(z)
            return z
        except Exception as e:
            print("記不住縮放：%r" % e)
            return 0


def run_windowed(cfg: dict, base: str):
    import webview

    if sys.platform == "win32":
        # 讓工作列把本程式當成獨立的應用程式（顯示新月圖示，不跟其他 Python 程式擠在一起）
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    server = _start_server(cfg)
    from backend import server as srv, claude_runner

    geo = _load_geometry()
    first = {"done": False}

    def create(params=None):
        url = base + (("?" + urllib.parse.urlencode(params)) if params else "")
        api = WindowApi()
        kw = dict(width=geo.get("width", 1440), height=geo.get("height", 900), min_size=(900, 600),
                  js_api=api, text_select=True, zoomable=True, background_color="#202124")
        if not first["done"]:                     # 第一個視窗沿用上次的位置與大小
            first["done"] = True
            # 這台電腦第一次開（還沒記過大小）就放到最大；之後沿用上次關閉時的狀態
            kw.update(x=geo.get("x"), y=geo.get("y"), maximized=bool(geo.get("maximized", not geo)))
        win = webview.create_window(TITLE, url, **kw)
        api._win = win
        state = {"maximized": bool(kw.get("maximized"))}
        win.events.maximized += lambda: state.update(maximized=True)
        win.events.restored += lambda: state.update(maximized=False)
        win.events.closing += lambda: _save_geometry(win, state)

        def restore_zoom():                       # 開窗後套用上次的縮放倍率
            z = _saved_zoom()
            if abs(z - 1.0) > 0.001:
                try:
                    _set_zoom(win, z)
                except Exception as e:
                    print("無法套用縮放：%r" % e)
        win.events.loaded += restore_zoom
        return win

    srv.WINDOW_HOOK["new"] = lambda params: create(params)     # 「開新視窗」與第二次啟動都走這裡
    create({"case": _arg("case")} if _arg("case") else None)
    webview.start(gui="edgechromium", private_mode=False,
                  storage_path=str(settings.LOCAL_DIR / "webview"), icon=ICON)

    # 所有視窗都關了：停掉還在跑的 Claude，再關伺服器
    claude_runner.stop_all()
    server.should_exit = True
    time.sleep(0.3)


def main():
    _redirect_output_if_windowless()
    _trust_windows_certs()
    cfg = settings.load()
    base = "http://%s:%d/" % (cfg["host"], cfg["port"])
    print("律法夕惕者 Xitilex — Vigilantibus, non dormientibus, iura subveniunt.")
    print("案件根目錄 :", cfg["root"])
    print("Claude CLI :", cfg["claude_bin"] or "（找不到）")

    if "--no-browser" in sys.argv:              # 只跑伺服器（開發測試用）
        import uvicorn
        from backend.server import app
        uvicorn.run(app, host=cfg["host"], port=cfg["port"], log_level="warning")
        return

    if _already_running(base):                  # 已經開著：請它再開一個視窗就好
        params = {"params": {"case": _arg("case")} if _arg("case") else {}}
        try:
            req = urllib.request.Request(base + "api/window/new", data=json.dumps(params).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            ok = json.loads(urllib.request.urlopen(req, timeout=5).read()).get("ok")
        except Exception:
            ok = False
        if ok:
            return
        # 已開著的是瀏覽器模式（關掉瀏覽器，背景伺服器也不會結束）。這次能開原生視窗的話，
        # 請舊的伺服器結束，由這次接手；不能的話照舊用瀏覽器開。
        if "--browser" in sys.argv or not _webview_available() or not _handover(base):
            import webbrowser
            webbrowser.open(base)
            return

    reason = ""
    if "--browser" in sys.argv:
        reason = "以 --browser 參數啟動（除錯模式）"
    else:
        try:
            import webview  # noqa: F401
        except ImportError as e:
            reason = "這台電腦沒有安裝原生視窗元件 pywebview（%s）" % e
            print(reason)
            _message("這台電腦還沒裝好「原生視窗元件」（pywebview），這次先用瀏覽器開啟。\n\n"
                     "請到程式資料夾雙擊「安裝.exe」補裝，之後就會用獨立視窗開啟。")
        else:
            try:
                _record_launch("原生視窗", "", cfg)
                run_windowed(cfg, base)
                return
            except Exception as e:
                reason = "原生視窗開不起來：%r" % e
                _message("原生視窗開不起來，改用瀏覽器開啟。\n\n原因：%r" % e)

    # 瀏覽器模式（備用）
    import webbrowser
    _record_launch("瀏覽器", reason, cfg)
    server = _start_server(cfg)
    from backend import server as srv
    srv.WINDOW_HOOK["quit"] = lambda: setattr(server, "should_exit", True)   # 讓之後的原生視窗接手
    webbrowser.open(base)
    print("開啟網址：", base, "（關掉這個視窗就等於關閉系統）")
    try:
        while not server.should_exit:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _message("律法夕惕者無法啟動：\n\n%r" % e)
        raise
