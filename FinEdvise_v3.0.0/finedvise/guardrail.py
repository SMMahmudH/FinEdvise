"""Output guardrail: every number in an answer must come from a tool result.

The check reads English and Bengali text, Latin and Bengali digits, lakh
grouping (1,10,000), words such as 'lakh'/'লাখ'/'হাজার'/'k', and percentages.
Dates, week labels, ordinals, record IDs and list markers are not treated as
figures. Numbers the user typed in the question may be repeated.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Set

from .fmt import LATIN_DIGITS

MONTH_WORDS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|জানুয়ারি|ফেব্রুয়ারি|মার্চ|এপ্রিল|মে|জুন|জুলাই|আগস্ট|সেপ্টেম্বর|অক্টোবর|নভেম্বর|ডিসেম্বর"
)

# Patterns removed before numbers are read (they are not figures).
EXCLUDE_PATTERNS = [
    r"\b\d{4}-\d{2}-\d{2}\b",                                     # ISO dates
    r"\b(?:[A-Z]{1,6}-)+\d+[A-Za-z0-9-]*\b",                      # IDs: P-0001, STU-003, F-12
    rf"\b\d{{1,2}}(?:\s*[-–]\s*\d{{1,2}})?\s+(?:{MONTH_WORDS})\b",  # 1 Dec, 1-2 Dec
    rf"(?:{MONTH_WORDS})\s+\d{{1,2}}(?:st|nd|rd|th)?\b",          # Dec 1
    rf"(?:{MONTH_WORDS})\s+W\d\b",                                # Dec W1
    r"\bW\d\b|\bweek\s+\d+\b|\bwk\s*\d+\b|সপ্তাহ[\s-]*\d+",        # week labels
    r"\b\d+(?:st|nd|rd|th)\b",                                    # ordinals
    r"\d+(?:ম|য়|য়|র্থ|ষ্ঠ|তম)",                                     # Bengali ordinals (১ম, ২য়, ৪র্থ)
    r"(?m)^\s*(?:[-*•]\s*)?\d{1,2}[.)]\s",                        # list markers
    r"\b(?:19|20)\d{2}\b",                                        # years
    r"\b\d{1,2}:\d{2}\b",                                         # clock times
]

SCALES = {
    "lakh": 100_000, "lac": 100_000, "lakhs": 100_000, "লাখ": 100_000, "লক্ষ": 100_000,
    "crore": 10_000_000, "কোটি": 10_000_000,
    "k": 1_000, "thousand": 1_000, "হাজার": 1_000,
}
NUMBER_RE = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?(?:\s*(%|শতাংশ|percent|lakhs?|lac|লাখ|লক্ষ|crore|কোটি|thousand|হাজার|k)(?![A-Za-z]))?",
    re.IGNORECASE,
)
MONEY_BEFORE = re.compile(r"(৳|BDT|Tk\.?|taka)\s*$", re.IGNORECASE)
MONEY_AFTER = re.compile(r"^\s*(টাকা|taka|BDT)", re.IGNORECASE)


def to_latin(text: str) -> str:
    return text.translate(LATIN_DIGITS)


def extract_numbers(text: str) -> List[Dict[str, Any]]:
    clean = to_latin(text)
    for pattern in EXCLUDE_PATTERNS:
        clean = re.sub(pattern, lambda m: " " * len(m.group(0)), clean, flags=re.IGNORECASE)
    found = []
    for m in NUMBER_RE.finditer(clean):
        whole, frac, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
        shown = float(whole.replace(",", "") + ("." + frac if frac else ""))
        decimals = len(frac) if frac else 0
        kind = "plain"
        scale = 1
        if unit in ("%", "শতাংশ", "percent"):
            kind = "percent"
        elif unit:
            scale = SCALES.get(unit, 1)
        before = clean[max(0, m.start() - 6):m.start()]
        after = clean[m.end():m.end() + 8]
        if MONEY_BEFORE.search(before) or MONEY_AFTER.search(after):
            kind = "money"
        found.append({"raw": m.group(0).strip(), "shown": shown, "decimals": decimals, "scale": scale,
                      "kind": kind, "value": shown * scale})
    return found


def collect_numbers(obj: Any, out: Set[float] | None = None) -> Set[float]:
    """Every number inside a tool result, plus the length of every list."""
    out = set() if out is None else out
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
        out.add(abs(float(obj)))
    elif isinstance(obj, dict):
        for value in obj.values():
            collect_numbers(value, out)
    elif isinstance(obj, (list, tuple)):
        out.add(float(len(obj)))
        for value in obj:
            collect_numbers(value, out)
    elif isinstance(obj, str):
        # numbers written inside tool text (for example "fees 1 week late") also count as tool output
        for item in extract_numbers(obj):
            out.add(item["value"])
    return out


def _matches(item: Dict[str, Any], candidates: Iterable[float]) -> bool:
    shown, d, scale = item["shown"], item["decimals"], item["scale"]
    for v in candidates:
        if round(v / scale, d) == shown:
            return True
        if item["kind"] == "percent" and round(v * 100, d) == shown:
            return True
        if item["kind"] == "money" and scale == 1 and d == 0 and abs(v - shown) <= 0.5:
            return True
    return False


def check(text: str, tool_results: Iterable[Any], user_text: str = "") -> Dict[str, Any]:
    allowed: Set[float] = set()
    for result in tool_results:
        collect_numbers(result, allowed)
    for item in extract_numbers(user_text or ""):
        allowed.add(item["value"])
        allowed.add(item["shown"])
    checked, unverified = [], []
    for item in extract_numbers(text):
        ok = _matches(item, allowed)
        entry = {"text": item["raw"], "kind": item["kind"], "value": item["value"], "verified": ok}
        checked.append(entry)
        if not ok:
            unverified.append(entry)
    return {
        "passed": not unverified,
        "numbers_checked": len(checked),
        "checked": checked,
        "unverified": unverified,
    }
