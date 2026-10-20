"""Append-only, hash-chained JSON-lines log with server time.

Each entry stores the hash of the previous entry, so editing or deleting any
line breaks the chain and `verify()` reports where. Used for the audit log
and for the sandbox ledger journal.
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

GENESIS = "0" * 64
MAX_TEXT = 600


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _trim(value: Any) -> Any:
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else value[:MAX_TEXT] + "…"
    if isinstance(value, dict):
        return {str(k): _trim(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_trim(v) for v in value][:50]
    return value


class ChainedLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_hash, self._count = self._scan_tail()

    def _scan_tail(self):
        if not self.path.exists():
            return GENESIS, 0
        last, count = GENESIS, 0
        with open(self.path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = json.loads(line)["hash"]
                    count += 1
        return last, count

    def append(self, event: str, actor: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            entry = {
                "seq": self._count + 1,
                "time_utc": utc_now(),
                "event": event,
                "actor": actor,
                **_trim(fields),
                "prev_hash": self._last_hash,
            }
            entry["hash"] = sha256(canonical(entry))
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(canonical(entry) + "\n")
                handle.flush()
            self._last_hash = entry["hash"]
            self._count += 1
            return entry

    def entries(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        return rows[-limit:] if limit else rows

    def verify(self) -> Dict[str, Any]:
        prev = GENESIS
        rows = self.entries()
        for i, row in enumerate(rows, start=1):
            body = {k: v for k, v in row.items() if k != "hash"}
            if row.get("prev_hash") != prev or sha256(canonical(body)) != row.get("hash") or row.get("seq") != i:
                return {"ok": False, "count": len(rows), "broken_at": i}
            prev = row["hash"]
        return {"ok": True, "count": len(rows), "broken_at": None, "last_hash": prev}

    def count(self) -> int:
        return self._count
