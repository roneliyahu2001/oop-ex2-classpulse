"""Small, dependency-free text helpers shared by the summary and review services."""
from __future__ import annotations

import re
from collections import Counter

STOPWORDS = set("""
a an the and or but if then so of to in on at for with by from as is are was were be been being
it its this that these those i you he she we they me him her us them my your our their not no yes
do does did done have has had can could will would should may might must just also very really
about into over than too more most such what which who whom when where why how all any each
there here okay ok um uh like going gonna want know right well now one get got let lets
של את על עם זה זאת זו הוא היא הם הן אני אתה את אנחנו לא כן גם אבל או אם כי מה מי איך למה
יש אין כל עוד רק כמו אז שם פה היה היתה היו להיות אחד אחת שלי שלך שלו שלה אותו אותה
""".split())

_TS_LINE = re.compile(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{1,3}\s*-->.*$")
_WORD = re.compile(r"[A-Za-z֐-׿][A-Za-z֐-׿'\-]*")


def transcript_to_text(raw: str) -> str:
    """Accepts plain text, WebVTT (Zoom / Meet) or SRT and returns plain prose."""
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s == "WEBVTT" or s.isdigit() or _TS_LINE.match(s):
            continue
        if s.startswith(("NOTE", "Kind:", "Language:")):
            continue
        s = re.sub(r"<[^>]+>", "", s)  # VTT voice / styling tags
        if lines and lines[-1] == s:   # auto-captions often repeat lines
            continue
        lines.append(s)
    return " ".join(lines)


def words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text)]


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOPWORDS and len(w) > 2]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def top_keywords(text: str, n: int = 8) -> list[str]:
    return [w for w, _ in Counter(content_words(text)).most_common(n)]


def shingles(text: str, k: int = 3) -> set[tuple[str, ...]]:
    w = words(text)
    if len(w) < k:
        return {tuple(w)} if w else set()
    return {tuple(w[i:i + k]) for i in range(len(w) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)
