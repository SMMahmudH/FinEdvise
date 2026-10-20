"""Validate a fee-register CSV before anything is imported.

The register lists tuition payments already received (so already inside the
cash balance). Importing it only updates who still owes what. Every row gets
a status: accepted, held (owner must review) or rejected, with a reason in
English and Bengali. Text in the file, including the memo column, is kept as
plain data: it is never executed and never treated as an instruction.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date
from typing import Any, Dict, List

from .fmt import LATIN_DIGITS

MAX_BYTES = 1_000_000
MAX_ROWS = 2000
REQUIRED = ("date", "receipt_no", "student_id", "amount")
INSTRUCTION_HINT = re.compile(
    r"ignore|instruction|approve|pay\b|transfer|delete|system prompt|<\s*script|javascript:|অনুমোদন|পেমেন্ট|মুছে|ট্রান্সফার",
    re.IGNORECASE,
)

MESSAGES = {
    "missing_date": ("Missing date. Rejected.", "তারিখ নেই। বাতিল।"),
    "bad_date": ("Date is not in YYYY-MM-DD form. Rejected.", "তারিখ YYYY-MM-DD আকারে নয়। বাতিল।"),
    "future_date": ("Date is after the scenario date ({today}). Rejected.", "তারিখ সিনারিও তারিখের ({today}) পরে। বাতিল।"),
    "outside_period": ("Date is outside this register's period ({start} to {today}). Rejected.", "তারিখ এই রেজিস্টারের সময়ের ({start} থেকে {today}) বাইরে। বাতিল।"),
    "duplicate": ("Duplicate receipt {receipt} (same as row {first}). Skipped.", "একই রসিদ {receipt} আবার এসেছে (সারি {first})। বাদ।"),
    "unknown_student": ("Unknown student ID {sid}. Rejected.", "অজানা শিক্ষার্থী আইডি {sid}। বাতিল।"),
    "withdrawn": ("Student withdrew on {when}. Held for the owner to check (refund or wrong ID?).", "শিক্ষার্থী {when} তারিখে চলে গেছে। মালিকের যাচাইয়ের জন্য আটকে রাখা হলো (ফেরত নাকি ভুল আইডি?)।"),
    "bad_amount": ("Amount '{raw}' is not a number. Rejected.", "পরিমাণ '{raw}' সংখ্যা নয়। বাতিল।"),
    "non_positive": ("Amount must be above zero; record refunds separately. Rejected.", "পরিমাণ শূন্যের বেশি হতে হবে; ফেরত আলাদাভাবে লিখুন। বাতিল।"),
    "partial": ("Part payment: BDT {amount} of a BDT {fee} monthly fee; BDT {left} of that month is still due.", "আংশিক পরিশোধ: মাসিক {fee} টাকার মধ্যে {amount} টাকা; ওই মাসের {left} টাকা এখনো বাকি।"),
    "multi_month": ("Covers {months} months of fees.", "{months} মাসের ফি।"),
    "uneven": ("Covers {months} full months and BDT {rest} towards another month.", "{months} মাস পুরো এবং আরেক মাসের {rest} টাকা।"),
    "advance": ("More than the student's dues; BDT {extra} is an advance.", "বকেয়ার চেয়ে বেশি; {extra} টাকা অগ্রিম।"),
    "normalised": ("Amount written as '{raw}' was read as {amount}.", "পরিমাণ '{raw}' কে {amount} হিসেবে পড়া হয়েছে।"),
    "name_mismatch": ("Name '{name}' differs from the roster.", "নাম '{name}' তালিকার সাথে মেলে না।"),
    "memo_flag": ("Memo looks like an instruction. It is stored as plain text only and never acted on.", "মেমো দেখতে নির্দেশের মতো। এটি শুধু লেখা হিসেবে রাখা হলো; কখনো কার্যকর হবে না।"),
}


def _msg(code: str, **kw: Any) -> Dict[str, str]:
    en, bn = MESSAGES[code]
    return {"code": code, "en": en.format(**kw), "bn": bn.format(**kw)}


def _parse_amount(raw: str):
    text = (raw or "").translate(LATIN_DIGITS).replace(",", "").replace("৳", "").strip()
    try:
        value = float(text)
    except ValueError:
        return None, False
    return value, text != (raw or "").strip()


def validate_register(text: str, roster: List[Dict[str, Any]], scenario: date) -> Dict[str, Any]:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("file is larger than 1 MB")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    missing = [h for h in REQUIRED if h not in headers]
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")

    by_id = {s["id"]: s for s in roster}
    seen: Dict[str, int] = {}
    rows: List[Dict[str, Any]] = []
    period_start = scenario.replace(day=1)
    paid_by_student: Dict[str, float] = {}

    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            raise ValueError(f"more than {MAX_ROWS} rows")
        row = {k.strip(): (v or "").strip() for k, v in raw.items() if k}
        messages: List[Dict[str, str]] = []
        status = "accepted"
        sid = row.get("student_id", "")
        student = by_id.get(sid)

        when = None
        if not row.get("date"):
            status = "rejected"; messages.append(_msg("missing_date"))
        else:
            try:
                when = date.fromisoformat(row["date"])
            except ValueError:
                status = "rejected"; messages.append(_msg("bad_date"))
        if when and when >= scenario:
            status = "rejected"; messages.append(_msg("future_date", today=scenario.isoformat()))
        elif when and when < period_start:
            status = "rejected"; messages.append(_msg("outside_period", start=period_start.isoformat(), today=scenario.isoformat()))

        receipt = row.get("receipt_no", "")
        if receipt and receipt in seen:
            status = "rejected"; messages.append(_msg("duplicate", receipt=receipt, first=seen[receipt]))
        elif receipt:
            seen[receipt] = number

        amount, normalised = _parse_amount(row.get("amount", ""))
        if amount is None:
            status = "rejected"; messages.append(_msg("bad_amount", raw=row.get("amount", "")))
        elif amount <= 0:
            status = "rejected"; messages.append(_msg("non_positive"))
        elif normalised:
            messages.append(_msg("normalised", raw=row.get("amount", ""), amount=f"{amount:,.0f}"))

        if student is None:
            status = "rejected"; messages.append(_msg("unknown_student", sid=sid or "(blank)"))
        elif student.get("status") == "withdrawn" and status != "rejected":
            status = "held"; messages.append(_msg("withdrawn", when=student.get("withdrawn_on", "?")))

        if student and amount and amount > 0:
            if row.get("student_name") and row["student_name"].lower() != student["name"].lower():
                messages.append(_msg("name_mismatch", name=row["student_name"]))
            fee = student["monthly_fee"]
            if status == "accepted":
                if amount < fee:
                    messages.append(_msg("partial", amount=f"{amount:,.0f}", fee=f"{fee:,.0f}", left=f"{fee - amount:,.0f}"))
                elif amount % fee == 0 and amount > fee:
                    messages.append(_msg("multi_month", months=int(amount // fee)))
                elif amount % fee:
                    messages.append(_msg("uneven", months=int(amount // fee), rest=f"{amount % fee:,.0f}"))
                already = paid_by_student.get(sid, 0.0)
                if already + amount > student["dues_before_register"]:
                    extra = already + amount - student["dues_before_register"]
                    messages.append(_msg("advance", extra=f"{extra:,.0f}"))
                paid_by_student[sid] = already + amount

        memo = row.get("memo", "")
        if memo and INSTRUCTION_HINT.search(memo):
            messages.append(_msg("memo_flag"))

        rows.append({
            "row": number, "status": status, "date": row.get("date", ""), "receipt_no": receipt,
            "student_id": sid, "amount": amount if amount is not None else None,
            "method": row.get("method", ""), "month": row.get("month", ""), "memo": memo,
            "messages": messages,
        })

    accepted = [r for r in rows if r["status"] == "accepted"]
    held = [r for r in rows if r["status"] == "held"]
    rejected = [r for r in rows if r["status"] == "rejected"]
    return {
        "rows": rows,
        "summary": {
            "total_rows": len(rows),
            "accepted": len(accepted),
            "accepted_amount": float(sum(r["amount"] for r in accepted)),
            "held": len(held),
            "held_amount": float(sum(r["amount"] or 0 for r in held)),
            "rejected": len(rejected),
            "flagged_memos": sum(1 for r in rows if any(m["code"] == "memo_flag" for m in r["messages"])),
        },
        "note_en": "These payments are already in the cash balance. Importing them only updates each student's dues.",
        "note_bn": "এই টাকা ইতিমধ্যে নগদ হিসাবে আছে। ইমপোর্ট শুধু প্রত্যেক শিক্ষার্থীর বকেয়া হালনাগাদ করে।",
    }
