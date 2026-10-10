# -*- coding: utf-8 -*-
"""驅動本機 Claude Code CLI（headless），工作目錄設在該案件資料夾。

沿用 casemgr/backend/claude_bridge.py 已實測可行的做法：
  * 子行程以 thread + queue 讀取（Windows 上 asyncio 子行程不可靠）
  * 洗掉父行程繼承的 CLAUDE_* / ANTHROPIC_BASE_URL 等變數
  * 認證失敗時多半是 ~/.claude/.credentials.json 變空殼，
    要開一般 PowerShell 執行 `claude` 重新登入（見 README）
"""
from __future__ import annotations
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

_INHERIT_BLOCK = ("CLAUDE", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN",
                  "ANTHROPIC_CUSTOM_HEADERS", "AI_AGENT", "BAGGAGE",
                  # 從 Claude Code 工作階段裡啟動本系統時會繼承到；會讓雲端連接器改成
                  # 非同步載入，Claude 開工時還看不到它們
                  "MCP_CONNECTION_NONBLOCKING", "MCP_SERVER_CONNECTION_BATCH_SIZE")

_running: dict[str, subprocess.Popen] = {}

MODELS = ["", "fable", "opus", "sonnet", "haiku"]            # "" = Claude Code 預設
EFFORTS = ["", "low", "medium", "high", "xhigh", "max"]

CARD_RULES = """案件狀態、庭期與待辦事項記在各案資料夾的「{card_name}」（Markdown＋YAML frontmatter）。
要更新時直接編輯這個檔，並嚴守格式（系統會據此同步 Google 日曆）：
   - frontmatter 欄位：案件狀態（只能是 {statuses} 之一）、案件類型、案號、法院、股別、對造、委任日、釘選。
     「下次期日」由系統依庭期自動計算，不必手動改。「釘選」只有律師要求釘選時才寫「是」，否則不要寫這個欄位。
   - 「## 庭期」段每行一筆：`- YYYY-MM-DD HH:MM 事由（法庭）`，例如
     `- 2026-10-28 14:30 言詞辯論（第12法庭）`；時間不明就只寫日期。新庭期加在這裡，改期就改那一行。
   - 「## 待辦事項」段每行一條：`- [ ] YYYY-MM-DD 事項`（無期限則省略日期），完成改 `- [x]`
     不要為「出席某場庭」另立待辦——庭期本身就會進日曆；庭前要準備的事（例如提出書狀）才列待辦。
   - 案件卡若有「## 子案」段（一件案子底下有多個訴訟，例如 SP001，每行「- 子案號 對造」），
     每筆庭期與待辦的事由都要以子案號開頭，後面空一格，例如
     `- 2026-10-29 16:30 L101 續行準備程序（臺灣高等法院第4法庭）`、`- [ ] L102 民事上訴理由（三）狀定稿`。
     事由裡不必再寫對造名稱，系統會依子案表自動帶出。
   - 行尾若有 `<!--gcal:…-->` 是 Google 日曆事件編號，修改該行時務必原樣保留；新增的行不用加。
   - 其他段落（如「## 案件摘要」）可以新增或改寫
   檔案不存在時可以建立，標題列用「# 資料夾名稱（把 - 換成空格）」。
"""

CASE_PROMPT = """你是{owner}的案件管理系統「律法夕惕者」裡的助理，正在處理一件案件。
目前工作目錄就是這件案件的雲端硬碟資料夾：{case_path}
案件：{case_name}（種類：{ctype}）

規則：
1. 一律使用繁體中文與臺灣法律用語回答，工作過程中的進度說明也一樣，不要用英文。
2. {file_rule}
3. 你產出的整理文件請存成新檔，放在「Claude整理」資料夾（不存在就建立），
   檔名以日期開頭，例如「{today}-案件摘要.md」。
4. {card_rules}
5. 讀 PDF 用 Read 工具；讀 .docx 可用 py -3 搭配 python-docx。
   執行 Python 一律用 `py -3`：這台電腦的 `python`／`python3` 是 Microsoft Store 的假捷徑，一執行就失敗。
6. 回答時引用檔案請寫出相對路徑，方便律師在系統裡點開。
"""

MULTI_PROMPT = """你是{owner}的案件管理系統「律法夕惕者」裡的助理，這次要一次處理「多件案件」。
目前工作目錄是全部案件的根目錄：{root}
本次範圍：{scope_label}，共 {n} 件。
範圍內的案件清單（代號、當事人、案由、種類、狀態、釘選、下次期日、未完成待辦數、
有無案件卡、最後更動日、資料夾相對路徑）在這個檔案，請先讀它：
{index_path}

規則：
1. 一律使用繁體中文與臺灣法律用語回答，工作過程中的進度說明也一樣，不要用英文。
2. {file_rule}
3. 案件很多：先用清單判斷，需要時才打開個別案件的案件卡或資料夾；不要逐一打開所有卷宗。
   只處理範圍內的案件。
4. 彙整報告存成新檔，放在根目錄下的「{out_dir}」資料夾（不存在就建立），檔名以日期開頭，
   例如「{today}-全案盤點.md」。
5. {card_rules}
6. 回答時提到案件請寫「代號 當事人」；引用檔案請寫相對於根目錄的路徑，方便律師點開。
7. 需要寫程式統計時，執行 Python 一律用 `py -3`：這台電腦的 `python`／`python3` 是
   Microsoft Store 的假捷徑，一執行就失敗。
"""


# 「允許整理檔案」關閉時（預設）的規則
FILES_OFF_CASE = "絕對不要刪除、搬移或改名資料夾裡既有的檔案。"
FILES_OFF_MULTI = "絕對不要刪除、搬移或改名任何既有的檔案或資料夾。"
# 律師在面板上開啟「允許整理檔案」時的規則
FILES_ON = """律師這次開啟了「允許整理檔案」，可以依律師的指示刪除、搬移、改名檔案與資料夾，但必須遵守：
   (1) {where}
   (2) 動手前先列出整理計畫（哪些檔案、搬到哪裡、改成什麼名字、要刪哪些），等律師回覆同意再執行；
       律師已經講得很具體的單一動作（例如「把 A 改名為 B」）可以直接做。
   (3) 「刪除」一律改成搬到該案件資料夾裡的「_待刪除」資料夾（不存在就建立），由律師自己確認後再清掉；
       只有律師明確說「永久刪除」才真的刪。
   (4) 「{card_name}」不可刪除、改名或搬走。
   (5) 做完列出實際變更清單（原路徑 → 新路徑），方便律師核對。"""
FILES_WHERE_CASE = ("只動本案資料夾（{case_path}）裡面的東西（Obsidian 筆記庫另依下方說明）；"
                    "其他地方的檔案一律不碰，本案資料夾本身也不要改名或搬走。")
FILES_WHERE_MULTI = ("只動範圍內各案件資料夾裡面的東西（Obsidian 筆記庫另依下方說明）。案件資料夾本身改名或搬動，會讓系統把它當成另一件案件"
                     "（對話紀錄不會跟著走），除非律師明確要求，否則不要做。")
# 開啟時解除封鎖的指令（清空檔案內容、shred、git push/reset/clean 仍然封鎖）
FILE_OP_DENY_RE = re.compile(r"^(Bash|PowerShell)\((rm|rmdir|del|erase|rd|mv|move|ren|rename|unlink|"
                             r"remove-item|move-item|rename-item|ri|mi|rni) \*\)$", re.I)


def _file_rule(cfg: dict, allow: bool, multi: bool, case_path: str = "") -> str:
    if not allow:
        return FILES_OFF_MULTI if multi else FILES_OFF_CASE
    where = FILES_WHERE_MULTI if multi else FILES_WHERE_CASE.format(case_path=case_path)
    return FILES_ON.format(where=where, card_name=cfg["card_name"])


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items()
           if not any(k == b or k.startswith(b) for b in _INHERIT_BLOCK)}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _extra_prompt(cfg: dict, allow_files: bool = False) -> str:
    lines = ["", "其他可用資源與界線："]
    if cfg.get("vault_path"):
        lines.append("- 律師的 Obsidian 筆記庫在「%s」：可以讀取（案件筆記、開庭筆記、法律知識庫）作為參考，"
                     "也可以依律師的指示新增筆記、修改筆記內容。不要動 .obsidian、.claude、.claudian 等設定資料夾。"
                     % cfg["vault_path"])
        if allow_files:
            lines.append("  律師勾選了「允許整理檔案」，所以筆記庫也可以依上面第 2 條的規則刪除、搬移、改名"
                         "（先列計畫、等同意；要刪的筆記搬到筆記庫最上層的「_待刪除」資料夾）。"
                         "搬移或改名筆記時，要一併更新其他筆記裡指向它的 [[連結]]，或在變更清單裡註明哪些連結需要修正。")
        else:
            lines.append("  沒有勾選「允許整理檔案」時，不要刪除、搬移、改名筆記庫裡的檔案或資料夾。")
    lines += [
        "- 可以使用 skill（例如 legal-drafter、judgment-verifier、case-summary）與已連結的連接器"
        "（判決查驗、法律檢索、Gmail、Google 日曆、Google 雲端硬碟、Claude Docs）。",
        "- Gmail 只能讀信與建立草稿，不能寄出；需要寄信時建立草稿並告訴律師，由律師自行寄出。",
        "- Google 日曆只能讀。庭期與期限請寫進案件卡，系統會自動同步到日曆，不要直接建立日曆事件。",
        "- 檔案整理權限已開啟，依上面規則第 2 條處理；清空檔案內容（Clear-Content）、shred、"
        "git push／reset／clean 仍被封鎖。" if allow_files else
        "- 不要刪除、搬移、改名任何檔案：rm、del、Remove-Item、Move-Item、Rename-Item 等指令已被封鎖，"
        "但封鎖擋不住程式碼，所以用 Python 或其他程式處理檔案時也絕對不能刪除、搬移、改名或清空既有檔案。",
    ]
    return "\n".join(lines) + "\n"


def _owner(cfg: dict) -> str:
    """使用這套系統的律師（config.json 的 owner_name，例如「王大明律師」）。"""
    return str(cfg.get("owner_name") or "律師").strip()


def _card_rules(cfg: dict) -> str:
    return CARD_RULES.format(card_name=cfg["card_name"], statuses="、".join(cfg["statuses"]))


def case_context(cfg: dict, case: dict, allow_files: bool = False) -> dict:
    return {"cwd": case["path"], "add_dirs": [], "allow_files": allow_files,
            "prompt": CASE_PROMPT.format(owner=_owner(cfg), case_path=case["path"], case_name=case["name"],
                                         ctype=case.get("ctype", ""), today=time.strftime("%Y%m%d"),
                                         card_rules=_card_rules(cfg),
                                         file_rule=_file_rule(cfg, allow_files, False, case["path"]))}


def multi_context(cfg: dict, cases: list[dict], scope_label: str, index_dir: Path,
                  allow_files: bool = False) -> dict:
    """多案模式：工作目錄設在根目錄，先產生一份範圍內的案件索引給 Claude 讀。"""
    index_dir.mkdir(parents=True, exist_ok=True)
    idx = index_dir / "案件索引.md"
    rows = ["# 案件索引（%s，共 %d 件，產生於 %s）" % (scope_label, len(cases), time.strftime("%Y-%m-%d %H:%M")),
            "", "| 代號 | 當事人 | 案由 | 種類 | 狀態 | 釘選 | 下次期日 | 未完成待辦 | 案件卡 | 最後更動 | 資料夾 |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in cases:
        cell = lambda v: str(v).replace("|", "／")
        rows.append("| %s |" % " | ".join(cell(x) for x in (
            c["code"], c["client"], c["cause"], c.get("ctype", ""), c["status"] or "未標示",
            "是" if c.get("pinned") else "", c["next_date"], c["open_todos"] or "",
            "有" if c["has_card"] else "無", time.strftime("%Y-%m-%d", time.localtime(c["mtime"])),
            c["rel"])))
    idx.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return {"cwd": cfg["root"], "add_dirs": [str(index_dir)], "allow_files": allow_files,
            "prompt": MULTI_PROMPT.format(owner=_owner(cfg), root=cfg["root"], scope_label=scope_label, n=len(cases),
                                          index_path=str(idx), out_dir="Claude整理（全案）",
                                          today=time.strftime("%Y%m%d"), card_rules=_card_rules(cfg),
                                          file_rule=_file_rule(cfg, allow_files, True))}


def build_args(cfg: dict, ctx: dict, session_id: str | None,
               model: str = "", effort: str = "") -> list[str]:
    args = [cfg["claude_bin"], "-p",
            "--output-format", "stream-json", "--verbose",
            "--include-partial-messages",
            "--permission-mode", cfg.get("claude_permission_mode", "acceptEdits"),
            "--append-system-prompt", ctx["prompt"] + _extra_prompt(cfg, bool(ctx.get("allow_files")))]
    model = model if model in MODELS else ""
    effort = effort if effort in EFFORTS else ""
    model = model or cfg.get("claude_model") or ""
    effort = effort or cfg.get("claude_effort") or ""
    if model:
        args += ["--model", model]
    if effort:
        args += ["--effort", effort]
    if session_id:
        args += ["--resume", session_id]
    dirs = list(ctx.get("add_dirs") or [])
    if cfg.get("vault_path") and Path(cfg["vault_path"]).is_dir():
        dirs.append(cfg["vault_path"])             # Obsidian 筆記庫：讀取參考用
    for d in dirs:
        args += ["--add-dir", d]
    allowed, denied = tool_rules(cfg, allow_files=bool(ctx.get("allow_files")))
    if allowed:
        args += ["--allowedTools", ",".join(allowed)]
    if denied:
        args += ["--disallowedTools", ",".join(denied)]
    return args


# ------------------------------------------------------------------ 工具權限
#
# 背景執行的 Claude 沒有「彈窗問你要不要允許」的機會：沒放行的工具一律拒絕，
# 放行的就直接執行。所以連接器逐一決定，寫入類的只開放「不會對外造成後果」的。

GMAIL_OK = {"get_message", "get_thread", "search_threads", "list_labels",
            "list_drafts", "get_draft", "create_draft", "update_draft"}       # 只讀＋草稿，不能寄
CALENDAR_OK = {"list_calendars", "list_events", "get_event", "search_events", "suggest_time"}
DRIVE_OK = {"search_files", "read_file_content", "get_file_metadata", "download_file_content",
            "list_recent_files", "get_file_permissions"}
DOCS_OK = {"batch", "create", "export", "guide", "query", "read", "update"}     # Claude Docs：不能刪

# Gmail／日曆／雲端硬碟的對外寫入工具：不論探測時有沒有看到，一律明列禁止
# （連接器若在探測當下還沒連上，或日後新增工具，也擋得住）
STATIC_DENY = {
    "gmail": ["send_message", "forward", "reply", "trash_message", "trash_thread", "delete_draft",
              "delete_label", "mark_message_spam", "mark_thread_spam"],
    "calendar": ["create_event", "update_event", "delete_event", "respond_to_event"],
    "drive": ["share_file", "trash_file", "update_file", "create_file", "copy_file"],
}

# 確認過「只做查詢」的伺服器（以顯示名稱比對），才整個放行
READONLY_SERVERS = {"judicial-tw", "claude.ai 法律偵探MCP", "claude.ai 法律偵探判決檢索"}
EXCLUDED_SERVERS = ("chatcut",)                   # 影片剪輯，與案件無關

# 不認識的伺服器：預設不放行，只開放名稱明顯是查詢的工具
READ_VERB_RE = re.compile(r"^(get|list|search|read|query|find|fetch|lookup|verify|extract|guide)(_|$)")
WRITE_WORD_RE = re.compile(r"send|forward|reply|trash|delete|remove|share|create|update|copy|move|"
                           r"post|respond|write|upload|rename|label|spam|archive|save|set|add|edit")


def mcp_server_key(name: str) -> str:
    """與 Claude Code 本身相同的伺服器名稱正規化（工具前綴 mcp__<key>__）：
    非 [A-Za-z0-9_-] 字元一律換成底線；claude.ai 連接器再把連續底線合併、去頭尾。
    例：「claude.ai Google Drive」→ claude_ai_Google_Drive；「claude.ai 法律偵探MCP」→ claude_ai_MCP"""
    name = name or ""
    key = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    if name.startswith("claude.ai "):
        key = re.sub(r"_+", "_", key).strip("_")
    return key


def _kind(display: str) -> str:
    low = (display or "").lower()
    if any(x in low for x in EXCLUDED_SERVERS):
        return "excluded"
    if display in READONLY_SERVERS:
        return "readonly"
    if display == "claude.ai Claude Docs":
        return "docs"
    for k in ("gmail", "calendar", "drive"):
        if k in low:
            return k
    return "unknown"


def _servers(caps: dict) -> list[tuple[str, str]]:
    """[(key, 顯示名稱)]，key 長的排前面（工具歸屬取最長前綴）。"""
    out = []
    for s in caps.get("mcp_servers", []) or []:
        if isinstance(s, dict) and isinstance(s.get("name"), str) and s["name"]:
            out.append((mcp_server_key(s["name"]), s["name"]))
    return sorted(out, key=lambda x: -len(x[0]))


def classify_tool(tool: str, servers: list[tuple[str, str]]) -> bool:
    """這個 MCP 工具能不能放行。歸屬不明的一律不放行。"""
    for key, display in servers:
        prefix = "mcp__%s__" % key
        if not tool.startswith(prefix):
            continue
        name = tool[len(prefix):]
        kind = _kind(display)
        if kind == "excluded":
            return False
        if kind == "readonly":
            return True
        if kind == "gmail":
            return name in GMAIL_OK
        if kind == "calendar":
            return name in CALENDAR_OK          # 庭期由案件卡同步，Claude 不直接改日曆
        if kind == "drive":
            return name in DRIVE_OK
        if kind == "docs":
            return name in DOCS_OK
        return bool(READ_VERB_RE.match(name)) and not WRITE_WORD_RE.search(name)
    return False


def mcp_tool_allowed(tool: str, caps: dict | None = None) -> bool:
    return classify_tool(tool, _servers(caps if caps is not None else load_capabilities()))


def tool_rules(cfg: dict, allow_files: bool = False) -> tuple[list[str], list[str]]:
    """回傳 (允許清單, 禁止清單)。預設不放行；只有下列才放行：
      * 確認為唯讀查詢的伺服器（判決查驗、法律偵探）：整個伺服器
      * Gmail／日曆／雲端硬碟／Claude Docs：依白名單逐項（連接器還沒連上也照樣組出全名）
      * 其他不認識的伺服器：只放行名稱明顯是查詢的工具
    Gmail／日曆／雲端硬碟的對外寫入工具另外明列禁止（禁止優先於允許）。"""
    allowed = list(cfg.get("claude_allowed_tools") or [])
    denied = list(cfg.get("claude_disallowed_tools") or [])
    if allow_files:                    # 律師開啟「允許整理檔案」：解除刪除／搬移／改名指令的封鎖
        denied = [d for d in denied if not FILE_OP_DENY_RE.match(d)]
    caps = load_capabilities()
    servers = _servers(caps)
    for t in caps.get("tools", []) or []:
        if isinstance(t, str) and t.startswith("mcp__"):
            (allowed if classify_tool(t, servers) else denied).append(t)
    for key, display in servers:
        kind = _kind(display)
        if kind == "readonly":
            allowed.append("mcp__" + key)
        elif kind in ("gmail", "calendar", "drive"):
            ok = {"gmail": GMAIL_OK, "calendar": CALENDAR_OK, "drive": DRIVE_OK}[kind]
            allowed += ["mcp__%s__%s" % (key, n) for n in sorted(ok)]
            denied += ["mcp__%s__%s" % (key, n) for n in STATIC_DENY[kind]]
        elif kind == "docs":
            allowed += ["mcp__%s__%s" % (key, n) for n in sorted(DOCS_OK)]
            denied.append("mcp__%s__delete" % key)
    return list(dict.fromkeys(allowed)), list(dict.fromkeys(denied))


# ------------------------------------------------------------------ 可用能力探測

CAPS_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "casedesk" / "claude" / "capabilities.json"


def load_capabilities() -> dict:
    try:
        d = json.loads(CAPS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    d["tools"] = [t for t in d.get("tools") or [] if isinstance(t, str)] if isinstance(d.get("tools"), list) else []
    d["mcp_servers"] = [s for s in d.get("mcp_servers") or [] if isinstance(s, dict)] \
        if isinstance(d.get("mcp_servers"), list) else []
    d["skills"] = [x for x in d.get("skills") or [] if isinstance(x, str)] if isinstance(d.get("skills"), list) else []
    return d


def probe_capabilities(cfg: dict, cwd: str) -> dict:
    """實際叫一次 Claude（Haiku、最低強度、只回一個字），讀出可用的 skill、MCP、工具，
    同時確認登入是否有效。結果存成快取，之後每次執行都用它決定放行哪些連接器工具。"""
    out = {"at": time.time(), "ok": False, "error": "", "skills": [], "mcp_servers": [], "tools": []}
    args = [cfg["claude_bin"], "-p", "--output-format", "stream-json", "--verbose",
            "--model", "haiku", "--effort", "low", "--max-turns", "1"]
    try:
        p = subprocess.run(args, cwd=cwd, env=child_env(), input="只回覆：OK", capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=180,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        out["error"] = "無法啟動 Claude：%s" % e
        return out
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            out["skills"] = ev.get("skills", [])
            out["tools"] = ev.get("tools", [])
            out["mcp_servers"] = [{"name": m.get("name"), "status": m.get("status")}
                                  for m in ev.get("mcp_servers", [])]
        elif ev.get("type") == "result":
            out["ok"] = not ev.get("is_error")
            if ev.get("is_error"):
                out["error"] = ev.get("result") or "執行失敗"
    if not out["ok"] and not out["error"]:
        out["error"] = (p.stderr or "").strip()[-400:] or "沒有收到回應"
    if out["error"] and any(k in out["error"].lower() for k in ("login", "authenticat", "oauth", "credential")):
        out["error"] += ("\n→ 命令列 Claude 的登入失效了。請開一般 PowerShell 執行 claude，"
                         "輸入 /login 重新登入，回來按「重新檢查」即可（不必重開系統）。")
    servers = _servers(out)
    out["allowed_mcp"] = [t for t in out["tools"] if t.startswith("mcp__") and classify_tool(t, servers)]
    out["blocked_mcp"] = [t for t in out["tools"] if t.startswith("mcp__") and not classify_tool(t, servers)]
    out["server_kinds"] = {s["name"]: _kind(s["name"]) for s in out["mcp_servers"] if s.get("name")}
    if out["tools"]:                           # 有讀到工具清單才覆寫快取（登入失敗時也讀得到）
        CAPS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CAPS_FILE.with_name(CAPS_FILE.name + ".%d.tmp" % threading.get_ident())
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, CAPS_FILE)
    return out


def stream(cfg: dict, ctx: dict, prompt: str, session_id: str | None = None,
           model: str = "", effort: str = ""):
    """逐則 yield stream-json 事件；第一則是 {"type":"run","run_id":…}。"""
    if not cfg.get("claude_bin"):
        yield {"type": "error", "message": "找不到 Claude Code CLI（claude.exe）。"}
        return
    run_id = uuid.uuid4().hex[:10]
    try:
        proc = subprocess.Popen(
            build_args(cfg, ctx, session_id, model, effort), cwd=ctx["cwd"], env=child_env(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        yield {"type": "error", "message": "無法啟動 Claude：%s" % e}
        return
    _running[run_id] = proc
    yield {"type": "run", "run_id": run_id}

    q: queue.Queue = queue.Queue()

    def pump(s, tag):
        try:
            for line in s:
                q.put((tag, line))
        finally:
            q.put((tag, None))

    threading.Thread(target=pump, args=(proc.stdout, "out"), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "err"), daemon=True).start()
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass

    timeout = cfg.get("claude_timeout_sec", 900)
    done, errs, deadline = 0, [], time.time() + timeout
    try:
        while done < 2:
            if time.time() > deadline:
                _kill_tree(proc)
                yield {"type": "error", "message": "Claude 逾時（%d 秒）已中止。" % timeout}
                return
            try:
                tag, line = q.get(timeout=1.0)
            except queue.Empty:
                continue
            if line is None:
                done += 1
                continue
            if tag == "err":
                errs.append(line.rstrip())
                continue
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass
        rc = proc.wait()
        if rc not in (0, None) and run_id in _running:
            msg = "\n".join(errs[-6:]) or "結束碼 %d" % rc
            if "authenticat" in msg.lower() or "login" in msg.lower():
                msg += ("\n\n→ 多半是命令列的 Claude 登入失效。請開一般 PowerShell 執行 "
                        "`claude` 重新登入，回來再試即可（不必重開系統）。")
            yield {"type": "error", "message": msg}
    finally:
        _running.pop(run_id, None)
        # 瀏覽器重新整理或關掉分頁時，串流會被中斷而走到這裡；Claude 若還在跑就停掉，
        # 否則它會在沒人看得到、也沒辦法按停止的情況下繼續改檔案。
        if proc.poll() is None:
            _kill_tree(proc)


def _kill_tree(proc: subprocess.Popen) -> None:
    """連同 Claude 叫起的子行程（py、pandoc…）一起結束。"""
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True,
                       timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        pass
    try:
        proc.kill()
    except OSError:
        pass


def local_session_exists(session_id: str) -> bool:
    """這台電腦的 Claude Code 有沒有這個工作階段（--resume 只能接續本機的）。"""
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", session_id or ""):
        return False
    base = Path.home() / ".claude" / "projects"
    try:
        return any(base.glob("*/%s.jsonl" % session_id))
    except OSError:
        return False


def transcript_for(messages: list, current_prompt: str, limit: int = 8000) -> str:
    """把先前的對話整理成純文字（只留律師的話與 Claude 的回答，略過工具紀錄），取最後 limit 字。"""
    msgs = list(messages)
    if msgs and isinstance(msgs[-1], dict) and msgs[-1].get("role") == "user" \
            and (msgs[-1].get("text") or "").strip() == current_prompt.strip():
        msgs = msgs[:-1]                       # 這次的問題本身不算「先前」
    lines = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if m.get("role") == "user":
            lines.append("律師：" + (m.get("text") or "").strip())
        elif m.get("role") == "bot":
            text = "".join(p.get("text", "") for p in m.get("parts") or []
                           if isinstance(p, dict) and p.get("kind") == "text").strip()
            if text:
                lines.append("Claude：" + text)
    out = "\n\n".join(lines)
    return out[-limit:] if len(out) > limit else out


def stop_all() -> None:
    """程式關閉時：停掉所有還在跑的 Claude（含它叫起的子行程）。"""
    for rid in list(_running):
        stop(rid)


def stop(run_id: str) -> bool:
    proc = _running.pop(run_id, None)
    if not proc:
        return False
    _kill_tree(proc)
    return True


def credential_state() -> str:
    p = Path.home() / ".claude" / ".credentials.json"
    if not p.exists():
        return "沒有憑證檔（命令列從未登入）"
    try:
        o = json.loads(p.read_text(encoding="utf-8")).get("claudeAiOauth") or {}
    except Exception as e:
        return "憑證檔讀不到：%s" % e
    if not (o.get("accessToken") or "").strip():
        return "憑證檔是空殼——請開一般 PowerShell 執行 claude 重新登入"
    return "正常"
