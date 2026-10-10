# -*- coding: utf-8 -*-
"""依範本開新案資料夾。

範本就是你原本放在「各種案件資料夾範本」裡的那幾套資料夾（一般／法扶／消債／遺產管理人），
整套複製過去、取好名字、再建一張案件卡。代號自動接續同字首的最大號（CV020 → CV021）；
陪偵、義辯這類以日期命名的類別，代號預設為今天日期。
"""
from __future__ import annotations
import datetime as dt
import re
import shutil
from collections import Counter
from pathlib import Path

from . import card, scanner

BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')
CODE_OK = re.compile(r"^([A-Z]{1,3}\d{2,4}[A-Z]?|\d{7,8})$")
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def _template_root(cfg: dict) -> Path:
    return Path(cfg["root"]) / cfg.get("template_dir", "各種案件資料夾範本")


def _default_template(group: str, names: list[str]) -> str:
    for key, kw in (("消債", "消債"), ("消費者債務", "消債"), ("遺產管理", "遺產管理"),
                    ("陪偵", "法扶"), ("義務辯護", "一般")):
        if key in group:
            hit = next((n for n in names if kw in n), None)
            if hit:
                return hit
    return next((n for n in names if "一般" in n), names[0] if names else "")


def _next_code(prefix: str, cases: list[dict]) -> str:
    nums, width = [], 3
    for c in cases:
        m = re.match(r"^%s(\d+)[A-Z]?$" % re.escape(prefix), c["code"])
        if m:
            nums.append(int(m.group(1)))
            width = max(width, len(m.group(1)))
    return "%s%0*d" % (prefix, width, (max(nums) + 1) if nums else 1)


def options(cfg: dict) -> dict:
    root = Path(cfg["root"])
    excl = set(cfg.get("exclude_dirs", [])) | set(cfg.get("closed_groups", [])) | \
        {cfg.get("template_dir", "各種案件資料夾範本")}
    cases = list(scanner.scan(cfg).values())
    tpl_root = _template_root(cfg)
    templates = sorted(p.name for p in tpl_root.iterdir() if p.is_dir()) if tpl_root.exists() else []

    groups = []
    dirs = [""] + sorted(p.name for p in root.iterdir()
                         if p.is_dir() and p.name not in excl and not p.name.startswith(".")
                         and scanner.CAT_RE.match(p.name)) if root.exists() else []
    for name in dirs:
        label = name or "（根目錄）"
        mine = [c for c in cases if c["group"] == label]
        date_n = sum(1 for c in mine if c["code"].isdigit())
        prefixes = Counter(re.match(r"[A-Z]+", c["code"]).group(0)
                           for c in mine if not c["code"].isdigit())
        mode = "date" if mine and date_n > len(mine) / 2 else "code"
        prefix = prefixes.most_common(1)[0][0] if prefixes else ""
        groups.append({"dir": name, "label": label, "mode": mode, "prefix": prefix,
                       "count": len(mine),
                       "suggest": dt.date.today().strftime("%Y%m%d") if mode == "date"
                       else (_next_code(prefix, cases) if prefix else ""),
                       "template": _default_template(name, templates)})
    prefixes = sorted({re.match(r"[A-Z]+", c["code"]).group(0) for c in cases if not c["code"].isdigit()})
    return {"groups": groups, "templates": templates,
            "next_by_prefix": {p: _next_code(p, cases) for p in prefixes},
            "statuses": cfg["statuses"]}


def create(cfg: dict, group_dir: str, template: str, code: str, client: str,
           cause: str, status: str, retained: str, opponent: str = "") -> dict:
    code, client, cause = code.strip().upper(), client.strip(), cause.strip()
    if not CODE_OK.match(code):
        raise ValueError("代號格式不對，應像 CV021、LB042A 或 20261005")
    if not client:
        raise ValueError("請填當事人")
    for label, v in (("當事人", client), ("案由", cause)):
        if BAD_CHARS.search(v):
            raise ValueError("%s不能含有 \\ / : * ? \" < > | 這些字元" % label)
    if "-" in client:
        raise ValueError("當事人名稱不能含有「-」（資料夾名稱用它分隔代號、當事人、案由）")
    for label, v in (("當事人", client), ("案由", cause)):
        if v and v[-1] in ". ":
            raise ValueError("%s的結尾不能是句點或空白（Windows 會自動拿掉，造成資料夾名稱對不上）" % label)
    if client.upper().split(".")[0] in WIN_RESERVED:
        raise ValueError("「%s」是 Windows 保留名稱，不能用" % client)

    root = Path(cfg["root"])
    parent = root / group_dir if group_dir else root
    rr, pr = root.resolve(), parent.resolve()
    if not parent.is_dir() or (pr != rr and pr.parent != rr):
        raise ValueError("找不到要放的類別資料夾")
    clash = [c for c in scanner.scan(cfg, force=True).values() if c["code"] == code]
    if clash and not code.isdigit():
        raise ValueError("代號 %s 已經用過了：%s" % (code, clash[0]["rel"]))

    name = "-".join(x for x in (code, client, cause) if x)
    dest = parent / name
    if dest.exists():
        raise ValueError("資料夾已存在：%s" % dest.name)

    src = _template_root(cfg) / template if template else None
    if src and src.is_dir():
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns("desktop.ini", "~$*", ".*"))
    else:
        dest.mkdir(parents=True)

    meta = {"案件狀態": status if status in cfg["statuses"] else "進行中",
            "委任日": retained or dt.date.today().isoformat()}
    if opponent.strip():
        meta["對造"] = opponent.strip()
    card.write(dest / cfg["card_name"], meta, [], [], " ".join(x for x in (code, client, cause) if x))
    scanner.scan(cfg, force=True)
    return {"id": scanner.case_id(str(dest.relative_to(root))), "path": str(dest), "name": name}
