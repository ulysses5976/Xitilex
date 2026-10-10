# -*- coding: utf-8 -*-
"""日曆事件標題。

手機上的日曆只看得到標題開頭幾個字，所以「誰」放最前面、所內案號放最後：
    一般案件：王小明（對大發科技），出席臺北地院115勞訴88準備程序（LB999）
    有子案的案件（例如 SP001）：以子案的對造為主角、子案號在後，不再加 SP001
              甲科技（L101），續行準備程序（臺灣高等法院第4法庭）

子案寫在案件卡的「## 子案」段，每行「- 子案號 對造名稱」；庭期與待辦的事由以子案號開頭
（「L101 續行準備程序…」或「L101：…」），系統就會認出是哪個子案。
"""
from __future__ import annotations
import re

SUB_RE = re.compile(r"^\s*([A-Z]{1,3}\d{2,5}[A-Z]?)(?:[\s：:｜|、,，\-]+|(?=[^\x00-\x7f])|$)(.*)$")
AGAINST_RE = re.compile(r"[（(]對([^（）()]+)[）)]")


def split_sub(text: str, subcases: list[dict]) -> tuple[str, str, str] | None:
    """事由開頭是已登記的子案號 → (子案號, 對造名稱, 其餘事由)。"""
    m = SUB_RE.match(text or "")
    if not m:
        return None
    names = {s["code"]: s["name"] for s in subcases or []}
    if m.group(1) not in names:
        return None
    return m.group(1), names[m.group(1)], m.group(2).strip(" ，,、")


# 「（對話紀錄）」「（對帳單）」「（對保）」這類是一般詞，不是「對某某」當事人
# （刻意不列「方、白、齊、焦、應」等也是姓氏的字，免得「（對方大同）」這種真的當事人被漏掉）
NOT_PARTY_RE = re.compile(r"^(話|帳|保|照|象|價|稱|待|折|號|準|比)")


def against(text: str, opponent: str = "") -> re.Match | None:
    """找出事由裡表示對造的「（對某某）」。案件卡的「對造」欄有這個名字就一定算；
    否則排除「（對話紀錄）」這類以常見詞開頭的括號。"""
    for m in AGAINST_RE.finditer(text or ""):
        name = m.group(1).strip()
        if opponent and name and (name in opponent or opponent in name):
            return m
        if not NOT_PARTY_RE.match(name):
            return m
    return None


def strip_against(text: str, opponent: str = "") -> str:
    m = against(text, opponent)
    return (text[:m.start()] + text[m.end():]) if m else text


def subject_body(case: dict, subcases: list[dict], text: str,
                 opponent: str = "") -> tuple[str, str, str]:
    """回傳 (主角, 事由, 標題結尾的案號)。月曆畫面與日曆標題共用。"""
    text = (text or "").strip()
    sub = split_sub(text, subcases)
    if sub:
        code, name, rest = sub
        return "%s（%s）" % (name, code), rest, ""
    m = against(text, opponent)
    subject = case["client"] + ("（對%s）" % m.group(1).strip() if m else "")
    body = (text[:m.start()] + text[m.end():]).strip(" ，,") if m else text
    return subject, body, case["code"]


def event_title(case: dict, subcases: list[dict], text: str, fallback: str, done: bool = False,
                opponent: str = "") -> str:
    subject, body, code = subject_body(case, subcases, text, opponent)
    title = "%s，%s" % (subject, body or fallback)
    if code:
        title += "（%s）" % code
    return ("✓ " if done else "") + title
