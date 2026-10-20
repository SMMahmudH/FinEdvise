"""Deterministic cash-flow engine.

Conventions (see docs/TECHNICAL.md for the worked example):

* The forecast is a list of dated lines in data/school.json, grouped into
  Sunday-to-Saturday weeks.
* Week t: I_t receipts, O_t expected payments, K_t committed (fixed-price)
  payments. Inside a week, payments go out first:
      low point   L_t = C_(t-1) - O_t - K_t - spend_t
      week close  C_t = L_t + I_t
* Safe-to-Invest for money spent at the start of week k:
      STI(k) = max(0, min over t >= k of min(C_t - R, L_t))
  The C_t - R term keeps every week-end balance at or above the owner's
  reserve R (the mentor-reviewed formula). The L_t term additionally makes
  sure cash never goes below zero on a payday before that week's fees arrive.
  For the demo data the reserve term binds, so the result is BDT 77,000.
* A reserve breach (C_t < R) is reported separately from a cash shortfall
  (L_t < 0).
* Money a campaign is expected to bring in is never counted when deciding
  how much is safe to spend on that campaign.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import fmt
from .data import CATEGORY_LABELS, opening_cash, reserve_amount, scenario_date
from .provenance import Metric, fmt_int, money

OPERATING_CATEGORIES = {
    "utilities", "refreshments", "teaching_supplies", "routine_printing",
    "exam_paper_printing", "maintenance", "books_and_diaries", "events",
}
ENROLMENT_CATEGORIES = {"session_fee_existing", "admission_new"}
# Money parents pay. Only these can arrive late; bKash settlements and loan money are not fees.
FEE_CATEGORIES = {
    "tuition", "tuition_arrears", "exam_fee", "session_fee_existing", "admission_new", "merchandise",
}
CLOSURE_CATEGORIES = FEE_CATEGORIES
EPS = 0.005


# --------------------------------------------------------------------------
# Shocks
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Shocks:
    """What-if changes applied to the forecast. Never written back to records."""

    enrolment_drop_pct: float = 0.0   # re-admission session fees and new admissions fall by this share
    fee_delay_weeks: int = 0          # every fee parents pay arrives this many weeks later
    cost_increase_pct: float = 0.0    # paper and operating costs that are not yet fixed-price
    emergency_cost: float = 0.0       # one-off unplanned payment
    emergency_week: int = 1
    closure_week: int = 0             # unplanned closure (heat, flood, strike): that week's fees slip a week

    def is_base(self) -> bool:
        return self == Shocks()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]], horizon: int = 8) -> "Shocks":
        """Build from user input with range checks (raises ValueError)."""
        raw = raw or {}
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"unknown shock fields: {sorted(unknown)}")

        def number(name: str, low: float, high: float, default: float) -> float:
            value = raw.get(name, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be a number")
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
            return float(value)

        def whole(name: str, low: int, high: int, default: int) -> int:
            value = raw.get(name, default)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be a whole number")
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")
            return value

        return cls(
            enrolment_drop_pct=number("enrolment_drop_pct", 0.0, 0.9, 0.0),
            fee_delay_weeks=whole("fee_delay_weeks", 0, 4, 0),
            cost_increase_pct=number("cost_increase_pct", 0.0, 1.0, 0.0),
            emergency_cost=number("emergency_cost", 0.0, 10_000_000.0, 0.0),
            emergency_week=whole("emergency_week", 1, horizon, 1),
            closure_week=whole("closure_week", 0, horizon, 0),
        )

    def describe(self, lang: str = "en") -> List[str]:
        parts: List[str] = []
        bn = lang == "bn"
        if self.enrolment_drop_pct:
            p = fmt.pct(self.enrolment_drop_pct, lang)
            parts.append(f"2027 ভর্তি ও পুনঃভর্তি {p} কম" if bn else f"2027 enrolment {p} lower")
        if self.fee_delay_weeks:
            w = self.fee_delay_weeks
            parts.append(f"ফি {w} সপ্তাহ দেরিতে" if bn else f"fees {w} week{'s' if w > 1 else ''} late")
        if self.cost_increase_pct:
            p = fmt.pct(self.cost_increase_pct, lang)
            parts.append(f"কাগজ ও চলতি খরচ {p} বেশি" if bn else f"paper and operating costs +{p}")
        if self.emergency_cost:
            parts.append(
                f"জরুরি মেরামত {fmt.bdt(self.emergency_cost, lang)} (সপ্তাহ {self.emergency_week})" if bn
                else f"emergency repair {fmt.bdt(self.emergency_cost, lang)} in week {self.emergency_week}"
            )
        if self.closure_week:
            parts.append(
                f"সপ্তাহ {self.closure_week}-এ অপ্রত্যাশিত বন্ধ" if bn
                else f"unplanned closure in week {self.closure_week}"
            )
        if not parts:
            parts.append("মূল পূর্বাভাস" if bn else "base forecast")
        return parts


BASE = Shocks()
DOWNSIDE = Shocks(enrolment_drop_pct=0.15, fee_delay_weeks=1)
DOWNSIDE_LABEL = {
    "en": "Stress test: 2027 enrolment 15% lower and fees 1 week late",
    "bn": "স্ট্রেস টেস্ট: 2027 ভর্তি 15% কম এবং ফি 1 সপ্তাহ দেরিতে",
}


# --------------------------------------------------------------------------
# Weeks
# --------------------------------------------------------------------------

@dataclass
class Week:
    index: int
    start: date
    end: date
    label: str
    receipts: float = 0.0
    payments: float = 0.0
    committed: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "label": self.label,
            "receipts": round(self.receipts, 2),
            "payments": round(self.payments, 2),
            "committed": round(self.committed, 2),
        }


def week_label(start: date) -> str:
    """Name a Sunday-start week by the month of its Wednesday: 29 Nov-5 Dec -> 'Dec W1'."""
    mid = start + timedelta(days=3)
    return f"{fmt.MONTHS_EN[mid.month - 1]} W{math.ceil(mid.day / 7)}"


def horizon(data: Dict[str, Any]) -> Tuple[date, int]:
    fc = data["forecast"]
    return date.fromisoformat(fc["start_date"]), int(fc["weeks"])


def week_of(data: Dict[str, Any], when: date) -> int:
    start, _ = horizon(data)
    return (when - start).days // 7 + 1


def build_weeks(
    data: Dict[str, Any],
    shocks: Shocks = BASE,
    extra_lines: Iterable[Dict[str, Any]] = (),
) -> Tuple[List[Week], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Group forecast lines into weeks after applying shocks.

    Returns (weeks, lines_after_shocks, carried_past_window). Receipts pushed
    beyond the last week are reported as carried past the window, not dropped.
    """
    start, n = horizon(data)
    weeks = [
        Week(index=i + 1, start=start + timedelta(days=7 * i), end=start + timedelta(days=7 * i + 6),
             label=week_label(start + timedelta(days=7 * i)))
        for i in range(n)
    ]
    shocked: List[Dict[str, Any]] = []
    carried: List[Dict[str, Any]] = []
    lines = list(data["forecast"]["lines"]) + list(extra_lines)

    for line in lines:
        idx = week_of(data, date.fromisoformat(line["date"]))
        if not 1 <= idx <= n:
            continue
        amount = float(line["amount"])
        notes: List[str] = []
        if line["type"] == "receipt":
            if shocks.enrolment_drop_pct and line["category"] in ENROLMENT_CATEGORIES:
                amount *= 1.0 - shocks.enrolment_drop_pct
                notes.append("enrolment shock")
            delay = shocks.fee_delay_weeks if line["category"] in FEE_CATEGORIES else 0
            if shocks.closure_week and shocks.closure_week == idx and line["category"] in CLOSURE_CATEGORIES:
                delay += 1
                notes.append("closure")
            if delay:
                notes.append(f"+{delay} week")
            target = idx + delay
            row = {**line, "amount": round(amount, 2), "original_amount": line["amount"],
                   "week": target, "from_week": idx, "shock_notes": notes}
            if target > n:
                carried.append(row)
                continue
            weeks[target - 1].receipts += amount
            shocked.append(row)
        else:
            if shocks.cost_increase_pct and line.get("status") == "expected" and line["category"] in OPERATING_CATEGORIES:
                amount *= 1.0 + shocks.cost_increase_pct
                notes.append("cost shock")
            row = {**line, "amount": round(amount, 2), "original_amount": line["amount"],
                   "week": idx, "from_week": idx, "shock_notes": notes}
            if line.get("status") == "committed":
                weeks[idx - 1].committed += amount
            else:
                weeks[idx - 1].payments += amount
            shocked.append(row)

    if shocks.emergency_cost:
        w = weeks[shocks.emergency_week - 1]
        w.payments += shocks.emergency_cost
        shocked.append({
            "id": "SHOCK-EMERGENCY", "date": w.start.isoformat(), "type": "payment", "category": "maintenance",
            "amount": shocks.emergency_cost, "original_amount": 0, "status": "expected",
            "desc_en": "Emergency repair (what-if)", "desc_bn": "জরুরি মেরামত (যদি হয়)",
            "week": w.index, "from_week": w.index, "shock_notes": ["emergency shock"],
        })

    for w in weeks:
        w.receipts = round(w.receipts, 2)
        w.payments = round(w.payments, 2)
        w.committed = round(w.committed, 2)
    return weeks, shocked, carried


# --------------------------------------------------------------------------
# Cash path and Safe-to-Invest
# --------------------------------------------------------------------------

def cash_path(c0: float, weeks: List[Week], reserve: float, spends: Optional[Dict[int, float]] = None) -> List[Dict[str, Any]]:
    """Week-by-week balances. `spends` maps week index -> amount paid at the start of that week."""
    spends = spends or {}
    rows: List[Dict[str, Any]] = []
    prev_close = float(c0)
    cum_spend = 0.0
    for w in weeks:
        spend = float(spends.get(w.index, 0.0))
        cum_spend += spend
        low = prev_close - w.payments - w.committed - spend
        close = low + w.receipts
        if low < -EPS:
            status = "CASH_SHORTFALL"
        elif close < reserve - EPS:
            status = "RESERVE_BREACH"
        else:
            status = "OK"
        rows.append({
            **w.to_dict(),
            "opening": round(prev_close, 2),
            "spend": round(spend, 2),
            "cumulative_spend": round(cum_spend, 2),
            "low_point": round(low, 2),
            "closing": round(close, 2),
            "reserve": round(reserve, 2),
            "headroom": round(close - reserve, 2),
            "cash_shortfall": round(max(0.0, -low), 2),
            "reserve_gap": round(max(0.0, reserve - close), 2),
            "status": status,
        })
        prev_close = close
    return rows


def safe_to_invest(c0: float, weeks: List[Week], reserve: float, spend_week: int = 1) -> Dict[str, Any]:
    if not 1 <= spend_week <= len(weeks):
        raise ValueError("spend_week outside the horizon")
    rows = cash_path(c0, weeks, reserve)
    best: Optional[Dict[str, Any]] = None
    caps = []
    for row in rows:
        if row["index"] < spend_week:
            continue
        reserve_cap = row["closing"] - reserve
        cash_cap = row["low_point"]
        cap = min(reserve_cap, cash_cap)
        kind = "reserve" if reserve_cap <= cash_cap else "cash"
        caps.append({"week": row["index"], "label": row["label"], "reserve_cap": round(reserve_cap, 2),
                     "cash_cap": round(cash_cap, 2), "cap": round(cap, 2), "binding": kind})
        if best is None or cap < best["cap"] - EPS:
            best = {"cap": cap, "kind": kind, "row": row}
    value = max(0.0, math.floor(best["cap"] + 1e-6))
    return {"value": float(value), "binding_kind": best["kind"], "binding_row": best["row"], "caps": caps, "rows": rows}


def sti_metric(c0: float, reserve: float, result: Dict[str, Any], scenario_name: str, shocks: Shocks, spend_week: int) -> Metric:
    row = result["binding_row"]
    caps = ", ".join(fmt_int(c["cap"]) for c in result["caps"])
    if scenario_name == "base":
        label_en, label_bn, badge = "Safe to spend now (base forecast)", "এখন নিরাপদে খরচযোগ্য (মূল পূর্বাভাস)", "SIMULATED"
    else:
        label_en, label_bn, badge = "Safe to spend now (stress test)", "এখন নিরাপদে খরচযোগ্য (স্ট্রেস টেস্ট)", "SIMULATED"
    return Metric(
        key=f"safe_to_invest_{scenario_name}",
        value=result["value"],
        unit="BDT",
        badge=badge,
        label_en=label_en,
        label_bn=label_bn,
        formula="STI = max(0, min over weeks t >= k of min(C_t - R, L_t)); C_t = week-end cash, L_t = low point after the week's payments",
        worked=(
            f"min of weekly limits [{caps}] = {fmt_int(result['value'])}, set by {row['label']} "
            f"({'reserve' if result['binding_kind'] == 'reserve' else 'cash'}): "
            f"C_t {fmt_int(row['closing'])} - R {fmt_int(reserve)}"
            if result["binding_kind"] == "reserve" else
            f"min of weekly limits [{caps}] = {fmt_int(result['value'])}, set by {row['label']} (cash low point L_t {fmt_int(row['low_point'])})"
        ),
        inputs={
            "opening_cash_C0": c0,
            "reserve_R": reserve,
            "spend_week_k": spend_week,
            "binding_week": row["label"],
            "binding_week_close_C_t": row["closing"],
            "binding_week_low_point_L_t": row["low_point"],
            "scenario": shocks.describe("en"),
        },
        source="engine.safe_to_invest over data/school.json forecast lines",
        note_en="Money the campaign itself may bring in is not counted.",
        note_bn="প্রচারণা থেকে যে টাকা আসতে পারে তা ধরা হয়নি।",
    )


def scenario_view(
    data: Dict[str, Any],
    shocks: Shocks = BASE,
    commitments: Iterable[Dict[str, Any]] = (),
    spends: Optional[Dict[int, float]] = None,
    spend_week: int = 1,
) -> Dict[str, Any]:
    c0 = opening_cash(data).value
    reserve = reserve_amount(data)
    weeks, lines, carried = build_weeks(data, shocks, commitments)
    sti = safe_to_invest(c0, weeks, reserve, spend_week)
    rows = cash_path(c0, weeks, reserve, spends)
    return {
        "shocks": shocks.to_dict(),
        "shock_text": {"en": shocks.describe("en"), "bn": shocks.describe("bn")},
        "weeks": [w.to_dict() for w in weeks],
        "rows": rows,
        "lines": lines,
        "carried_past_window": carried,
        "carried_total": round(sum(c["amount"] for c in carried), 2),
        "sti": sti,
        "worst_row": min(rows, key=lambda r: (r["headroom"], r["low_point"])),
    }


# --------------------------------------------------------------------------
# Student economics: economic break-even versus cash payback
# --------------------------------------------------------------------------

def student_economics(data: Dict[str, Any]) -> Dict[str, Metric]:
    e = data["student_economics"]
    gross = e["admission_fee"] + e["session_fee"] + e["monthly_tuition"] * e["horizon_months"]
    net_revenue = round((gross - e["new_student_discount"]) * e["collection_rate"] * e["retention_probability"], 2)
    variable = e["variable_cost_books_id_diary"] + e["variable_cost_exam_materials"]
    contribution = round(net_revenue - variable, 2)
    window_fees = e["admission_fee"] + e["session_fee"] + e["monthly_tuition"] - e["new_student_discount"]
    window_cash = round(window_fees * e["collection_rate"] - e["variable_cost_books_id_diary"], 2)
    common = {k: e[k] for k in ("admission_fee", "session_fee", "monthly_tuition", "new_student_discount",
                                "collection_rate", "retention_probability", "variable_cost_books_id_diary",
                                "variable_cost_exam_materials", "horizon_months")}
    return {
        "gross_fees": Metric(
            key="gross_fees_per_student", value=money(gross), unit="BDT", badge="VERIFIED",
            label_en="Gross fees per new student (12 months)", label_bn="নতুন শিক্ষার্থীর মোট ফি (১২ মাস)",
            formula="admission + session + 12 x monthly tuition",
            worked=f"{fmt_int(e['admission_fee'])} + {fmt_int(e['session_fee'])} + 12 x {fmt_int(e['monthly_tuition'])} = {fmt_int(gross)}",
            inputs=common, source="data/school.json: student_economics",
        ),
        "net_contribution": Metric(
            key="net_contribution_per_student", value=money(contribution), unit="BDT", badge="ASSUMED",
            label_en="Net contribution per extra student (12 months)", label_bn="প্রতি অতিরিক্ত শিক্ষার্থীর নিট অবদান (১২ মাস)",
            formula="(admission + session + 12 x tuition - discount) x collection rate x retention - books/ID/diary - exam materials",
            worked=(
                f"({fmt_int(gross)} - {fmt_int(e['new_student_discount'])}) x {e['collection_rate']} x "
                f"{e['retention_probability']} - {fmt_int(e['variable_cost_books_id_diary'])} - "
                f"{fmt_int(e['variable_cost_exam_materials'])} = {fmt_int(net_revenue)} - {fmt_int(variable)} = {fmt_int(contribution)}"
            ),
            inputs=common, source="data/school.json: student_economics",
            note_en=e["method_note_en"], note_bn=e["method_note_bn"],
        ),
        "window_cash": Metric(
            key="window_cash_per_student", value=money(window_cash), unit="BDT", badge="ASSUMED",
            label_en="Cash per extra student by end of January", label_bn="জানুয়ারির শেষে প্রতি অতিরিক্ত শিক্ষার্থী থেকে নগদ",
            formula="(admission + session + first month's tuition - discount) x collection rate - books/ID/diary",
            worked=(
                f"({fmt_int(e['admission_fee'])} + {fmt_int(e['session_fee'])} + {fmt_int(e['monthly_tuition'])} - "
                f"{fmt_int(e['new_student_discount'])}) x {e['collection_rate']} - {fmt_int(e['variable_cost_books_id_diary'])} "
                f"= {fmt_int(window_fees * e['collection_rate'])} - {fmt_int(e['variable_cost_books_id_diary'])} = {fmt_int(window_cash)}"
            ),
            inputs=common, source="data/school.json: student_economics",
            note_en="This is why cash payback needs far more students than economic break-even.",
            note_bn="এ কারণেই নগদ ফেরতের জন্য অর্থনৈতিক ব্রেক-ইভেনের চেয়ে অনেক বেশি শিক্ষার্থী লাগে।",
        ),
    }


def break_even(data: Dict[str, Any], cost: float, extra_students: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
        raise ValueError("cost must be a non-negative number")
    econ = student_economics(data)
    nc = econ["net_contribution"].value
    wc = econ["window_cash"].value
    e = data["student_economics"]
    if nc <= 0:
        return {"viable": False, "reason_en": "Net contribution per student is zero or negative.",
                "reason_bn": "প্রতি শিক্ষার্থীর নিট অবদান শূন্য বা ঋণাত্মক।", "economics": {k: m.to_dict() for k, m in econ.items()}}
    econ_students = math.ceil(cost / nc) if cost > 0 else 0
    cash_students = math.ceil(cost / wc) if (cost > 0 and wc > 0) else None
    scenarios = {}
    for name, n in (extra_students or {}).items():
        contribution = n * nc
        window = n * wc
        monthly_stream = n * e["monthly_tuition"] * e["collection_rate"] * e["retention_probability"]
        if window >= cost:
            months = 0.0
        elif monthly_stream > 0:
            months = round((cost - window) / monthly_stream, 1)
        else:
            months = None
        scenarios[name] = {
            "extra_students": n,
            "economic_gain": money(contribution - cost),
            "economic_break_even_met": n >= econ_students,
            "cash_by_end_january": money(window),
            "cash_gap_end_january": money(window - cost),
            "months_after_january_to_cash_payback": months,
        }
    return {
        "viable": True,
        "cost": money(cost),
        "economics": {k: m.to_dict() for k, m in econ.items()},
        "economic_break_even": Metric(
            key="economic_break_even_students", value=econ_students, unit="students", badge="SIMULATED",
            label_en="Extra students needed to pay back the cost (12 months)",
            label_bn="খরচ উঠাতে প্রয়োজনীয় অতিরিক্ত শিক্ষার্থী (১২ মাস)",
            formula="ceil(cost / net contribution per student)",
            worked=f"ceil({fmt_int(cost)} / {fmt_int(nc)}) = {econ_students}",
            inputs={"cost": cost, "net_contribution_per_student": nc}, source="engine.break_even",
        ).to_dict(),
        "cash_payback": Metric(
            key="cash_payback_students", value=cash_students, unit="students", badge="SIMULATED",
            label_en="Extra students needed to get the cash back by end of January",
            label_bn="জানুয়ারির মধ্যে নগদ ফেরত পেতে প্রয়োজনীয় অতিরিক্ত শিক্ষার্থী",
            formula="ceil(cost / cash per extra student by end of January)",
            worked=f"ceil({fmt_int(cost)} / {fmt_int(wc)}) = {cash_students}",
            inputs={"cost": cost, "window_cash_per_student": wc}, source="engine.break_even",
        ).to_dict(),
        "scenarios": scenarios,
    }


# --------------------------------------------------------------------------
# Plans: lump sum versus staged schedule
# --------------------------------------------------------------------------

def plan_total(plan: Dict[str, Any]) -> float:
    return float(sum(item["amount"] for item in plan["items"]))


def plan_schedule(plan: Dict[str, Any], staged: bool) -> Tuple[Dict[int, float], List[Dict[str, Any]], float]:
    """Return (week -> spend, item schedule, staging cost). Lump sum pays everything in week 1."""
    spends: Dict[int, float] = {}
    items = []
    cost = 0.0
    for item in plan["items"]:
        flex = item.get("flex")
        week = int(flex["pay_week"]) if (staged and flex) else 1
        extra = round(item["amount"] * flex.get("cost_pct", 0), 2) if (staged and flex) else 0.0
        spends[week] = spends.get(week, 0.0) + item["amount"]
        cost += extra
        items.append({**item, "pay_week": week, "staging_cost": extra})
    return spends, items, round(cost, 2)


def _path_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    worst = min(rows, key=lambda r: (r["headroom"], r["low_point"]))
    breaches = [r for r in rows if r["status"] != "OK"]
    shortfall = max(rows, key=lambda r: r["cash_shortfall"])
    return {
        "ok": not breaches,
        "worst_week": worst["label"],
        "worst_headroom": worst["headroom"],
        "max_reserve_gap": max(r["reserve_gap"] for r in rows),
        "max_cash_shortfall": shortfall["cash_shortfall"],
        "shortfall_week": shortfall["label"] if shortfall["cash_shortfall"] > 0 else None,
        "problem_weeks": [{"label": r["label"], "status": r["status"], "reserve_gap": r["reserve_gap"],
                           "cash_shortfall": r["cash_shortfall"]} for r in breaches],
    }


def evaluate_plan(
    data: Dict[str, Any],
    plan: Dict[str, Any],
    staged: bool,
    stress: Shocks = DOWNSIDE,
    commitments: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    c0 = opening_cash(data).value
    reserve = reserve_amount(data)
    spends, items, staging_cost = plan_schedule(plan, staged)
    commitments = list(commitments)
    base_weeks, _, _ = build_weeks(data, BASE, commitments)
    stress_weeks, _, _ = build_weeks(data, stress, commitments)
    base_rows = cash_path(c0, base_weeks, reserve, spends)
    stress_rows = cash_path(c0, stress_weeks, reserve, spends)
    total = plan_total(plan)
    be = break_even(data, total, plan["extra_students_estimate"])
    return {
        "plan_id": plan["id"],
        "name_en": plan["name_en"],
        "name_bn": plan["name_bn"],
        "total": total,
        "staged": staged,
        "schedule": items,
        "spends_by_week": spends,
        "staging_cost": staging_cost,
        "base": _path_summary(base_rows),
        "stress": _path_summary(stress_rows),
        "base_rows": base_rows,
        "stress_rows": stress_rows,
        "economic_break_even": be["economic_break_even"]["value"],
        "cash_payback_students": be["cash_payback"]["value"],
        "extra_students_estimate": plan["extra_students_estimate"],
        "gains": {k: v["economic_gain"] for k, v in be["scenarios"].items()},
        "break_even": be,
    }


def compare_plans(data: Dict[str, Any], stress: Shocks = DOWNSIDE, commitments: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    commitments = list(commitments)
    plans = []
    for plan in data["plans"]:
        lump = evaluate_plan(data, plan, False, stress, commitments)
        staged = evaluate_plan(data, plan, True, stress, commitments)
        plans.append({"id": plan["id"], "lump_sum": lump, "staged": staged})

    safe = [p for p in plans if p["lump_sum"]["base"]["ok"]]
    best_gain = max(plans, key=lambda p: p["lump_sum"]["gains"]["base"])
    recommended = max(safe, key=lambda p: p["lump_sum"]["gains"]["base"]) if safe else None
    reason = _recommendation_reason(recommended, best_gain)
    advice = None
    if recommended:
        rec_lump = recommended["lump_sum"]
        rec_staged = recommended["staged"]
        advice = {
            "plan_id": recommended["id"],
            "lump_sum_safe_under_stress": rec_lump["stress"]["ok"],
            "staged_safe_under_stress": rec_staged["stress"]["ok"],
            "use_staged": (not rec_lump["stress"]["ok"]) and rec_staged["stress"]["ok"],
            "needs_financing": (not rec_lump["stress"]["ok"]) and (not rec_staged["stress"]["ok"]),
        }
    return {
        "stress": stress.to_dict(),
        "stress_text": {"en": stress.describe("en"), "bn": stress.describe("bn")},
        "plans": plans,
        "recommended_plan_id": recommended["id"] if recommended else None,
        "reason": reason,
        "advice": advice,
    }


def _recommendation_reason(recommended: Optional[Dict[str, Any]], best_gain: Dict[str, Any]) -> Dict[str, str]:
    if recommended is None:
        return {"en": "No plan keeps the reserve in the base forecast. Reduce the budget or schedule spending later.",
                "bn": "কোনো প্ল্যানেই মূল পূর্বাভাসে রিজার্ভ ঠিক থাকে না। বাজেট কমান বা খরচ পরে করুন।"}
    rec = recommended["lump_sum"]
    en = (f"{rec['name_en']} has the highest expected gain ({fmt.bdt(rec['gains']['base'], 'en')}, base estimate) "
          f"among plans that keep the reserve in every week of the base forecast.")
    bn = (f"মূল পূর্বাভাসে প্রতিটি সপ্তাহে রিজার্ভ ঠিক রাখে এমন প্ল্যানের মধ্যে {rec['name_bn']} প্ল্যানে প্রত্যাশিত লাভ "
          f"সবচেয়ে বেশি ({fmt.bdt(rec['gains']['base'], 'bn')}, মূল অনুমান)।")
    if best_gain["id"] != recommended["id"]:
        other = best_gain["lump_sum"]
        extra = other["gains"]["base"] - rec["gains"]["base"]
        gap = other["base"]["max_reserve_gap"]
        short = other["base"]["max_cash_shortfall"]
        week = other["base"]["worst_week"]
        en += (f" {other['name_en']} would earn {fmt.bdt(extra, 'en')} more on paper, but it breaks the reserve in "
               f"{week} by {fmt.bdt(gap, 'en')}")
        bn += (f" {other['name_bn']} প্ল্যানে কাগজে-কলমে {fmt.bdt(extra, 'bn')} বেশি লাভ, কিন্তু {fmt.week_label(week, 'bn')}-এ "
               f"রিজার্ভ {fmt.bdt(gap, 'bn')} ভাঙে")
        if short > 0:
            en += f" and leaves the school {fmt.bdt(short, 'en')} short of cash on payday"
            bn += f" এবং বেতনের দিনে {fmt.bdt(short, 'bn')} নগদ ঘাটতি হয়"
        en += ". It loses because of that, not because it earns less."
        bn += "। এ কারণেই এটি বাদ, কম লাভের জন্য নয়।"
    return {"en": en, "bn": bn}


# --------------------------------------------------------------------------
# Alerts and the "next pinch" summary
# --------------------------------------------------------------------------

def _big_payments(lines: List[Dict[str, Any]], week_index: int) -> List[Dict[str, Any]]:
    return [l for l in lines if l["type"] == "payment" and l["week"] == week_index and l["category"] in ("payroll", "rent")]


def alerts(data: Dict[str, Any], view: Dict[str, Any], scenario_name: str) -> List[Dict[str, Any]]:
    """One alert per week that breaks the reserve or runs out of cash. Generated, never typed."""
    today = scenario_date(data)
    out = []
    for row in view["rows"]:
        if row["status"] == "OK":
            continue
        pays = _big_payments(view["lines"], row["index"])
        due = min((date.fromisoformat(p["date"]) for p in pays), default=date.fromisoformat(row["start"]))
        days = (due - today).days
        if row["status"] == "CASH_SHORTFALL":
            amount = row["cash_shortfall"]
            en = (f"{row['label']} ({fmt.day_month(due, 'en')}, in {days} days): after this week's payments the school "
                  f"would be {fmt.bdt(amount, 'en')} short of cash before the week's fees arrive.")
            bn = (f"{fmt.week_label(row['label'], 'bn')} ({fmt.day_month(due, 'bn')}, {days} দিন পর): এ সপ্তাহের খরচ দেওয়ার পর "
                  f"ফি আসার আগেই {fmt.bdt(amount, 'bn')} নগদ ঘাটতি হবে।")
            severity = "critical"
        else:
            amount = row["reserve_gap"]
            en = (f"{row['label']} (week of {fmt.day_month(date.fromisoformat(row['start']), 'en')}): cash stays positive but ends "
                  f"{fmt.bdt(amount, 'en')} below your {fmt.bdt(row['reserve'], 'en')} reserve.")
            bn = (f"{fmt.week_label(row['label'], 'bn')} ({fmt.day_month(date.fromisoformat(row['start']), 'bn')} থেকে): নগদ শূন্যের "
                  f"নিচে নামে না, কিন্তু {fmt.bdt(row['reserve'], 'bn')} রিজার্ভের চেয়ে {fmt.bdt(amount, 'bn')} কম থাকে।")
            severity = "warning"
        out.append({
            "scenario": scenario_name, "type": row["status"], "severity": severity, "week": row["index"],
            "label": row["label"], "amount": amount, "due_date": due.isoformat(), "days_until": days,
            "message_en": en, "message_bn": bn,
        })
    return out


def next_pinch(data: Dict[str, Any], base: Dict[str, Any], stress: Dict[str, Any]) -> Dict[str, Any]:
    """The tightest coming week, why, and how much is safe to spend before it."""
    today = scenario_date(data)
    worst = min(base["rows"], key=lambda r: r["headroom"])
    pays = _big_payments(base["lines"], worst["index"])
    total = sum(p["amount"] for p in pays)
    start = date.fromisoformat(worst["start"])
    due = min((date.fromisoformat(p["date"]) for p in pays), default=start)
    last_due = max((date.fromisoformat(p["date"]) for p in pays), default=due)
    days = (due - today).days
    stress_row = next(r for r in stress["rows"] if r["index"] == worst["index"])
    sti_b = base["sti"]["value"]
    sti_s = stress["sti"]["value"]
    reserve = worst["reserve"]
    weeks = len(base["rows"])
    if pays:
        when_en = fmt.day_month(due, "en") if due == last_due else f"{due.day}-{fmt.day_month(last_due, 'en')}"
        when_bn = fmt.day_month(due, "bn") if due == last_due else f"{due.day}-{fmt.day_month(last_due, 'bn')}"
        head_en = (f"Salaries and rent of {fmt.bdt(total, 'en')} are due on {when_en}, {days} days from today. "
                   f"It is the tightest of the next {weeks} weeks")
        head_bn = (f"{when_bn} তারিখে {fmt.bdt(total, 'bn')} বেতন ও ভাড়া দিতে হবে, আজ থেকে {days} দিন পর। "
                   f"আগামী {weeks} সপ্তাহের মধ্যে এটিই সবচেয়ে টানাটানির সপ্তাহ")
    else:
        head_en = (f"The tightest of the next {weeks} weeks is {worst['label']}, starting {fmt.day_month(start, 'en')} "
                   f"({days} days from today), after the spending you have already approved")
        head_bn = (f"আগামী {weeks} সপ্তাহের মধ্যে সবচেয়ে টানাটানির সপ্তাহ {fmt.week_label(worst['label'], 'bn')}, "
                   f"{fmt.day_month(start, 'bn')} থেকে ({days} দিন পর), অনুমোদিত খরচের পরে")
    approved = any(str(line.get("id", "")).startswith("P-") for line in base["lines"])
    more_en, more_bn = (" more", " আরও") if approved else ("", "")
    en = (f"{head_en}: after it, cash is forecast at {fmt.bdt(worst['closing'], 'en')} (base) or "
          f"{fmt.bdt(stress_row['closing'], 'en')} (stress test). To keep your {fmt.bdt(reserve, 'en')} reserve, spend at most "
          f"{fmt.bdt(sti_b, 'en')}{more_en} now ({fmt.bdt(sti_s, 'en')} if the stress test happens).")
    bn = (f"{head_bn}: এরপর নগদ থাকবে {fmt.bdt(worst['closing'], 'bn')} (মূল পূর্বাভাস) বা "
          f"{fmt.bdt(stress_row['closing'], 'bn')} (স্ট্রেস টেস্ট)। {fmt.bdt(reserve, 'bn')} রিজার্ভ ঠিক রাখতে এখন সর্বোচ্চ{more_bn} "
          f"{fmt.bdt(sti_b, 'bn')} খরচ করুন (স্ট্রেস টেস্ট হলে {fmt.bdt(sti_s, 'bn')})।")
    return {
        "week": worst["index"], "label": worst["label"], "due_date": due.isoformat(), "last_due_date": last_due.isoformat(),
        "days_until": days, "payroll_and_rent": money(total), "base_close": worst["closing"],
        "stress_close": stress_row["closing"], "sti_base": sti_b, "sti_stress": sti_s, "reserve": reserve,
        "message_en": en, "message_bn": bn,
    }


def simulate(
    data: Dict[str, Any],
    amount: float = 0.0,
    spend_week: int = 1,
    stress: Shocks = DOWNSIDE,
    commitments: Iterable[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Base forecast and stress test for spending `amount` at the start of `spend_week`."""
    _, n = horizon(data)
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
        raise ValueError("amount must be a non-negative number")
    if isinstance(spend_week, bool) or not isinstance(spend_week, int) or not 1 <= spend_week <= n:
        raise ValueError(f"spend_week must be a whole number from 1 to {n}")
    commitments = list(commitments)
    spends = {spend_week: float(amount)} if amount else {}
    c0 = opening_cash(data).value
    reserve = reserve_amount(data)
    base = scenario_view(data, BASE, commitments, spends, spend_week)
    strs = scenario_view(data, stress, commitments, spends, spend_week)
    base_sti = sti_metric(c0, reserve, base["sti"], "base", BASE, spend_week)
    stress_sti = sti_metric(c0, reserve, strs["sti"], "stress", stress, spend_week)
    return {
        "amount": money(amount),
        "spend_week": spend_week,
        "reserve": reserve,
        "opening_cash": c0,
        "base": {**base, "sti_metric": base_sti.to_dict(), "summary": _path_summary(base["rows"]),
                 "alerts": alerts(data, base, "base")},
        "stress": {**strs, "sti_metric": stress_sti.to_dict(), "summary": _path_summary(strs["rows"]),
                   "alerts": alerts(data, strs, "stress")},
        "safe_in_base": amount <= base["sti"]["value"] + EPS,
        "safe_in_stress": amount <= strs["sti"]["value"] + EPS,
        "gap_base": money(max(0.0, amount - base["sti"]["value"])),
        "gap_stress": money(max(0.0, amount - strs["sti"]["value"])),
        "break_even": break_even(data, amount) if amount else None,
    }


def category_label(category: str, lang: str) -> str:
    en, bn = CATEGORY_LABELS.get(category, (category, category))
    return bn if lang == "bn" else en


# --------------------------------------------------------------------------
# Month view: actuals, then actual + forecast, then forecast
# --------------------------------------------------------------------------

def forecast_months(data: Dict[str, Any], commitments: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """November and later as months: 1-14 Nov actuals plus forecast lines (and commitments in the plan view)."""
    from .data import monthly_ledger  # local import to avoid a cycle at module load
    start, n = horizon(data)
    end = start + timedelta(days=7 * n - 1)
    opening = monthly_ledger(data)[-1]["closing_cash"]
    buckets: Dict[str, Dict[str, float]] = {}

    def add(month: str, kind: str, amount: float, actual: bool) -> None:
        b = buckets.setdefault(month, {"receipts": 0.0, "payments": 0.0, "actual_receipts": 0.0, "actual_payments": 0.0,
                                       "campaign": 0.0})
        b[kind] += amount
        if actual:
            b["actual_" + kind] += amount

    for line in data["november_to_date_actuals"]:
        add(line["date"][:7], "receipts" if line["type"] == "receipt" else "payments", float(line["amount"]), True)
    for line in list(data["forecast"]["lines"]) + list(commitments):
        if not start <= date.fromisoformat(line["date"]) <= end:
            continue
        add(line["date"][:7], "receipts" if line["type"] == "receipt" else "payments", float(line["amount"]), False)
        if line.get("category") == "admission_campaign":
            buckets[line["date"][:7]]["campaign"] += float(line["amount"])
    rows = []
    for month in sorted(buckets):
        b = buckets[month]
        closing = opening + b["receipts"] - b["payments"]
        last_day = min(end, (date.fromisoformat(month + "-01") + timedelta(days=32)).replace(day=1) - timedelta(days=1))
        status = "ACTUAL+FORECAST" if b["actual_receipts"] or b["actual_payments"] else "FORECAST"
        rows.append({"month": month, "status": status, "opening_cash": money(opening), "receipts": money(b["receipts"]),
                     "payments": money(b["payments"]), "campaign": money(b["campaign"]), "net": money(b["receipts"] - b["payments"]),
                     "closing_cash": money(closing), "covers_to": last_day.isoformat()})
        opening = closing
    return rows


def collection_insight(data: Dict[str, Any]) -> Dict[str, Any]:
    """The worst and best collection months from the actual ledger (no model, just the records)."""
    from .data import monthly_ledger
    rows = monthly_ledger(data)
    worst = min(rows, key=lambda r: r["collection_ratio"])
    best = max(rows, key=lambda r: r["collection_ratio"])
    return {"worst_month": worst["month"], "worst_ratio": worst["collection_ratio"], "worst_note_en": worst["note_en"],
            "worst_note_bn": worst["note_bn"], "best_month": best["month"], "best_ratio": best["collection_ratio"],
            "best_note_en": best["note_en"], "best_note_bn": best["note_bn"]}
