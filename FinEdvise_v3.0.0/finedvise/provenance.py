"""Provenance: every number the app shows carries where it came from.

A Metric holds the value, a badge (VERIFIED / ASSUMED / SIMULATED /
ILLUSTRATIVE), the formula, the inputs and a worked line with the actual
numbers, so the UI can show "click to inspect" details generated from code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict

BADGES = ("VERIFIED", "ASSUMED", "SIMULATED", "ILLUSTRATIVE")

BADGE_MEANING = {
    "VERIFIED": {
        "en": "From the reconciled (sandbox) ledger or a dated public source.",
        "bn": "মেলানো (স্যান্ডবক্স) লেজার বা তারিখসহ প্রকাশ্য উৎস থেকে।",
    },
    "ASSUMED": {
        "en": "An estimate or policy the owner set or must confirm.",
        "bn": "মালিকের ঠিক করা বা নিশ্চিত করতে হবে এমন অনুমান বা নীতি।",
    },
    "SIMULATED": {
        "en": "Calculated by the engine for a scenario; not a record.",
        "bn": "কোনো পরিস্থিতির জন্য ইঞ্জিনের হিসাব; আসল রেকর্ড নয়।",
    },
    "ILLUSTRATIVE": {
        "en": "A placeholder to confirm before use (for example a lender's terms).",
        "bn": "ব্যবহারের আগে নিশ্চিত করতে হবে এমন নমুনা মান (যেমন ঋণদাতার শর্ত)।",
    },
}


@dataclass
class Metric:
    key: str
    value: Any
    unit: str
    badge: str
    label_en: str
    label_bn: str
    formula: str = ""
    worked: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    note_en: str = ""
    note_bn: str = ""

    def __post_init__(self) -> None:
        if self.badge not in BADGES:
            raise ValueError(f"unknown badge {self.badge!r}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def money(value: float) -> float:
    """Round a taka amount to whole taka (half away from zero), kept as a float."""
    if value >= 0:
        return float(int(value + 0.5))
    return -float(int(-value + 0.5))


def fmt_int(value: float) -> str:
    """International grouping used in formula text: 220000 -> '220,000'."""
    return f"{money(value):,.0f}"
