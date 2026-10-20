"""Load and check the single data source (data/school.json).

Everything else in the app is calculated from this file. The checks here fail
loudly if the file stops adding up, so a typo cannot quietly change a result.
"""
from __future__ import annotations

import copy
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

from .provenance import Metric, fmt_int, money

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SCHOOL_FILE = DATA_DIR / "school.json"
CATALOGUE_FILE = DATA_DIR / "financing_catalogue.json"

RECEIPT_CATEGORIES = {
    "tuition", "tuition_arrears", "exam_fee", "session_fee_existing",
    "admission_new", "merchandise", "wallet_settlement", "loan_proceeds",
}
PAYMENT_CATEGORIES = {
    "payroll", "rent", "utilities", "refreshments", "teaching_supplies",
    "routine_printing", "exam_paper_printing", "maintenance",
    "books_and_diaries", "events", "admission_campaign", "loan_repayment",
}
LINE_STATUSES = {"expected", "committed"}

CATEGORY_LABELS = {
    "tuition": ("Tuition", "টিউশন"),
    "tuition_arrears": ("Late tuition", "বকেয়া টিউশন"),
    "exam_fee": ("Exam fees", "পরীক্ষার ফি"),
    "session_fee_existing": ("Session fees (existing students)", "সেশন ফি (বর্তমান শিক্ষার্থী)"),
    "admission_new": ("New admissions", "নতুন ভর্তি"),
    "merchandise": ("Diaries, ties, uniforms", "ডায়েরি, টাই, ইউনিফর্ম"),
    "wallet_settlement": ("bKash settlement", "বিকাশ সেটেলমেন্ট"),
    "loan_proceeds": ("Loan received", "ঋণ প্রাপ্তি"),
    "payroll": ("Salaries", "বেতন"),
    "rent": ("Rent", "ভাড়া"),
    "utilities": ("Utilities", "বিল"),
    "refreshments": ("Refreshments", "চা-নাস্তা"),
    "teaching_supplies": ("Teaching supplies", "শিক্ষা উপকরণ"),
    "routine_printing": ("Printing", "ছাপা"),
    "exam_paper_printing": ("Exam paper and printing", "পরীক্ষার কাগজ ও ছাপা"),
    "maintenance": ("Repairs and maintenance", "মেরামত"),
    "books_and_diaries": ("Books and diaries", "বই ও ডায়েরি"),
    "events": ("Events", "অনুষ্ঠান"),
    "admission_campaign": ("Admission campaign", "ভর্তি প্রচারণা"),
    "loan_repayment": ("Loan repayment", "ঋণ পরিশোধ"),
}


class DataError(ValueError):
    """Raised when the data file is inconsistent."""


def load_json(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_school(path: Path | None = None) -> Dict[str, Any]:
    data = load_json(path or SCHOOL_FILE)
    problems = validate_school(data)
    if problems:
        raise DataError("; ".join(problems))
    return data


def load_catalogue(path: Path | None = None) -> Dict[str, Any]:
    return load_json(path or CATALOGUE_FILE)


def clone(data: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(data)


def _is_amount(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def validate_school(data: Dict[str, Any]) -> List[str]:
    """Return a list of problems (empty when the file is consistent)."""
    problems: List[str] = []
    try:
        scenario = date.fromisoformat(data["meta"]["scenario_date"])
        start = date.fromisoformat(data["forecast"]["start_date"])
        weeks = int(data["forecast"]["weeks"])
    except (KeyError, ValueError, TypeError) as exc:
        return [f"meta/forecast header invalid: {exc}"]
    if start != scenario:
        problems.append("forecast.start_date must equal meta.scenario_date")
    end = start + timedelta(days=7 * weeks - 1)

    seen = set()
    for line in data["forecast"]["lines"]:
        lid = line.get("id")
        if lid in seen:
            problems.append(f"duplicate line id {lid}")
        seen.add(lid)
        try:
            when = date.fromisoformat(line["date"])
        except (KeyError, ValueError):
            problems.append(f"{lid}: bad date")
            continue
        if not start <= when <= end:
            problems.append(f"{lid}: date {when} outside forecast window {start}..{end}")
        if line.get("type") == "receipt":
            if line.get("category") not in RECEIPT_CATEGORIES:
                problems.append(f"{lid}: unknown receipt category {line.get('category')}")
        elif line.get("type") == "payment":
            if line.get("category") not in PAYMENT_CATEGORIES:
                problems.append(f"{lid}: unknown payment category {line.get('category')}")
        else:
            problems.append(f"{lid}: type must be receipt or payment")
        if line.get("status") not in LINE_STATUSES:
            problems.append(f"{lid}: status must be expected or committed")
        if not _is_amount(line.get("amount")):
            problems.append(f"{lid}: amount must be a non-negative number")

    for line in data["november_to_date_actuals"]:
        lid = line.get("id")
        if lid in seen:
            problems.append(f"duplicate line id {lid}")
        seen.add(lid)
        when = date.fromisoformat(line["date"])
        if not (scenario.replace(day=1) <= when < scenario):
            problems.append(f"{lid}: month-to-date actual must fall before the scenario date")
        if not _is_amount(line.get("amount")):
            problems.append(f"{lid}: amount must be a non-negative number")

    pos = data["opening_position"]
    for key in ("cash_in_hand", "bank", "bkash_available"):
        if not _is_amount(pos.get(key)):
            problems.append(f"opening_position.{key} must be a non-negative number")
    if date.fromisoformat(pos["as_of"]) != scenario:
        problems.append("opening_position.as_of must equal the scenario date")

    reserve = data["reserve_policy"].get("minimum_reserve")
    if not _is_amount(reserve):
        problems.append("reserve_policy.minimum_reserve must be a non-negative number")

    for plan in data["plans"]:
        for item in plan["items"]:
            flex = item.get("flex")
            if flex and not 1 <= int(flex["pay_week"]) <= weeks:
                problems.append(f"{item['id']}: flex.pay_week outside the horizon")

    # The month-to-date actuals must bridge October's closing cash to C_0.
    if not problems:
        ledger = monthly_ledger(data)
        oct_close = ledger[-1]["closing_cash"]
        mtd = month_to_date(data)
        c0 = opening_cash(data).value
        if money(oct_close + mtd["net"]) != money(c0):
            problems.append(
                f"October closing cash {oct_close} + 1-14 Nov net {mtd['net']} does not equal C_0 {c0}"
            )
    return problems


# --------------------------------------------------------------------------
# Derived figures
# --------------------------------------------------------------------------

def scenario_date(data: Dict[str, Any]) -> date:
    return date.fromisoformat(data["meta"]["scenario_date"])


def opening_cash(data: Dict[str, Any]) -> Metric:
    pos = data["opening_position"]
    total = pos["cash_in_hand"] + pos["bank"] + pos["bkash_available"]
    pending = pos.get("bkash_pending", {}).get("amount", 0)
    return Metric(
        key="opening_cash",
        value=money(total),
        unit="BDT",
        badge="VERIFIED",
        label_en="Cash you can use today (C_0)",
        label_bn="আজ ব্যবহারযোগ্য নগদ (C_0)",
        formula="C_0 = cash in hand + bank + settled bKash balance",
        worked=f"{fmt_int(pos['cash_in_hand'])} + {fmt_int(pos['bank'])} + {fmt_int(pos['bkash_available'])} = {fmt_int(total)}",
        inputs={
            "cash_in_hand": pos["cash_in_hand"],
            "bank": pos["bank"],
            "bkash_available": pos["bkash_available"],
            "bkash_pending_not_counted": pending,
        },
        source=pos.get("source_en", ""),
        note_en="Unpaid fees and bKash money that has not settled yet are not counted as cash.",
        note_bn="অপরিশোধিত ফি এবং এখনো সেটেল না হওয়া বিকাশের টাকা নগদ হিসেবে ধরা হয়নি।",
    )


def billable_tuition(data: Dict[str, Any]) -> Metric:
    fees = data["fees"]
    students = data["profile"]["active_students"]
    sch = fees["scholarships"]
    gross = students * fees["monthly_tuition"]
    waived = sch["students"] * sch["monthly_waiver_per_student"]
    return Metric(
        key="billable_tuition",
        value=money(gross - waived),
        unit="BDT",
        badge="VERIFIED",
        label_en="Tuition billed each month",
        label_bn="প্রতি মাসে টিউশন বিল",
        formula="students x monthly tuition - scholarship students x monthly waiver",
        worked=(
            f"{students} x {fmt_int(fees['monthly_tuition'])} - {sch['students']} x "
            f"{fmt_int(sch['monthly_waiver_per_student'])} = {fmt_int(gross - waived)}"
        ),
        inputs={
            "active_students": students,
            "monthly_tuition": fees["monthly_tuition"],
            "scholarship_students": sch["students"],
            "monthly_waiver_per_student": sch["monthly_waiver_per_student"],
        },
        source="data/school.json: profile, fees",
        note_en=sch["note_en"],
        note_bn=sch["note_bn"],
    )


def monthly_ledger(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Jan-Oct 2026 actuals with opening/closing cash and outstanding tuition computed."""
    block = data["monthly_actuals_2026"]
    opening = float(block["opening_cash_jan"])
    outstanding = float(block["outstanding_tuition_opening_jan"])
    rows = []
    for m in block["months"]:
        inflow = m["tuition_collected"] + m["session_and_admission"] + m["exam_fees"] + m["merchandise"]
        outflow = m["fixed_costs"] + m["exam_paper_printing"] + m["admission_campaign"] + m["events_repairs_merch"]
        closing = opening + inflow - outflow
        outstanding = max(0.0, outstanding + m["tuition_billed"] - m["tuition_collected"])
        rows.append({
            **m,
            "status": "ACTUAL",
            "opening_cash": money(opening),
            "total_inflow": money(inflow),
            "total_outflow": money(outflow),
            "net": money(inflow - outflow),
            "closing_cash": money(closing),
            "outstanding_tuition": money(outstanding),
            "collection_ratio": round(m["tuition_collected"] / m["tuition_billed"], 4) if m["tuition_billed"] else None,
        })
        opening = closing
    return rows


def month_to_date(data: Dict[str, Any]) -> Dict[str, Any]:
    lines = data["november_to_date_actuals"]
    receipts = sum(line["amount"] for line in lines if line["type"] == "receipt")
    payments = sum(line["amount"] for line in lines if line["type"] == "payment")
    tuition = sum(line["amount"] for line in lines if line["type"] == "receipt" and line["category"] == "tuition")
    return {"receipts": money(receipts), "payments": money(payments), "net": money(receipts - payments), "tuition": money(tuition)}


def outstanding_tuition(data: Dict[str, Any]) -> Metric:
    """Tuition owed by parents on the scenario date. Never counted as cash."""
    ledger = monthly_ledger(data)
    oct_outstanding = ledger[-1]["outstanding_tuition"]
    billed = billable_tuition(data).value
    mtd = month_to_date(data)
    pending = data["opening_position"].get("bkash_pending", {}).get("amount", 0)
    paid = mtd["tuition"] + pending
    value = oct_outstanding + billed - paid
    return Metric(
        key="outstanding_tuition",
        value=money(value),
        unit="BDT",
        badge="VERIFIED",
        label_en="Tuition parents still owe (not cash)",
        label_bn="অভিভাবকদের কাছে বকেয়া টিউশন (নগদ নয়)",
        formula="dues at 31 Oct + November bill - November tuition paid so far (incl. unsettled bKash)",
        worked=f"{fmt_int(oct_outstanding)} + {fmt_int(billed)} - {fmt_int(paid)} = {fmt_int(value)}",
        inputs={
            "outstanding_31_oct": oct_outstanding,
            "november_bill": billed,
            "november_tuition_received": mtd["tuition"],
            "bkash_pending_tuition": pending,
        },
        source="data/school.json: monthly_actuals_2026, november_to_date_actuals, opening_position",
        note_en="Dues are money the school hopes to collect. They are never treated as cash in hand.",
        note_bn="বকেয়া হলো যে টাকা আদায়ের আশা আছে। এটি কখনো হাতের নগদ হিসেবে ধরা হয় না।",
    )


def reserve_amount(data: Dict[str, Any]) -> float:
    return float(data["reserve_policy"]["minimum_reserve"])


def reserve_metric(data: Dict[str, Any]) -> Metric:
    policy = data["reserve_policy"]
    return Metric(
        key="minimum_reserve",
        value=money(policy["minimum_reserve"]),
        unit="BDT",
        badge="ASSUMED",
        label_en="Minimum reserve (owner policy)",
        label_bn="ন্যূনতম রিজার্ভ (মালিকের নীতি)",
        formula="Set by the owner; the engine never lets a plan go below it at the end of any week.",
        worked=f"R = {fmt_int(policy['minimum_reserve'])} ({policy['status']})",
        inputs={"status": policy["status"]},
        source="data/school.json: reserve_policy (owner-adjustable in Settings)",
        note_en=policy["rationale_en"],
        note_bn=policy["rationale_bn"],
    )
