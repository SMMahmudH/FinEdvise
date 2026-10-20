"""The agent's tools. Each one wraps the deterministic engine.

Every call goes through policy.evaluate() (inside Sandbox.decide) and is
written to the audit log. A tool result is the only place the agent may take
numbers from. Results use student codes, never names.
"""
from __future__ import annotations

import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from . import engine, extras, financing, fmt
from .audit import canonical, sha256
from .data import opening_cash, outstanding_tuition, reserve_amount, scenario_date
from .policy import ACTIONS, PROHIBITED, evaluate
from .store import Sandbox

SHOCK_PROPS = {
    "enrolment_drop_pct": {"type": "number", "description": "Fall in 2027 enrolment (re-admissions and new admissions) as a fraction, e.g. 0.15 for 15%."},
    "fee_delay_weeks": {"type": "integer", "description": "Weeks that parents' fee payments arrive late (0-4)."},
    "cost_increase_pct": {"type": "number", "description": "Rise in paper and operating costs not yet fixed-price, as a fraction, e.g. 0.10."},
    "emergency_cost": {"type": "number", "description": "One-off unplanned payment in taka."},
    "emergency_week": {"type": "integer", "description": "Week (1-8) of the emergency payment."},
    "closure_week": {"type": "integer", "description": "Week (1-8) of an unplanned school closure; 0 for none."},
}

TOOL_SPECS: List[Dict[str, Any]] = [
    {"name": "get_state", "description": "Current cash position, dues (not cash), reserve, safe-to-spend in the base forecast and the stress test, and the next tight week. Call this first.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "get_weekly_forecast", "description": "Week-by-week cash forecast for the next 8 weeks.",
     "parameters": {"type": "object", "properties": {
         "scenario": {"type": "string", "enum": ["base", "stress"], "description": "base forecast or the standard stress test"},
         "view": {"type": "string", "enum": ["plan", "baseline"], "description": "plan includes owner-approved commitments; baseline excludes them"}}}},
    {"name": "safe_to_invest", "description": "How much can be spent safely now (or in a given week), and what happens if `amount` is spent. Optional shocks replace the standard stress test.",
     "parameters": {"type": "object", "properties": {
         "amount": {"type": "number", "description": "Amount the owner wants to spend, in taka. 0 to just get the limit."},
         "spend_week": {"type": "integer", "description": "Week 1-8 when the money is spent; 1 means now."},
         **SHOCK_PROPS}}},
    {"name": "compare_plans", "description": "Compare the conservative, balanced and aggressive admission-season plans: safety in every week, break-even, cash payback and the recommended plan with the reason.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "break_even", "description": "Extra students needed for a campaign cost: economic break-even over 12 months versus getting the cash back by the end of January.",
     "parameters": {"type": "object", "properties": {"campaign_cost": {"type": "number", "description": "Campaign cost in taka."}}, "required": ["campaign_cost"]}},
    {"name": "match_financing", "description": "Cover a plan's stress-test gap: operational fixes first (reschedule, supplier credit), then credit options costed the same way (all-in APR) and tested on the weakest week. Returns the next eligibility question to ask.",
     "parameters": {"type": "object", "properties": {
         "plan_id": {"type": "string", "enum": ["PLAN_CONSERVATIVE", "PLAN_BALANCED", "PLAN_AGGRESSIVE"]},
         "amount": {"type": "number", "description": "Use instead of plan_id for a custom amount spent now."}}}},
    {"name": "draft_proposal", "description": "Create a DRAFT budget proposal for the owner to approve with the Approve button. It has no effect until approved.",
     "parameters": {"type": "object", "properties": {
         "plan_id": {"type": "string", "enum": ["PLAN_CONSERVATIVE", "PLAN_BALANCED", "PLAN_AGGRESSIVE"]},
         "amount": {"type": "number", "description": "Use instead of plan_id for a custom amount."},
         "staged": {"type": "boolean", "description": "true to pay flexible items later (recommended when the stress test fails)."},
         "spend_week": {"type": "integer", "description": "For a custom amount: week 1-8 to spend it."},
         "note": {"type": "string"}}}},
    {"name": "draft_parent_reminders", "description": "Draft polite fee reminders for guardians with dues. Drafts only: nothing is sent. Uses student codes.",
     "parameters": {"type": "object", "properties": {
         "min_months_due": {"type": "number", "description": "Only students owing at least this many months (default 2)."},
         "max_count": {"type": "integer", "description": "Maximum drafts (default 5)."}}}},
    {"name": "evaluate_extras", "description": "Evaluate the optional brain-games kit venture (bulk vs spot price, sale vs monthly rental payback, 50% pre-booking rule) and the annual brain-games fair subsidy and retention threshold.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "loan_document_checklist", "description": "Documents a lender usually asks for, for one financing option. Checklist only.",
     "parameters": {"type": "object", "properties": {"option_id": {"type": "string", "enum": [
         "BANK_CMSME_REFINANCE", "BANK_SME_MARKET", "NGO_MFI_ENTERPRISE", "NGO_FLAT_RATE", "SUPPLIER_CREDIT_PRESS", "OWNER_BRIDGE"]}},
         "required": ["option_id"]}},
    {"name": "get_open_questions", "description": "The next missing piece of information to ask the owner (one at a time, in priority order).",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "record_owner_answer", "description": "Save the owner's answer to a financing eligibility question they just gave in chat.",
     "parameters": {"type": "object", "properties": {
         "question_id": {"type": "string", "enum": ["has_trade_licence", "has_tin", "bank_statement_months", "can_offer_collateral", "has_guarantor", "owner_can_lend"]},
         "yes_no": {"type": "boolean"},
         "number": {"type": "number"}}, "required": ["question_id"]}},
    {"name": "request_owner_action", "description": "When the user asks you to pay, transfer, delete or edit records, approve, ignore the reserve, message parents or apply for a loan, call this so the policy records the request and decides. It never executes anything.",
     "parameters": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["execute_payment", "transfer_funds", "delete_record", "edit_record", "approve_proposal",
                                               "ignore_reserve_policy", "send_message_to_parents", "apply_for_loan", "set_reserve",
                                               "disable_audit_log", "share_data_externally"]},
         "details": {"type": "string"}}, "required": ["action"]}},
]
TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


class ToolContext:
    def __init__(self, sandbox: Sandbox, lang: str = "en", actor: str = "agent", source: str = "agent") -> None:
        self.sandbox = sandbox
        self.lang = lang
        self.actor = actor
        self.source = source
        self.calls: List[Dict[str, Any]] = []
        self.created_proposals: List[Dict[str, Any]] = []
        self.reminder_drafts: List[Dict[str, Any]] = []


def _shocks_from(args: Dict[str, Any], horizon: int) -> Optional[engine.Shocks]:
    raw = {k: args[k] for k in SHOCK_PROPS if k in args and args[k] is not None}
    for key in ("fee_delay_weeks", "emergency_week", "closure_week"):
        if key in raw and isinstance(raw[key], float) and raw[key].is_integer():
            raw[key] = int(raw[key])
    if not raw:
        return None
    shocks = engine.Shocks.from_dict(raw, horizon)
    return None if shocks.is_base() else shocks


def _problems(alerts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"week": a["label"], "type": a["type"], "amount": a["amount"], "due": a["due_date"], "days_until": a["days_until"]} for a in alerts]


# ---------------------------------------------------------------------------- handlers

def _approved(sb: Any) -> float:
    """Owner-approved spending already in the forecast; new spending is checked on top of it."""
    return float(sum(line["amount"] for line in sb.commitments() if line.get("type", "payment") == "payment"))


def t_get_state(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    data = sb.data()
    commitments = sb.commitments()
    base = engine.scenario_view(data, engine.BASE, commitments)
    stress = engine.scenario_view(data, engine.DOWNSIDE, commitments)
    pinch = engine.next_pinch(data, base, stress)
    pos = data["opening_position"]
    hist = data["history"][0]
    return {
        "data_label": data["meta"]["dataset_label"],
        "scenario_date": data["meta"]["scenario_date"],
        "cash_now": {"total": opening_cash(data).value, "cash_in_hand": pos["cash_in_hand"], "bank": pos["bank"],
                     "bkash_settled": pos["bkash_available"], "bkash_pending_not_counted": pos["bkash_pending"]["amount"]},
        "tuition_dues_not_cash": outstanding_tuition(data).value,
        "reserve": {"amount": reserve_amount(data), "status": data["reserve_policy"]["status"]},
        "safe_to_spend_now": {"base": base["sti"]["value"], "stress_test": stress["sti"]["value"],
                              "stress_test_means": engine.DOWNSIDE.describe(ctx.lang)},
        "tightest_week": {"week": pinch["label"], "first_due_date": pinch["due_date"], "days_until": pinch["days_until"],
                          "salaries_and_rent": pinch["payroll_and_rent"], "cash_after_it_base": pinch["base_close"],
                          "cash_after_it_stress": pinch["stress_close"]},
        "approved_commitments_total": float(sum(l["amount"] for l in commitments)),
        "pending_proposals": sum(1 for p in sb.proposals() if p["status"] == "pending"),
        "last_year_campaign": {"budget": hist["approved_budget"], "forecast_extra_admissions": hist["forecast_extra_admissions"],
                               "actual_extra_admissions": hist["actual_extra_admissions"],
                               "planning_collection_rate_now": data["student_economics"]["collection_rate"]},
        "view": "plan: includes owner-approved commitments",
        "horizon_weeks": engine.horizon(data)[1],
    }


def t_get_weekly_forecast(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    data = sb.data()
    commitments = sb.commitments() if args.get("view", "plan") == "plan" else []
    shocks = engine.DOWNSIDE if args.get("scenario") == "stress" else engine.BASE
    view = engine.scenario_view(data, shocks, commitments)
    return {
        "scenario": shocks.describe(ctx.lang), "view": args.get("view", "plan"), "reserve": reserve_amount(data),
        "weeks": [{"week": r["label"], "from": r["start"], "to": r["end"], "fees_in": r["receipts"],
                   "payments_out": round(r["payments"] + r["committed"], 2), "low_point": r["low_point"],
                   "week_end_cash": r["closing"], "above_reserve": r["headroom"], "status": r["status"]} for r in view["rows"]],
        "fees_arriving_after_window": view["carried_total"],
    }


def t_safe_to_invest(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    data = sb.data()
    _, n = engine.horizon(data)
    amount = float(args.get("amount") or 0.0)
    spend_week = int(args.get("spend_week") or 1)
    custom = _shocks_from(args, n)
    stress = custom or engine.DOWNSIDE
    sim = engine.simulate(data, amount, spend_week, stress, sb.commitments())
    week_label = sim["base"]["rows"][spend_week - 1]["label"]
    out = {
        "amount": sim["amount"], "spend_week": spend_week, "spend_week_label": week_label, "reserve": sim["reserve"],
        "horizon_weeks": n, "approved_spending_already_in_forecast": _approved(sb),
        "base": {"safe_to_spend": sim["base"]["sti"]["value"], "limited_by_week": sim["base"]["sti"]["binding_row"]["label"],
                 "limit_type": sim["base"]["sti"]["binding_kind"], "amount_is_safe": sim["safe_in_base"],
                 "gap": sim["gap_base"], "problems_if_spent": _problems(sim["base"]["alerts"])},
        "stress": {"scenario": stress.describe(ctx.lang), "is_standard_stress_test": custom is None,
                   "safe_to_spend": sim["stress"]["sti"]["value"], "limited_by_week": sim["stress"]["sti"]["binding_row"]["label"],
                   "amount_is_safe": sim["safe_in_stress"], "gap": sim["gap_stress"],
                   "problems_if_spent": _problems(sim["stress"]["alerts"]),
                   "fees_arriving_after_window": sim["stress"]["carried_total"]},
    }
    if amount:
        be = sim["break_even"]
        out["break_even"] = {"economic_break_even_students": be["economic_break_even"]["value"],
                             "cash_payback_students": be["cash_payback"]["value"]}
    return out


def t_compare_plans(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    cmp = engine.compare_plans(sb.data(), engine.DOWNSIDE, sb.commitments())
    plans = []
    for p in cmp["plans"]:
        lump, staged = p["lump_sum"], p["staged"]
        plans.append({
            "id": p["id"], "name": lump["name_bn"] if ctx.lang == "bn" else lump["name_en"], "total": lump["total"],
            "extra_students_owner_estimate": lump["extra_students_estimate"],
            "economic_break_even_students": lump["economic_break_even"], "cash_payback_students": lump["cash_payback_students"],
            "expected_gain": lump["gains"],
            "paid_now": {"base_ok": lump["base"]["ok"], "stress_ok": lump["stress"]["ok"], "base_reserve_gap": lump["base"]["max_reserve_gap"],
                         "base_cash_shortfall": lump["base"]["max_cash_shortfall"], "base_worst_week": lump["base"]["worst_week"],
                         "stress_reserve_gap": lump["stress"]["max_reserve_gap"], "stress_cash_shortfall": lump["stress"]["max_cash_shortfall"]},
            "staged": {"base_ok": staged["base"]["ok"], "stress_ok": staged["stress"]["ok"], "staging_cost": staged["staging_cost"],
                       "stress_reserve_gap": staged["stress"]["max_reserve_gap"], "stress_cash_shortfall": staged["stress"]["max_cash_shortfall"],
                       "schedule": [{"item": i["label_bn"] if ctx.lang == "bn" else i["label_en"], "amount": i["amount"], "pay_week": i["pay_week"]}
                                    for i in staged["schedule"]]},
        })
    return {"recommended_plan_id": cmp["recommended_plan_id"], "reason": cmp["reason"][ctx.lang if ctx.lang in ("en", "bn") else "en"],
            "advice": cmp["advice"], "stress_test_means": engine.DOWNSIDE.describe(ctx.lang), "plans": plans,
            "approved_spending_already_in_forecast": _approved(sb),
            "horizon_months": ctx.sandbox.seed["student_economics"]["horizon_months"],
            "note": "Extra students are the owner's estimates (ASSUMED), not a forecast of what advertising causes."}


def t_break_even(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    cost = args.get("campaign_cost")
    be = engine.break_even(ctx.sandbox.data(), float(cost))
    econ = be["economics"]
    return {"campaign_cost": be["cost"], "horizon_months": ctx.sandbox.seed["student_economics"]["horizon_months"],
            "net_contribution_per_student": econ["net_contribution"]["value"],
            "net_contribution_formula": econ["net_contribution"]["worked"],
            "economic_break_even_students": be["economic_break_even"]["value"],
            "cash_per_student_by_end_january": econ["window_cash"]["value"],
            "cash_per_student_formula": econ["window_cash"]["worked"],
            "cash_payback_students": be["cash_payback"]["value"]}


def t_match_financing(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    data = sb.data()
    plan_id = args.get("plan_id")
    amount = args.get("amount")
    if not plan_id and not amount:
        plan_id = engine.compare_plans(data, engine.DOWNSIDE, sb.commitments())["recommended_plan_id"] or "PLAN_BALANCED"
    m = financing.match_financing(data, sb.catalogue, sb.profile(), plan_id=plan_id, amount=amount,
                                  commitments=sb.commitments())
    lang = ctx.lang if ctx.lang in ("en", "bn") else "en"
    return {
        "plan_id": m["plan_id"], "plan_total": m["plan_total"], "stress_test_means": m["stress_text"][lang],
        "approved_spending_already_in_forecast": _approved(sb),
        "gap_if_paid_now": m["gap_if_paid_now"],
        "operational_fixes": [{"item": f["label_bn"] if lang == "bn" else f["label_en"], "amount": f["amount"],
                               "how": f["note_bn"] if lang == "bn" else f["note_en"], "pay_week": f["pay_week"], "cost": f["cost"]}
                              for f in m["operational_fixes"]],
        "staging_cost": m["staging_cost"], "gap_after_fixes": m["gap_after_fixes"], "borrowing_needed": m["borrowing_needed"],
        "credit_options": [{"id": o["id"], "name": o["name_bn"] if lang == "bn" else o["name_en"], "principal": o["principal"],
                            "all_in_apr_pct": o["cost"]["apr_pct"], "total_cost": o["cost"]["total_cost"],
                            "arrives": o["arrives"], "arrives_in_time": o["arrives_in_time"],
                            "passes_weakest_week_test": o["passes_weakest_week_test"], "eligibility": o["eligibility"]["status"],
                            "terms_badge": o["terms_badge"]} for o in m["credit_options"][:4]],
        "next_question": ({"id": m["next_question"]["id"], "question": m["next_question"]["q_bn" if lang == "bn" else "q_en"]}
                          if m["next_question"] else None),
        "verdict": m["verdict_bn"] if lang == "bn" else m["verdict_en"],
    }


def t_draft_proposal(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    plan_id = args.get("plan_id")
    amount = args.get("amount")
    staged = bool(args.get("staged", True))
    spend_week = int(args.get("spend_week") or 1)
    decision, proposal = sb.create_proposal("agent", plan_id=plan_id, amount=amount, staged=staged,
                                            spend_week=spend_week, note=str(args.get("note") or ""), source="agent")
    if not decision.allowed or proposal is None:
        return {"created": False, "decision": decision.decision, "reason": decision.reason_bn if ctx.lang == "bn" else decision.reason_en}
    ctx.created_proposals.append(proposal)
    c = proposal["content"]
    return {"created": True, "proposal_id": proposal["id"], "status": "pending_owner_approval",
            "title": c["title_bn"] if ctx.lang == "bn" else c["title_en"], "total": c["total"],
            "staging_cost": c["staging_cost"], "safe_in_base": c["checks"]["base_ok"], "safe_in_stress_test": c["checks"]["stress_ok"],
            "content_hash_short": proposal["content_hash"][:12],
            "next_step": "The owner reviews it in the Approvals tab and presses Approve or Reject."}


REMINDER_TEMPLATES = {
    "en": ("Dear {guardian},\nThis is a gentle reminder from {school} that {months_text} of tuition for {student} "
           "(BDT {amount}) is still unpaid. If it is difficult to pay at once, please talk to us about paying in parts. "
           "Thank you for your support.\n- School office"),
    "bn": ("প্রিয় {guardian},\n{school}-এর পক্ষ থেকে বিনীতভাবে জানাচ্ছি, {student}-এর {months_text} টিউশন (৳{amount}) এখনো "
           "বকেয়া আছে। একসাথে দেওয়া কঠিন হলে কিস্তিতে দেওয়ার বিষয়ে আমাদের সাথে কথা বলুন। আপনার সহযোগিতার জন্য ধন্যবাদ।\n- স্কুল অফিস"),
}


def t_draft_parent_reminders(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    min_months = float(args.get("min_months_due") or 2)
    max_count = max(1, min(int(args.get("max_count") or 5), 20))
    dues = sb.dues()
    rows = [r for r in dues["students"] if r["status"] == "active" and r["months_due"] >= min_months]
    rows.sort(key=lambda r: -r["dues"])
    rows = rows[:max_count]
    drafts = [{"student": r["student_id"], "guardian": "GRD-" + r["student_id"].split("-")[1], "dues": r["dues"],
               "months_due": r["months_due"]} for r in rows]
    ctx.reminder_drafts = drafts
    return {"drafts": drafts, "count": len(drafts), "dues_reconciled_with_ledger": dues["reconciled"],
            "sending": "not possible: drafts only, the owner copies and sends them",
            "tone": "polite, offers instalments, no threats, no public naming"}


def t_evaluate_extras(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    data = sb.data()
    return {
        "brain_games_kit": extras.brain_games_kit(data, sb.commitments()),
        "engagement_event": extras.engagement_event(data),
        "approved_spending_already_in_forecast": _approved(sb),
    }


def t_loan_document_checklist(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    sb = ctx.sandbox
    c = financing.loan_checklist(sb.catalogue, args["option_id"], sb.profile())
    lang = ctx.lang if ctx.lang in ("en", "bn") else "en"
    return {"option": c["name_bn"] if lang == "bn" else c["name_en"],
            "documents": c["documents_bn"] if lang == "bn" else c["documents_en"],
            "eligibility": c["eligibility"]["status"], "missing_answers": c["eligibility"]["missing"],
            "note": c["note_bn"] if lang == "bn" else c["note_en"]}


def open_questions(sb: Sandbox, lang: str) -> List[Dict[str, Any]]:
    data = sb.data()
    out = []
    for q in sorted(data["open_questions"], key=lambda q: q["priority"]):
        if q["id"] == "Q_RESERVE" and data["reserve_policy"]["status"] != "PROPOSED_DEFAULT":
            continue
        if q["id"] in sb.state["profile"]:
            continue
        out.append({"id": q["id"], "question": q["q_bn"] if lang == "bn" else q["q_en"], "q_en": q["q_en"], "q_bn": q["q_bn"], "where": "general"})
    for q in sorted(sb.catalogue["eligibility_questions"], key=lambda q: q["priority"]):
        if q["id"] not in sb.state["profile"]:
            out.append({"id": q["id"], "question": q["q_bn"] if lang == "bn" else q["q_en"], "q_en": q["q_en"], "q_bn": q["q_bn"], "where": "financing"})
    return out


def t_get_open_questions(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    qs = open_questions(ctx.sandbox, ctx.lang)
    return {"next_question": qs[0] if qs else None, "remaining": len(qs),
            "rule": "Ask one question at a time, the first one first."}


def t_record_owner_answer(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    qid = args.get("question_id")
    value = args.get("yes_no") if args.get("yes_no") is not None else args.get("number")
    if isinstance(value, float) and value.is_integer() and qid == "bank_statement_months":
        value = int(value)
    decision = ctx.sandbox.set_answer("agent", qid, value, via="chat")
    return {"saved": decision.allowed, "question_id": qid, "value": value, "decision": decision.decision}


def t_request_owner_action(ctx: ToolContext, args: Dict[str, Any]) -> Dict[str, Any]:
    action = str(args.get("action") or "")
    decision = ctx.sandbox.decide(action, "agent", {}, {"details": str(args.get("details") or "")[:200], "requested_in_chat": True}, "agent")
    alternatives = {
        "execute_payment": ("I can draft a budget proposal; payments are made by the owner outside this app.",
                            "আমি বাজেট প্রস্তাবের খসড়া করতে পারি; টাকা পরিশোধ মালিক এই অ্যাপের বাইরে করেন।"),
        "transfer_funds": ("I can show what is safe to move; the owner makes any transfer outside this app.",
                           "কত টাকা সরানো নিরাপদ তা দেখাতে পারি; ট্রান্সফার মালিক এই অ্যাপের বাইরে করেন।"),
        "delete_record": ("Records are append-only. A correction is added as a new entry by the owner.",
                          "রেকর্ড শুধু যোগ করা যায়, মোছা যায় না। ভুল হলে মালিক নতুন সংশোধনী এন্ট্রি দেন।"),
        "edit_record": ("Records are append-only. A correction is added as a new entry by the owner.",
                        "রেকর্ড শুধু যোগ করা যায়, বদলানো যায় না। ভুল হলে মালিক নতুন সংশোধনী এন্ট্রি দেন।"),
        "approve_proposal": ("I can prepare a draft; the owner approves it with the Approve button.",
                             "আমি খসড়া তৈরি করতে পারি; মালিক 'অনুমোদন' বোতামে অনুমোদন দেন।"),
        "ignore_reserve_policy": ("The reserve can only be changed by the owner in Settings, and every change is logged.",
                                  "রিজার্ভ শুধু মালিক সেটিংসে বদলাতে পারেন, আর প্রতিটি পরিবর্তন লগে থাকে।"),
        "send_message_to_parents": ("I can draft polite reminders for the owner to copy and send.",
                                    "মালিক কপি করে পাঠাতে পারেন এমন বিনীত রিমাইন্ডারের খসড়া করতে পারি।"),
        "apply_for_loan": ("I can compare options and list the documents; the owner applies directly.",
                           "বিকল্পগুলোর তুলনা ও কাগজপত্রের তালিকা দিতে পারি; আবেদন মালিক নিজে করেন।"),
        "set_reserve": ("The owner can change the reserve in Settings.", "মালিক সেটিংসে রিজার্ভ বদলাতে পারেন।"),
    }
    pair = alternatives.get(action, ("I can explain the numbers and prepare drafts.", "আমি হিসাব ব্যাখ্যা ও খসড়া তৈরি করতে পারি।"))
    return {"action": action, "tier": decision.tier, "decision": decision.decision,
            "reason": decision.reason_bn if ctx.lang == "bn" else decision.reason_en,
            "instead": pair[1] if ctx.lang == "bn" else pair[0], "executed": False}


HANDLERS: Dict[str, Callable[[ToolContext, Dict[str, Any]], Dict[str, Any]]] = {
    "get_state": t_get_state,
    "get_weekly_forecast": t_get_weekly_forecast,
    "safe_to_invest": t_safe_to_invest,
    "compare_plans": t_compare_plans,
    "break_even": t_break_even,
    "match_financing": t_match_financing,
    "evaluate_extras": t_evaluate_extras,
    "draft_proposal": t_draft_proposal,
    "draft_parent_reminders": t_draft_parent_reminders,
    "loan_document_checklist": t_loan_document_checklist,
    "get_open_questions": t_get_open_questions,
    "record_owner_answer": t_record_owner_answer,
    "request_owner_action": t_request_owner_action,
}


def _validate_args(name: str, args: Any) -> Dict[str, Any]:
    if args is None:
        return {}
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    spec = next(s for s in TOOL_SPECS if s["name"] == name)
    props = spec["parameters"].get("properties", {})
    clean = {}
    for key, value in args.items():
        if key not in props:
            raise ValueError(f"unknown argument {key}")
        kind = props[key]["type"]
        if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError(f"{key} must be a number")
        if kind == "integer":
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be a whole number")
        if kind == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        if kind == "string":
            if not isinstance(value, str):
                raise ValueError(f"{key} must be text")
            value = value[:500]
            if "enum" in props[key] and value not in props[key]["enum"]:
                raise ValueError(f"{key} must be one of {props[key]['enum']}")
        clean[key] = value
    for key in spec["parameters"].get("required", []):
        if key not in clean:
            raise ValueError(f"missing argument {key}")
    return clean


def run_tool(ctx: ToolContext, name: str, args: Any) -> Dict[str, Any]:
    """Policy check, run, log. Returns {'ok', 'decision', 'result' or 'error'}."""
    started = time.perf_counter()
    sb = ctx.sandbox
    if name not in TOOL_NAMES:
        # A name the model invented, e.g. 'pay_vendor': default deny, logged.
        decision = sb.decide(name, ctx.actor, {}, {"args": args if isinstance(args, dict) else str(args)[:200], "unknown_tool": True}, ctx.source)
        record = {"name": name, "args": args, "decision": decision.to_dict(), "ok": False,
                  "error": "unknown tool", "ms": round((time.perf_counter() - started) * 1000, 1)}
        ctx.calls.append(record)
        return {"ok": False, "decision": decision.to_dict(), "error": "This tool does not exist. Nothing was done."}
    try:
        clean = _validate_args(name, args)
    except ValueError as exc:
        sb.audit.append("TOOL_REJECTED_ARGS", ctx.actor, tool=name, error=str(exc), source=ctx.source)
        record = {"name": name, "args": args, "decision": None, "ok": False, "error": str(exc),
                  "ms": round((time.perf_counter() - started) * 1000, 1)}
        ctx.calls.append(record)
        return {"ok": False, "error": f"Invalid arguments: {exc}"}

    if name in ("draft_proposal", "record_owner_answer", "request_owner_action"):
        # these record their own policy decision inside the sandbox call
        decision_dict = None
    else:
        decision = sb.decide(name, ctx.actor, {}, {"args": clean}, ctx.source)
        decision_dict = decision.to_dict()
        if not decision.allowed:
            record = {"name": name, "args": clean, "decision": decision_dict, "ok": False,
                      "ms": round((time.perf_counter() - started) * 1000, 1)}
            ctx.calls.append(record)
            return {"ok": False, "decision": decision_dict}
    try:
        result = HANDLERS[name](ctx, clean)
    except ValueError as exc:
        sb.audit.append("TOOL_ERROR", ctx.actor, tool=name, error=str(exc), source=ctx.source)
        record = {"name": name, "args": clean, "decision": decision_dict, "ok": False, "error": str(exc),
                  "ms": round((time.perf_counter() - started) * 1000, 1)}
        ctx.calls.append(record)
        return {"ok": False, "error": str(exc)}
    if decision_dict is None:
        decision_dict = evaluate(name, ctx.actor, {"amount": result.get("total", 0)} if name == "draft_proposal" else {}).to_dict()
        if name == "request_owner_action":
            decision_dict = {"decision": result["decision"], "tier": result["tier"], "action": result["action"]}
    digest = sha256(canonical(result))
    sb.audit.append("TOOL_RESULT", ctx.actor, tool=name, result_hash=digest, source=ctx.source)
    record = {"name": name, "args": clean, "decision": decision_dict, "ok": True, "result": result,
              "result_hash": digest[:16], "ms": round((time.perf_counter() - started) * 1000, 1)}
    ctx.calls.append(record)
    return {"ok": True, "result": result}


def gemini_declarations() -> List[Dict[str, Any]]:
    """Function declarations for Gemini; tools without arguments omit 'parameters'."""
    out = []
    for spec in TOOL_SPECS:
        decl = {"name": spec["name"], "description": spec["description"]}
        if spec["parameters"].get("properties"):
            decl["parameters"] = spec["parameters"]
        out.append(decl)
    return out
