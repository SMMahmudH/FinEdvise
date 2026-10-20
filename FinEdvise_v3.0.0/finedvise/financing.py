"""Financing-option matching: operational fixes first, borrowing last.

Every credit option is costed the same way: build the borrower's cash flows
(money received after fees, then each repayment), solve the per-period
internal rate of return, and annualise it:
    APR (all-in, nominal) = r x periods per year
    EAR (compounded)      = (1 + r) ^ periods per year - 1
Each option is then replayed through the stress-test cash forecast to check
whether the school still keeps its reserve in every week, including the weeks
when instalments fall due ("weakest-week test").
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import fmt
from .data import opening_cash, reserve_amount, scenario_date
from .engine import DOWNSIDE, Shocks, build_weeks, cash_path, horizon, plan_schedule, plan_total, week_of
from .provenance import money

MONTH_DAYS = 365.0 / 12.0


# --------------------------------------------------------------------------
# Cost of credit
# --------------------------------------------------------------------------

def _npv(rate: float, flows: List[Tuple[float, float]]) -> float:
    return sum(amount / (1.0 + rate) ** k for k, amount in flows)


def periodic_irr(flows: List[Tuple[float, float]]) -> float:
    """IRR per period for flows [(period_index, amount)], borrower view (+ received, - paid)."""
    low, high = -0.99, 10.0
    f_low, f_high = _npv(low, flows), _npv(high, flows)
    if f_low * f_high > 0:
        raise ValueError("cash flows do not have a single rate of return")
    for _ in range(200):
        mid = (low + high) / 2.0
        f_mid = _npv(mid, flows)
        if abs(f_mid) < 1e-9:
            break
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2.0


def repayment_schedule(option: Dict[str, Any], principal: float) -> Dict[str, Any]:
    """Borrower cash flows by day offset from disbursement, for any catalogue option."""
    basis = option["rate_basis"]
    fee = principal * float(option.get("upfront_fee_pct") or 0.0)
    if basis == "lost_discount":
        days = int(option["credit_days"])
        discount = float(option["lost_discount_pct"])
        received = principal * (1.0 - discount)      # the cash price you would have paid today
        payments = [(float(days), principal)]
        return {"received": received, "fee": 0.0, "payments": payments, "period_days": float(days),
                "total_cost": principal - received}

    rate = float(option["rate_pct"] or 0.0) / 100.0
    rhythm = option["repayment"]
    if option.get("tenor_weeks"):
        years = int(option["tenor_weeks"]) / 52.0
    else:
        years = int(option["tenor_months"]) / 12.0
    if rhythm == "single":
        total = principal * (1.0 + rate * years)
        payments = [(years * 365.0, total)]
        period_days = years * 365.0
    elif rhythm in ("monthly", "weekly"):
        n = round(years * 12) if rhythm == "monthly" else round(years * 52)
        period_days = MONTH_DAYS if rhythm == "monthly" else 7.0
        if basis == "flat":
            installment = principal * (1.0 + rate * years) / n
        else:
            r = rate * period_days / 365.0
            installment = principal / n if r == 0 else principal * r / (1.0 - (1.0 + r) ** (-n))
        payments = [((i + 1) * period_days, installment) for i in range(n)]
    else:
        raise ValueError(f"unknown repayment rhythm {rhythm}")
    received = principal - fee
    total_paid = sum(p for _, p in payments)
    return {"received": received, "fee": fee, "payments": payments, "period_days": period_days,
            "total_cost": total_paid + fee - principal}


def cost_of_credit(option: Dict[str, Any], principal: float) -> Dict[str, Any]:
    sched = repayment_schedule(option, principal)
    period = sched["period_days"]
    flows = [(0.0, sched["received"])] + [(day / period, -amount) for day, amount in sched["payments"]]
    if sched["total_cost"] <= 1e-9:
        r = 0.0
    else:
        r = periodic_irr(flows)
    per_year = 365.0 / period
    return {
        "principal": money(principal),
        "received_after_fees": money(sched["received"]),
        "upfront_fee": money(sched["fee"]),
        "instalment": money(sched["payments"][0][1]) if sched["payments"] else 0.0,
        "number_of_payments": len(sched["payments"]),
        "total_repaid": money(sum(p for _, p in sched["payments"])),
        "total_cost": money(sched["total_cost"]),
        "apr_pct": round(r * per_year * 100.0, 1),
        "ear_pct": round(((1.0 + r) ** per_year - 1.0) * 100.0, 1),
        "payments": [{"day": round(day, 1), "amount": money(amount)} for day, amount in sched["payments"]],
        "method": "IRR of borrower cash flows; APR = r x periods per year; EAR = (1 + r)^periods - 1",
    }


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------

def eligibility(option: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    missing, failed = [], []
    for field, needed in (option.get("requires") or {}).items():
        answer = profile.get(field)
        if answer is None:
            missing.append(field)
        elif isinstance(needed, bool):
            if bool(answer) != needed:
                failed.append(field)
        elif isinstance(needed, (int, float)):
            if not isinstance(answer, (int, float)) or answer < needed:
                failed.append(field)
    status = "not_eligible" if failed else ("unknown" if missing else "eligible")
    return {"status": status, "missing": missing, "failed": failed}


def next_question(catalogue: Dict[str, Any], profile: Dict[str, Any], options: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The single most important unanswered eligibility question (one at a time)."""
    needed = set()
    for opt in options:
        needed.update(field for field in (opt.get("requires") or {}) if profile.get(field) is None)
    for q in sorted(catalogue["eligibility_questions"], key=lambda q: q["priority"]):
        if q["id"] in needed:
            return q
    return None


# --------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------

def _needed_injection(rows: List[Dict[str, Any]]) -> float:
    """Smallest extra cash at the start of week 1 that removes every breach and shortfall."""
    need = 0.0
    for r in rows:
        need = max(need, r["reserve_gap"], r["cash_shortfall"])
    return money(need)


def _loan_lines(data: Dict[str, Any], option: Dict[str, Any], principal: float, cost: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Forecast lines for a loan: the money arriving and each instalment inside the window."""
    start, n = horizon(data)
    arrive = scenario_date(data) + timedelta(days=int(option.get("days_to_cash") or 0))
    lines = [{"id": f"LOAN-{option['id']}-IN", "date": arrive.isoformat(), "type": "receipt", "category": "loan_proceeds",
              "amount": cost["received_after_fees"], "status": "expected", "desc_en": "Loan money received",
              "desc_bn": "ঋণের টাকা প্রাপ্তি"}]
    for i, pay in enumerate(cost["payments"]):
        when = arrive + timedelta(days=round(pay["day"]))
        lines.append({"id": f"LOAN-{option['id']}-P{i + 1}", "date": when.isoformat(), "type": "payment",
                      "category": "loan_repayment", "amount": pay["amount"], "status": "committed",
                      "desc_en": f"Loan instalment {i + 1}", "desc_bn": f"ঋণের কিস্তি {i + 1}"})
    return [l for l in lines if 1 <= week_of(data, date.fromisoformat(l["date"])) <= n]


def _replay(data: Dict[str, Any], stress: Shocks, spends: Dict[int, float], extra: List[Dict[str, Any]],
            commitments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    weeks, _, _ = build_weeks(data, stress, commitments + extra)
    return cash_path(opening_cash(data).value, weeks, reserve_amount(data), spends)


def match_financing(
    data: Dict[str, Any],
    catalogue: Dict[str, Any],
    profile: Dict[str, Any],
    plan_id: Optional[str] = None,
    amount: Optional[float] = None,
    stress: Shocks = DOWNSIDE,
    commitments: Optional[List[Dict[str, Any]]] = None,
    allow_fixes: bool = True,
) -> Dict[str, Any]:
    """Cover a plan's stress-test gap: free operational fixes first, then credit options.

    allow_fixes=False compares credit options for paying everything now (used to show
    what borrowing would cost when rescheduling already solves the problem)."""
    commitments = list(commitments or [])
    if plan_id:
        plan = next((p for p in data["plans"] if p["id"] == plan_id), None)
        if plan is None:
            raise ValueError(f"unknown plan {plan_id}")
    else:
        if amount is None or isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
            raise ValueError("give a plan_id or a positive amount")
        plan = {"id": "CUSTOM", "name_en": "Custom amount", "name_bn": "নিজস্ব পরিমাণ",
                "items": [{"id": "X1", "label_en": "Spend now", "label_bn": "এখন খরচ", "amount": float(amount), "flex": None}],
                "extra_students_estimate": {}}

    total = plan_total(plan)
    lump_spends, _, _ = plan_schedule(plan, staged=False)
    lump_rows = _replay(data, stress, lump_spends, [], commitments)
    gap_lump = _needed_injection(lump_rows)

    staged_spends, staged_items, staging_cost = plan_schedule(plan, staged=allow_fixes)
    staged_rows = _replay(data, stress, staged_spends, [], commitments)
    gap_after_fixes = _needed_injection(staged_rows)

    fixes = []
    for item in staged_items:
        if allow_fixes and item.get("flex"):
            flex = item["flex"]
            fixes.append({
                "item_id": item["id"], "label_en": item["label_en"], "label_bn": item["label_bn"],
                "amount": money(item["amount"]), "type": flex["type"], "pay_week": item["pay_week"],
                "cost": money(item["staging_cost"]), "badge": "ASSUMED",
                "note_en": _fix_note(flex["type"], "en"), "note_bn": _fix_note(flex["type"], "bn"),
            })

    options = []
    if gap_after_fixes > 0:
        start, n = horizon(data)
        first_problem = next((r for r in staged_rows if r["status"] != "OK"), None)
        for opt in catalogue["options"]:
            if opt["kind"] == "supplier_credit":
                continue  # already used inside the operational fixes above
            minimum = float(opt.get("amount_min") or 0.0)
            principal = max(gap_after_fixes, minimum)
            principal_note = "lender_minimum" if minimum > gap_after_fixes else "exact_gap"
            capped = opt.get("amount_max") is not None and principal > opt["amount_max"]
            if capped:
                principal = float(opt["amount_max"])
                principal_note = "lender_maximum"
            cost = cost_of_credit(opt, principal)
            elig = eligibility(opt, profile)
            lines = _loan_lines(data, opt, principal, cost)
            rows = _replay(data, stress, staged_spends, lines, commitments)
            arrive = scenario_date(data) + timedelta(days=int(opt.get("days_to_cash") or 0))
            arrive_week = week_of(data, arrive)
            in_time = first_problem is None or arrive_week <= first_problem["index"]
            worst = min(rows, key=lambda r: (r["headroom"], r["low_point"]))
            first_fail = next((r for r in rows if r["status"] != "OK"), None)
            if first_fail is None and in_time:
                fail_reason = None
            elif not in_time:
                fail_reason = "arrives_too_late"
            elif first_fail["index"] == arrive_week:
                fail_reason = "arrives_after_payday_same_week"
            elif first_fail["index"] > arrive_week:
                fail_reason = "instalment_or_still_short"
            else:
                fail_reason = "arrives_too_late"
            options.append({
                "id": opt["id"], "kind": opt["kind"], "name_en": opt["name_en"], "name_bn": opt["name_bn"],
                "rate_pct": opt.get("rate_pct"), "rate_basis": opt["rate_basis"], "rate_badge": opt["rate_badge"],
                "terms_badge": opt["terms_badge"], "sources": opt.get("rate_sources", []),
                "principal": money(principal), "principal_note": principal_note, "capped_by_lender_max": capped, "cost": cost,
                "arrives": arrive.isoformat(), "arrives_week": arrive_week, "arrives_in_time": in_time,
                "passes_weakest_week_test": all(r["status"] == "OK" for r in rows) and in_time,
                "fail_reason": fail_reason, "first_fail_week": first_fail["label"] if first_fail else None,
                "worst_week_after": worst["label"], "worst_headroom_after": worst["headroom"],
                "eligibility": elig, "terms_note_en": opt.get("terms_note_en", ""), "terms_note_bn": opt.get("terms_note_bn", ""),
            })
        options.sort(key=lambda o: (
            0 if o["passes_weakest_week_test"] else 1,
            {"eligible": 0, "unknown": 1, "not_eligible": 2}[o["eligibility"]["status"]],
            o["cost"]["apr_pct"],
        ))

    question = next_question(catalogue, profile, [o for o in catalogue["options"] if o["kind"] != "supplier_credit"]) if gap_after_fixes > 0 else None
    return {
        "plan_id": plan["id"],
        "allow_fixes": allow_fixes,
        "plan_total": money(total),
        "stress": stress.to_dict(),
        "stress_text": {"en": stress.describe("en"), "bn": stress.describe("bn")},
        "gap_if_paid_now": gap_lump,
        "operational_fixes": fixes,
        "staging_cost": money(staging_cost),
        "gap_after_fixes": gap_after_fixes,
        "borrowing_needed": gap_after_fixes > 0,
        "credit_options": options,
        "next_question": question,
        "verdict_en": _verdict(gap_lump, gap_after_fixes, staging_cost, options, "en"),
        "verdict_bn": _verdict(gap_lump, gap_after_fixes, staging_cost, options, "bn"),
    }


def _fix_note(kind: str, lang: str) -> str:
    notes = {
        "supplier_credit": ("Buy on 30-day credit from the press; lose its 1% cash discount.",
                            "প্রেস থেকে ৩০ দিনের বাকিতে কিনুন; ১% নগদ ছাড় ছাড়তে হবে।"),
        "stage_after_payroll": ("Do this work after salaries are paid (from the week after payday).",
                                "বেতন দেওয়ার পরের সপ্তাহ থেকে এই কাজ করুন।"),
        "postpone": ("Buy closer to January, when it is needed.", "জানুয়ারির কাছাকাছি, যখন লাগবে তখন কিনুন।"),
    }
    en, bn = notes.get(kind, (kind, kind))
    return bn if lang == "bn" else en


def _verdict(gap_lump: float, gap_after: float, staging_cost: float, options: List[Dict[str, Any]], lang: str) -> str:
    if gap_lump <= 0:
        return ("এই খরচ স্ট্রেস টেস্টেও নিরাপদ। ঋণ বা খরচ পেছানোর দরকার নেই।" if lang == "bn"
                else "This spending is safe even in the stress test. No borrowing or rescheduling needed.")
    if gap_after <= 0:
        return (f"এখনই পুরো টাকা দিলে স্ট্রেস টেস্টে {fmt.bdt(gap_lump, lang)} ঘাটতি হয়। কিছু খরচ পরে করলে এই ঘাটতি থাকে না, "
                f"খরচ মাত্র {fmt.bdt(staging_cost, lang)}। ঋণের দরকার নেই।" if lang == "bn"
                else f"Paying everything now leaves a {fmt.bdt(gap_lump, lang)} gap in the stress test. Rescheduling part of it "
                     f"closes the gap for {fmt.bdt(staging_cost, lang)}. No loan is needed.")
    passing = [o for o in options if o["passes_weakest_week_test"] and o["eligibility"]["status"] != "not_eligible"]
    if passing and passing[0]["eligibility"]["status"] == "unknown":
        best = passing[0]
        name = best["name_bn"] if lang == "bn" else best["name_en"]
        return (f"খরচ পেছানোর পরও {fmt.bdt(gap_after, lang)} ঘাটতি থাকে। ঋণ বাছাইয়ের আগে যোগ্যতা জানতে হবে; সম্ভাব্য সবচেয়ে কম খরচের "
                f"বিকল্প: {name} (মোট খরচ বছরে {best['cost']['apr_pct']}%)।" if lang == "bn"
                else f"After rescheduling, {fmt.bdt(gap_after, lang)} is still missing. Eligibility must be confirmed before "
                     f"choosing; the cheapest candidate that arrives in time is {name} (all-in cost {best['cost']['apr_pct']}% a year).")
    if passing:
        best = passing[0]
        name = best["name_bn"] if lang == "bn" else best["name_en"]
        return (f"খরচ পেছানোর পরও {fmt.bdt(gap_after, lang)} ঘাটতি থাকে। সবচেয়ে কম খরচে সময়মতো যে বিকল্প পাস করে: {name} "
                f"(মোট খরচ বছরে {best['cost']['apr_pct']}%)।" if lang == "bn"
                else f"After rescheduling, {fmt.bdt(gap_after, lang)} is still missing. Cheapest option that arrives in time and "
                     f"passes the weakest-week test: {name} (all-in cost {best['cost']['apr_pct']}% a year).")
    return (f"খরচ পেছানোর পরও {fmt.bdt(gap_after, lang)} ঘাটতি থাকে এবং কোনো ঋণ সময়মতো আসে না বা পরীক্ষায় পাস করে না। "
            f"বাজেট কমানোই নিরাপদ।" if lang == "bn"
            else f"After rescheduling, {fmt.bdt(gap_after, lang)} is still missing and no credit option arrives in time and "
                 f"passes the weakest-week test. Cutting the budget is the safe choice.")


def loan_checklist(catalogue: Dict[str, Any], option_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    opt = next((o for o in catalogue["options"] if o["id"] == option_id), None)
    if opt is None:
        raise ValueError(f"unknown financing option {option_id}")
    elig = eligibility(opt, profile)
    return {
        "option_id": opt["id"], "name_en": opt["name_en"], "name_bn": opt["name_bn"],
        "documents_en": opt.get("documents_en", []), "documents_bn": opt.get("documents_bn", []),
        "documents_source": opt.get("documents_source"), "eligibility": elig,
        "draft_only": True,
        "note_en": "Checklist only. FinEdvise does not apply for loans or contact lenders.",
        "note_bn": "শুধু তালিকা। FinEdvise ঋণের আবেদন করে না বা ঋণদাতার সাথে যোগাযোগ করে না।",
    }
