"""Replace student and guardian names and phone numbers with codes.

Applied to everything sent to an outside model. The owner's screen shows the
real names again (re-identified locally); the model only ever sees codes.
Known limit: a name that is not in the roster cannot be recognised.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

PHONE_RE = re.compile(r"(?:\+?88)?0\d{3,4}[- ]?\d{3}[- ]?\d{3,4}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class Pseudonymizer:
    def __init__(self, roster: List[Dict[str, Any]]) -> None:
        pairs: List[Tuple[str, str]] = []
        for student in roster:
            sid = student["id"]
            gid = "GRD-" + sid.split("-", 1)[1]
            pairs.append((student["name"], sid))
            pairs.append((student["guardian"], gid))
            first = student["name"].split()[0]
            if len(first) >= 4:
                pairs.append((first, sid))
        # longest names first so "Ayaan Rahman" is replaced before "Ayaan"
        self._to_code = sorted(pairs, key=lambda p: -len(p[0]))
        self._to_name = {}
        for name, code in pairs:
            self._to_name.setdefault(code, name)
        for student in roster:
            gid = "GRD-" + student["id"].split("-", 1)[1]
            self._to_name[student["id"]] = student["name"]
            self._to_name[gid] = student["guardian"]

    def mask(self, text: str) -> str:
        if not text:
            return text
        out = EMAIL_RE.sub("[EMAIL]", text)
        out = PHONE_RE.sub("[PHONE]", out)
        for name, code in self._to_code:
            out = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", code, out, flags=re.IGNORECASE)
        return out

    def mask_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.mask(obj)
        if isinstance(obj, dict):
            return {k: self.mask_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.mask_obj(v) for v in obj]
        return obj

    def unmask(self, text: str) -> str:
        if not text:
            return text
        return re.sub(r"\b(?:STU|GRD)-\d{3}\b", lambda m: self._to_name.get(m.group(0), m.group(0)), text)

    def leaks(self, text: str) -> List[str]:
        """Names or phone numbers still present (used by tests and the red-team)."""
        found = [name for name, _ in self._to_code if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE)]
        found += PHONE_RE.findall(text)
        return found
