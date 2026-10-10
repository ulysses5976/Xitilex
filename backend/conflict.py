# -*- coding: utf-8 -*-
"""利益衝突檢查：拿當事人、對造的名字，比對所有案件的當事人（資料夾名稱）、對造（案件卡）、
子案的對造，以及案件卡內文（摘要等）有沒有提到。

比對方式（避免「王小」誤中「王小明」這類雜訊）：
  * 先正規化：全形轉半形、去空白與標點、去掉「股份有限公司／有限公司／公司」等組織後綴。
  * 名字完全相同 → 命中；三個字以上的名字，一方包含另一方也算（例如「大發科技」與
    「大發科技股份有限公司台北分公司」）。
  * 案件卡內文只找三個字以上的名字。

© 2026 無名小律師（楊朝淵律師）. Released under the MIT License.
"""
from __future__ import annotations
import re
import unicodedata
from pathlib import Path

from . import card

SEP_RE = re.compile(r"[、,，;；/／\n]|\s{2,}|及(?=\S{2,})|與(?=\S{2,})")
SUFFIX_RE = re.compile(r"(股份有限公司|有限公司|無限公司|有限合夥|公司|\(股\)|（股）|事務所)$")
PUNCT_RE = re.compile(r"[\s　·．・\.\-－—()（）「」『』\[\]【】〔〕<>《》\"'“”‘’:：]")
DROP_RE = re.compile(r"(等\d*人|等)$")


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").strip()
    s = DROP_RE.sub("", s)
    s = PUNCT_RE.sub("", s)
    prev = None
    while prev != s:
        prev, s = s, SUFFIX_RE.sub("", s)
    return s


def split_names(text: str) -> list[str]:
    out = []
    for part in SEP_RE.split(text or ""):
        part = part.strip()
        if part and norm(part):
            out.append(part)
    return out


def same(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    return (len(a) >= 3 and a in b) or (len(b) >= 3 and b in a)


def check(names: list[str], cases: list[dict], cfg: dict, exclude: str = "") -> list[dict]:
    """每個名字回傳 {"name", "hits": [{case 摘要, "role": 當事人／對造／提及, "via": 命中的原文}]}"""
    qs = [(n, norm(n)) for n in dict.fromkeys(x.strip() for x in names if x and x.strip())]
    qs = [(n, q) for n, q in qs if q]
    out = []
    texts: dict[str, str] = {}

    def card_text(c: dict) -> str:
        if c["id"] not in texts:
            p = Path(c["path"]) / cfg["card_name"]
            try:
                texts[c["id"]] = unicodedata.normalize("NFKC", p.read_text(encoding="utf-8")) if p.exists() else ""
            except (OSError, UnicodeDecodeError):
                texts[c["id"]] = ""
        return texts[c["id"]]

    for raw, q in qs:
        hits = []
        for c in cases:
            if c["id"] == exclude:
                continue
            info = {"id": c["id"], "code": c["code"], "client": c["client"], "cause": c["cause"],
                    "status": c.get("status", ""), "ctype": c.get("ctype", ""), "rel": c["rel"]}
            role, via = None, ""
            for nm in split_names(c["client"]):
                if same(q, norm(nm)):
                    role, via = "當事人", nm
                    break
            if not role:
                for nm in split_names(c.get("opponent", "")) + [s for s in c.get("sub_parties", [])]:
                    if same(q, norm(nm)):
                        role, via = "對造", nm
                        break
            if not role and len(q) >= 3 and c.get("has_card"):
                t = card_text(c)
                if q in PUNCT_RE.sub("", t):
                    i = t.find(raw.strip()[:6])
                    role, via = "提及", (t[max(0, i - 20): i + 40].replace("\n", " ") if i >= 0 else "")
            if role:
                hits.append({**info, "role": role, "via": via})
        order = {"當事人": 0, "對造": 1, "提及": 2}
        hits.sort(key=lambda h: (order[h["role"]], h["code"]))
        out.append({"name": raw, "hits": hits})
    return out
