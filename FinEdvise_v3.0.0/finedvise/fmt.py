"""Number and date formatting for English and Bengali text.

English text uses international grouping (110,000). Bengali text uses lakh
grouping (1,10,000). Digits are always Latin on the server; the browser can
switch Bengali text to Bengali digits, and the guardrail reads both.
"""
from __future__ import annotations

from datetime import date

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
LATIN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_BN = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট",
             "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]


def group_lakh(n: int) -> str:
    sign = "-" if n < 0 else ""
    s = str(abs(int(n)))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return sign + ",".join(groups + [tail])


def group_intl(n: int) -> str:
    return f"{int(n):,}"


def _round(value: float) -> int:
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def num(value: float, lang: str) -> str:
    """Whole number with the grouping of the language."""
    n = _round(value)
    return group_lakh(n) if lang == "bn" else group_intl(n)


def bdt(value: float, lang: str) -> str:
    """Money: 'BDT 77,000' in English, '৳77,000' (lakh grouping) in Bengali."""
    text = num(value, lang)
    return f"৳{text}" if lang == "bn" else f"BDT {text}"


def pct(value: float, lang: str, decimals: int = 0) -> str:
    """value is a fraction: 0.15 -> '15%'."""
    shown = round(value * 100, decimals)
    text = f"{shown:.{decimals}f}"
    return f"{text}%"


def day_month(d: date, lang: str) -> str:
    if lang == "bn":
        return f"{d.day} {MONTHS_BN[d.month - 1]}"
    return f"{d.day} {MONTHS_EN[d.month - 1]}"


def week_label(label_en: str, lang: str) -> str:
    """'Dec W1' -> 'ডিসেম্বর সপ্তাহ-1' in Bengali (digits switched in the browser)."""
    if lang != "bn":
        return label_en
    month_abbr, wk = label_en.split(" ")
    month_bn = MONTHS_BN[MONTHS_EN.index(month_abbr)]
    return f"{month_bn} সপ্তাহ-{wk[1:]}"


def to_latin_digits(text: str) -> str:
    return text.translate(LATIN_DIGITS)
