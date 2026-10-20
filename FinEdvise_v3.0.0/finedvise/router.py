"""Rule-based mode: an intent router with answer templates over the same tools.

Used when no AI model is configured or the model is unavailable. It is
labelled "rule-based" in the interface. It calls the same policy-checked tools
as the AI mode, so every number in its answers comes from a tool result.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import fmt
from .fmt import LATIN_DIGITS
from .tools import ToolContext, run_tool

BN_CHARS = re.compile(r"[ঀ-৿]")


def detect_lang(text: str, default: str = "en") -> str:
    if BN_CHARS.search(text or ""):
        return "bn"
    if re.search(r"[A-Za-z]", text or ""):
        return "en"
    return default


# ------------------------------------------------------------------ parsing

AMOUNT_RE = re.compile(
    r"(?:৳|bdt|tk\.?|taka)?\s*(\d{1,3}(?:,\d{2,3})+|\d+(?:\.\d+)?)\s*(lakhs?|lac|লাখ|লক্ষ|k\b|thousand|হাজার|crore|কোটি)?\s*(?:টাকা|taka|bdt)?",
    re.IGNORECASE,
)
SCALE = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "লাখ": 1e5, "লক্ষ": 1e5, "k": 1e3, "thousand": 1e3, "হাজার": 1e3,
         "crore": 1e7, "কোটি": 1e7}
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "এক": 1, "দুই": 2, "তিন": 3, "চার": 4}


def parse_amount(text: str) -> Optional[float]:
    """Largest money-like amount in the text (100 or more), e.g. '1 lakh', '৮৫,০০০', '85k'."""
    clean = text.translate(LATIN_DIGITS)
    best = None
    for m in AMOUNT_RE.finditer(clean):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        try:
            value = float(raw.replace(",", "")) * SCALE.get(unit, 1)
        except ValueError:
            continue
        if re.search(r"%|percent|শতাংশ", clean[m.end(1):m.end(1) + 3]):
            continue
        if value >= 100 and (best is None or value > best):
            best = value
    return best


def _number_near(clean: str, words: str) -> Optional[float]:
    m = re.search(rf"(\d+(?:\.\d+)?)\s*(?:%|percent|শতাংশ)[^.?!।]{{0,40}}(?:{words})|(?:{words})[^.?!।]{{0,40}}?(\d+(?:\.\d+)?)\s*(?:%|percent|শতাংশ)", clean, re.IGNORECASE)
    if not m:
        return None
    return float(m.group(1) or m.group(2))


def parse_shocks(text: str) -> Dict[str, Any]:
    clean = text.translate(LATIN_DIGITS).lower()
    shocks: Dict[str, Any] = {}
    enrol = _number_near(clean, r"admission|enrol|student|ভর্তি|শিক্ষার্থী")
    if enrol is not None and re.search(r"drop|fall|fewer|less|lower|down|কম|কমে", clean):
        shocks["enrolment_drop_pct"] = min(enrol, 90) / 100.0
    elif re.search(r"(fewer|less|lower|drop|fall).{0,20}(admission|enrol)|(ভর্তি).{0,15}কম", clean):
        shocks["enrolment_drop_pct"] = 0.15
    m = re.search(r"(\d+|one|two|three|four|এক|দুই|তিন|চার)\s*(?:-|\s)?(?:week|weeks|wk|সপ্তাহ)", clean)
    if re.search(r"late|delay|দেরি|দেরিতে|পিছিয়ে", clean):
        weeks = 1
        if m:
            token = m.group(1)
            weeks = int(token) if token.isdigit() else WORD_NUMBERS.get(token, 1)
        shocks["fee_delay_weeks"] = max(1, min(weeks, 4))
    cost = _number_near(clean, r"cost|price|paper|expense|খরচ|দাম|কাগজ")
    if cost is not None and re.search(r"rise|increase|up|more|higher|বেশি|বাড়ে|বাড়লে|বৃদ্ধি", clean):
        shocks["cost_increase_pct"] = min(cost, 100) / 100.0
    if re.search(r"emergency|repair|broke|জরুরি|মেরামত|নষ্ট", clean):
        amount = parse_amount(text)
        shocks["emergency_cost"] = amount if amount else 15000.0
    if re.search(r"clos|strike|flood|heat|hartal|বন্ধ|হরতাল|বন্যা|গরম", clean):
        shocks["closure_week"] = 3
    return shocks


QUESTION_CUE = re.compile(r"\?|\b(can|could|should|how|what|when|will|would|is it|are we|do we|enough)\b|কি\b|কী|কত|পারব|পারি|উচিত|কিভাবে|কীভাবে|হবে কি", re.IGNORECASE)
IMPERATIVE_CUE = re.compile(r"\b(now|immediately|right away|asap|go ahead|just do|do it)\b|^\s*(please\s+)?(pay|transfer|send|move|wire|release)\b|এখনই|এখুনি|দিয়ে দাও|করে দাও|পাঠাও|পাঠিয়ে দাও|পে করো|দাও$", re.IGNORECASE)

ALWAYS_ACTION = [
    ("delete_record", r"\b(delete|remove|erase|wipe|purge)\b.{0,40}\b(record|entry|entries|ledger|transaction|row|log|history|data)\b|মুছে|মুছো|ডিলিট"),
    ("edit_record", r"\b(edit|alter|modify|backdate|falsify|change)\b.{0,30}\b(record|entry|ledger|transaction|books)\b|(এন্ট্রি|রেকর্ড|হিসাব).{0,15}(বদলে|পরিবর্তন করে|পাল্টে)"),
    ("disable_audit_log", r"\b(disable|turn off|stop|hide|switch off)\b.{0,20}\b(audit|log|logging)\b|লগ.{0,10}বন্ধ"),
    ("ignore_reserve_policy", r"\b(ignore|forget|bypass|skip|override|disregard|remove)\b.{0,25}\breserve\b|\bwithout (the )?reserve\b|\breserve\b.{0,20}\b(doesn't matter|not needed|no longer)\b|রিজার্ভ.{0,20}(ভুলে|বাদ|উপেক্ষা|লাগবে না|ছাড়া|দরকার নেই)"),
    ("approve_proposal", r"\b(approve|authori[sz]e|sign off)\b|\block (in )?the (budget|plan)\b|অনুমোদন (দাও|দিন|করো|করে দাও|দিয়ে দাও)|অ্যাপ্রুভ"),
    ("send_message_to_parents", r"\b(send|sms|text|whatsapp|email|message)\b.{0,30}\b(parent|parents|guardian|guardians)\b|অভিভাবক.{0,25}(পাঠাও|পাঠিয়ে|এসএমএস|মেসেজ করো)"),
    ("apply_for_loan", r"\bapply\b.{0,20}\bloan\b|\bloan application\b|\bsubmit\b.{0,20}\bloan\b|(ঋণ|লোন).{0,10}আবেদন (করো|করে দাও)"),
    ("share_data_externally", r"\b(share|upload|export|send)\b.{0,30}\b(student|parent|guardian)s?\b.{0,20}\b(data|list|details|numbers)\b"),
]
MONEY_ACTION = [
    ("transfer_funds", r"\b(transfer|move|wire)\b.{0,30}\b(money|fund|funds|taka|tk|bdt|cash|\d)|ট্রান্সফার|টাকা (সরাও|সরিয়ে)"),
    ("execute_payment", r"\b(pay|payment|disburse|settle|release)\b|পেমেন্ট|পরিশোধ কর|টাকা দিয়ে দাও|পে করো|টাকা পাঠাও|পাঠিয়ে দাও"),
]

AGGRESSIVE_WORDS = r"aggressive|\bbold\b|আগ্রাসী|আক্রমণাত্মক|অ্যাগ্রেসিভ|এগ্রেসিভ"
BALANCED_WORDS = r"balanced|moderate|ভারসাম্য|ব্যালান্সড|ব্যালেন্সড|মাঝারি"
CONSERVATIVE_WORDS = r"conservative|cautious|রক্ষণশীল|কনজারভেটিভ"

PLAN_INTENTS = [
    ("draft_proposal", r"\b(draft|prepare|create|write|set up)\b.{0,30}\b(proposal|budget|plan)\b|for (my |owner )?approval|প্রস্তাব (তৈরি|বানাও|করো)|খসড়া|অনুমোদনের জন্য"),
    ("reminders", r"\b(remind|reminder|reminders|follow.?up|chase)\b|রিমাইন্ডার|তাগাদা|মনে করিয়ে"),
    ("loan_documents", r"\b(documents?|papers|paperwork|checklist)\b|কাগজপত্র|ডকুমেন্ট|কী কাগজ"),
    ("extras", r"\b(brain|game|games|kit|kits|fair|picnic|rental|club)\b|ব্রেইন|গেম|গেমস|কিট|মেলা|পিকনিক|ভাড়া"),
    ("financing", r"\b(loan|borrow|financing|finance|credit|lender|microcredit|mfi|interest rate|apr)\b|ঋণ|লোন|ধার|সুদ|অর্থায়ন"),
    ("break_even", r"break.?even|how many (new |extra )?students|payback|pay back|recover|কতজন|শিক্ষার্থী লাগবে|ব্রেক|উঠে আসবে|ফেরত পেতে"),
    ("compare_plans", r"\b(plans?|options?|compare|which one)\b|প্ল্যান|পরিকল্পনা|তুলনা|কোনটা|কোনটি|" + AGGRESSIVE_WORDS + "|" + BALANCED_WORDS + "|" + CONSERVATIVE_WORDS),
    ("what_if", r"\bwhat if\b|\bif\b.{0,50}\b(late|delay|drop|fall|fewer|less|lower|rise|increase|closed?|closure|strike|flood|emergency|repair)\b|যদি|দেরি|কমে|বাড়ে|বাড়লে|বন্ধ|হরতাল|বন্যা|জরুরি"),
    ("safe_to_invest", r"\b(how much|spend|safe|invest|afford|campaign)\b|কত টাকা|খরচ|বিনিয়োগ|নিরাপদ|পারব"),
    ("forecast", r"\b(forecast|weeks?|weekly|alerts?|risks?|warning|shortfall|tight|salary|salaries|payroll|rent|on time|enough (cash|money))\b|সপ্তাহ|সতর্ক|ঝুঁকি|পূর্বাভাস|ঘাটতি|বেতন|ভাড়া"),
    ("open_questions", r"\b(what do you need|missing|what information|what else)\b|কী জানতে|তথ্য লাগবে|আর কী"),
    ("state", r"\b(cash|balance|position|status|overview|summary|dues|owe|today)\b|নগদ|ব্যালেন্স|অবস্থা|সারসংক্ষেপ|বকেয়া|আজ"),
]


def classify(text: str) -> str:
    low = (text or "").lower()
    for action, pattern in ALWAYS_ACTION:
        if re.search(pattern, low, re.IGNORECASE):
            return "action:" + action
    for action, pattern in MONEY_ACTION:
        if re.search(pattern, low, re.IGNORECASE):
            if IMPERATIVE_CUE.search(low) or not QUESTION_CUE.search(low):
                return "action:" + action
    for intent, pattern in PLAN_INTENTS:
        if re.search(pattern, low, re.IGNORECASE):
            return intent
    return "help"


# ---------------------------------------------------------------- rendering

def b(value: float, lang: str) -> str:
    return fmt.bdt(value, lang)


def wk(label: str, lang: str) -> str:
    return fmt.week_label(label, lang)


def _problem_text(problems: List[Dict[str, Any]], lang: str) -> str:
    if not problems:
        return ""
    p = problems[0]
    if p["type"] == "CASH_SHORTFALL":
        return (f"{wk(p['week'], lang)}-এ বেতনের দিনে {b(p['amount'], lang)} নগদ ঘাটতি হবে ({p['days_until']} দিন পর)।" if lang == "bn"
                else f"you would be {b(p['amount'], lang)} short of cash on payday in {p['week']} (in {p['days_until']} days).")
    return (f"{wk(p['week'], lang)}-এ রিজার্ভের চেয়ে {b(p['amount'], lang)} কম থাকবে।" if lang == "bn"
            else f"cash would end {p['week']} {b(p['amount'], lang)} below your reserve.")


def render_state(r: Dict[str, Any], lang: str) -> str:
    c = r["cash_now"]
    s = r["safe_to_spend_now"]
    t = r["tightest_week"]
    stress = ", ".join(s["stress_test_means"])
    if lang == "bn":
        return (f"আজ ব্যবহারযোগ্য নগদ {b(c['total'], lang)} (হাতে {b(c['cash_in_hand'], lang)}, ব্যাংকে {b(c['bank'], lang)}, "
                f"বিকাশে {b(c['bkash_settled'], lang)}; বিকাশের {b(c['bkash_pending_not_counted'], lang)} এখনো সেটেল হয়নি, তাই ধরা হয়নি)। "
                f"অভিভাবকদের কাছে বকেয়া টিউশন {b(r['tuition_dues_not_cash'], lang)}, এটি নগদ নয়। রিজার্ভ {b(r['reserve']['amount'], lang)}।\n"
                f"এখন নিরাপদে খরচযোগ্য: মূল পূর্বাভাসে {b(s['base'], lang)}, স্ট্রেস টেস্টে ({stress}) {b(s['stress_test'], lang)}।\n"
                f"সবচেয়ে টানাটানির সপ্তাহ {wk(t['week'], lang)}: {t['days_until']} দিন পর {b(t['salaries_and_rent'], lang)} বেতন ও ভাড়া দিতে হবে।")
    return (f"Cash you can use today: {b(c['total'], lang)} (cash {b(c['cash_in_hand'], lang)}, bank {b(c['bank'], lang)}, "
            f"bKash {b(c['bkash_settled'], lang)}; {b(c['bkash_pending_not_counted'], lang)} of bKash has not settled yet, so it is not counted). "
            f"Parents owe {b(r['tuition_dues_not_cash'], lang)} in tuition; that is not cash. Your reserve is {b(r['reserve']['amount'], lang)}.\n"
            f"Safe to spend now: {b(s['base'], lang)} in the base forecast, {b(s['stress_test'], lang)} in the stress test ({stress}).\n"
            f"Tightest week: {t['week']}, when {b(t['salaries_and_rent'], lang)} of salaries and rent fall due in {t['days_until']} days.")


def on_top(r: Dict[str, Any], lang: str) -> str:
    """One sentence when owner-approved spending is already in the forecast."""
    done = r.get("approved_spending_already_in_forecast") or 0
    if not done:
        return ""
    return (f"\nএটি আগে অনুমোদিত {b(done, lang)} খরচের পরের হিসাব।" if lang == "bn"
            else f"\nThis is on top of the {b(done, lang)} of spending you have already approved.")


def render_sti(r: Dict[str, Any], lang: str, asked_amount: Optional[float]) -> str:
    return _render_sti(r, lang, asked_amount) + on_top(r, lang)


def _render_sti(r: Dict[str, Any], lang: str, asked_amount: Optional[float]) -> str:
    base, stress = r["base"], r["stress"]
    scen = ", ".join(stress["scenario"])
    if not asked_amount:
        if lang == "bn":
            return (f"এখন নিরাপদে খরচ করা যায় সর্বোচ্চ {b(base['safe_to_spend'], lang)} (মূল পূর্বাভাস; সীমা ঠিক করছে "
                    f"{wk(base['limited_by_week'], lang)})। স্ট্রেস টেস্টে ({scen}) সীমা {b(stress['safe_to_spend'], lang)}।\n"
                    f"এর বেশি খরচ করলে কোনো সপ্তাহের শেষে নগদ {b(r['reserve'], lang)} রিজার্ভের নিচে নামবে। প্রচারণা থেকে যে টাকা আসতে পারে তা এই হিসাবে ধরা হয়নি।")
        return (f"The most you can spend safely now is {b(base['safe_to_spend'], lang)} in the base forecast (the limit is set by "
                f"{base['limited_by_week']}). In the stress test ({scen}) it is {b(stress['safe_to_spend'], lang)}.\n"
                f"Spending more would leave cash below your {b(r['reserve'], lang)} reserve at the end of a week. Money the campaign may bring in is not counted.")
    amount = r["amount"]
    if base["amount_is_safe"] and stress["amount_is_safe"]:
        return (f"হ্যাঁ, এখন {b(amount, lang)} খরচ করা নিরাপদ: মূল পূর্বাভাসে সীমা {b(base['safe_to_spend'], lang)}, স্ট্রেস টেস্টে "
                f"{b(stress['safe_to_spend'], lang)}।" if lang == "bn"
                else f"Yes. Spending {b(amount, lang)} now is safe: the limit is {b(base['safe_to_spend'], lang)} in the base forecast and "
                     f"{b(stress['safe_to_spend'], lang)} in the stress test.")
    if base["amount_is_safe"]:
        return (f"মূল পূর্বাভাসে {b(amount, lang)} খরচ চলে (সীমা {b(base['safe_to_spend'], lang)}), কিন্তু স্ট্রেস টেস্টে ({scen}) সীমা "
                f"{b(stress['safe_to_spend'], lang)}: তখন {_problem_text(stress['problems_if_spent'], lang)}\n"
                f"সমাধান: কিছু খরচ বেতনের সপ্তাহের পরে করুন। চাইলে প্ল্যানগুলোর তুলনা দেখাই।" if lang == "bn"
                else f"{b(amount, lang)} fits the base forecast (limit {b(base['safe_to_spend'], lang)}), but in the stress test ({scen}) "
                     f"the limit is {b(stress['safe_to_spend'], lang)}, and {_problem_text(stress['problems_if_spent'], lang)}\n"
                     f"Fix: pay part of it after the salary week. Ask me to compare the plans to see a safe schedule.")
    return (f"এখন {b(amount, lang)} খরচ করা নিরাপদ নয়। মূল পূর্বাভাসেই সর্বোচ্চ {b(base['safe_to_spend'], lang)} খরচ করা যায় "
            f"(সীমা ঠিক করছে {wk(base['limited_by_week'], lang)}); {b(amount, lang)} খরচ করলে {_problem_text(base['problems_if_spent'], lang)}\n"
            f"স্ট্রেস টেস্টে সীমা {b(stress['safe_to_spend'], lang)}। হয় বাজেট {b(base['safe_to_spend'], lang)}-এ নামান, নয়তো কিছু খরচ পরে করুন।" if lang == "bn"
            else f"Spending {b(amount, lang)} now is not safe. Even in the base forecast the most you can spend is {b(base['safe_to_spend'], lang)} "
                 f"(the limit is set by {base['limited_by_week']}); with {b(amount, lang)} {_problem_text(base['problems_if_spent'], lang)}\n"
                 f"In the stress test the limit is {b(stress['safe_to_spend'], lang)}. Either cut the budget to {b(base['safe_to_spend'], lang)} or pay part of it later.")


def render_what_if(r: Dict[str, Any], base_r: Dict[str, Any], lang: str) -> str:
    return _render_what_if(r, base_r, lang) + on_top(r, lang)


def _render_what_if(r: Dict[str, Any], base_r: Dict[str, Any], lang: str) -> str:
    stress = r["stress"]
    scen = ", ".join(stress["scenario"])
    after = stress["fees_arriving_after_window"]
    extra = ""
    if after:
        h = r.get("horizon_weeks", 8)
        extra = (f" {b(after, lang)} ফি {h} সপ্তাহের পরে আসবে (হারিয়ে যায় না, শুধু পরে আসে)।" if lang == "bn"
                 else f" {b(after, lang)} of fees would arrive after the {h}-week window (not lost, just later).")
    if lang == "bn":
        return (f"যদি {scen}: এখন নিরাপদে খরচযোগ্য অর্থ মূল পূর্বাভাসের {b(base_r['base']['safe_to_spend'], lang)} থেকে "
                f"{b(stress['safe_to_spend'], lang)}-এ নামে (সীমা ঠিক করছে {wk(stress['limited_by_week'], lang)})।" + extra)
    return (f"With {scen}, the amount that is safe to spend now goes from {b(base_r['base']['safe_to_spend'], lang)} (base forecast) to "
            f"{b(stress['safe_to_spend'], lang)} (the limit is set by {stress['limited_by_week']})." + extra)


def render_plans(r: Dict[str, Any], lang: str) -> str:
    return _render_plans(r, lang) + on_top(r, lang)


def _render_plans(r: Dict[str, Any], lang: str) -> str:
    rec = next((p for p in r["plans"] if p["id"] == r["recommended_plan_id"]), None)
    if rec is None:
        return r["reason"]
    staged = rec["staged"]
    sched = "; ".join(f"{i['item']} {b(i['amount'], lang)} ({'সপ্তাহ' if lang == 'bn' else 'week'} {i['pay_week']})" for i in staged["schedule"])
    advice = r["advice"] or {}
    if lang == "bn":
        text = f"প্রস্তাব: {rec['name']} ({b(rec['total'], lang)})। {r['reason']}\n"
        if advice.get("use_staged"):
            text += (f"কিন্তু স্ট্রেস টেস্টে পুরো টাকা এখনই দিলে চলে না। ধাপে ধাপে দিলে প্রতিটি সপ্তাহে রিজার্ভ ঠিক থাকে, খরচ মাত্র "
                     f"{b(staged['staging_cost'], lang)}: {sched}।\n")
        text += (f"ব্রেক-ইভেন: {rec['economic_break_even_students']} জন অতিরিক্ত শিক্ষার্থী ({r['horizon_months']} মাসে); জানুয়ারির মধ্যে নগদ ফেরত পেতে লাগবে "
                 f"{rec['cash_payback_students']} জন। শিক্ষার্থীর সংখ্যাগুলো মালিকের অনুমান। অনুমোদনের জন্য খসড়া তৈরি করব?")
        return text
    text = f"Recommended: {rec['name']} ({b(rec['total'], lang)}). {r['reason']}\n"
    if advice.get("use_staged"):
        text += (f"In the stress test, paying it all now does not work. The staged schedule keeps the reserve in every week, at an extra cost of only "
                 f"{b(staged['staging_cost'], lang)}: {sched}.\n")
    text += (f"Break-even: {rec['economic_break_even_students']} extra students over {r['horizon_months']} months; getting the cash back by the end of January "
             f"needs {rec['cash_payback_students']}. Student numbers are the owner's estimates. Shall I draft it for your approval?")
    return text


def render_break_even(r: Dict[str, Any], lang: str) -> str:
    if lang == "bn":
        return (f"{b(r['campaign_cost'], lang)} খরচের জন্য অর্থনৈতিক ব্রেক-ইভেনে লাগবে {r['economic_break_even_students']} জন অতিরিক্ত "
                f"শিক্ষার্থী ({r['horizon_months']} মাসে প্রতিজন {b(r['net_contribution_per_student'], lang)} নিট অবদান রাখে: {r['net_contribution_formula']})।\n"
                f"কিন্তু জানুয়ারির মধ্যে পুরো টাকা নগদে ফেরত পেতে লাগবে {r['cash_payback_students']} জন, কারণ তখন পর্যন্ত প্রতিজন থেকে আসে মাত্র "
                f"{b(r['cash_per_student_by_end_january'], lang)} ({r['cash_per_student_formula']})।")
    return (f"For {b(r['campaign_cost'], lang)}, economic break-even needs {r['economic_break_even_students']} extra students over {r['horizon_months']} months "
            f"(each adds {b(r['net_contribution_per_student'], lang)}: {r['net_contribution_formula']}).\n"
            f"Getting the cash back by the end of January needs {r['cash_payback_students']} extra students, because each brings only "
            f"{b(r['cash_per_student_by_end_january'], lang)} by then ({r['cash_per_student_formula']}).")


def render_financing(r: Dict[str, Any], lang: str) -> str:
    text = r["verdict"] + on_top(r, lang)
    fixes = r["operational_fixes"]
    if fixes:
        text += "\nআগে বিনা ঋণে:" if lang == "bn" else "\nFirst, without borrowing:"
        for f in fixes:
            text += f"\n• {f['item']} ({b(f['amount'], lang)}): {f['how'].rstrip('.।')}"
    if r["borrowing_needed"] and r["credit_options"]:
        text += "\nঋণের বিকল্প (একই পদ্ধতিতে খরচ হিসাব):" if lang == "bn" else "\nCredit options (all costed the same way):"
        for o in r["credit_options"][:3]:
            ok = ("সময়মতো আসে ও দুর্বলতম সপ্তাহের পরীক্ষায় পাস" if lang == "bn" else "arrives in time and passes the weakest-week test") if o["passes_weakest_week_test"] \
                else ("দেরিতে আসে বা দুর্বলতম সপ্তাহের পরীক্ষায় ফেল" if lang == "bn" else "too late or fails the weakest-week test")
            text += f"\n• {o['name']}: {o['all_in_apr_pct']}% {'বার্ষিক' if lang == 'bn' else 'a year'} ({ok})"
    if r["next_question"]:
        text += ("\nঋণ বাছাইয়ের আগে একটি প্রশ্ন: " if lang == "bn" else "\nBefore choosing a loan, one question: ") + r["next_question"]["question"]
    return text


def render_draft(r: Dict[str, Any], lang: str) -> str:
    if not r.get("created"):
        return r.get("reason", "")
    safe_b = "হ্যাঁ" if r["safe_in_base"] else "না"
    safe_s = "হ্যাঁ" if r["safe_in_stress_test"] else "না"
    if lang == "bn":
        return (f"খসড়া {r['proposal_id']} তৈরি হয়েছে: {r['title']}, {b(r['total'], lang)}। মূল পূর্বাভাসে নিরাপদ: {safe_b}; "
                f"স্ট্রেস টেস্টে নিরাপদ: {safe_s}। আপনি 'অনুমোদন' ট্যাবে Approve না চাপা পর্যন্ত এর কোনো প্রভাব নেই "
                f"(কনটেন্ট হ্যাশ {r['content_hash_short']})।")
    return (f"Draft {r['proposal_id']} created: {r['title']}, {b(r['total'], lang)}. Safe in the base forecast: "
            f"{'yes' if r['safe_in_base'] else 'no'}; safe in the stress test: {'yes' if r['safe_in_stress_test'] else 'no'}. "
            f"It has no effect until you press Approve in the Approvals tab (content hash {r['content_hash_short']}).")


def render_reminders(r: Dict[str, Any], lang: str) -> str:
    lines = ", ".join(f"{d['student']} {b(d['dues'], lang)}" for d in r["drafts"])
    if lang == "bn":
        note = "" if r["dues_reconciled_with_ledger"] else " (সতর্কতা: ১-১৪ নভেম্বরের রেজিস্টার এখনো ইমপোর্ট হয়নি, তাই কিছু বকেয়া বেশি দেখাতে পারে)"
        return (f"{r['count']}টি বিনীত রিমাইন্ডারের খসড়া তৈরি করেছি (বেশি বকেয়া আগে): {lines}{note}। কিছুই পাঠানো হয়নি; "
                f"খসড়াগুলো নিচে দেখুন, কপি করে নিজে পাঠান।")
    note = "" if r["dues_reconciled_with_ledger"] else " (note: the 1-14 Nov register is not imported yet, so some dues may be overstated)"
    return (f"I drafted {r['count']} polite reminders, largest dues first: {lines}{note}. Nothing was sent; the drafts are shown below "
            f"for you to copy and send yourself.")


def render_extras(r: Dict[str, Any], lang: str) -> str:
    k, ev = r["brain_games_kit"], r["engagement_event"]
    if lang == "bn":
        text = (f"ব্রেইন-গেমস কিট: ক্লাসের {k['classroom_need']}টি ও অতিরিক্ত {k['extra_units']}টি = মোট {k['order_qty']}টি নিলে বাল্ক দাম "
                f"{b(k['unit_price'], lang)}/কিট (মোট নগদ {b(k['total_cash_needed'], lang)}, অতিরিক্ত কিটে {b(k['venture_cost'], lang)})। "
                f"{b(k['sale_price'], lang)} দরে অন্তত {k['break_even_units']}টি বিক্রি হলে খরচ উঠবে (মূল অনুমানে লাভ {b(k['base']['profit'], lang)}, "
                f"খারাপ অনুমানে ক্ষতি {b(abs(k['downside']['profit']), lang)}); অথবা মাসে {b(k['rental_option']['monthly_fee'], lang)} ভাড়ায় "
                f"{k['rental_option']['months_to_payback']} মাসে খরচ উঠবে। নিয়ম: আগে {k['prebooking_rule']['prebookings_needed_before_ordering']}টি প্রি-বুকিং নিন।\n"
                f"বার্ষিক মেলা: মোট খরচ {b(ev['total_cost'], lang)}, চাঁদা আদায় {b(ev['collected'], lang)}, স্কুলের ভর্তুকি {b(ev['school_subsidy'], lang)} "
                f"(ব্রেক-ইভেন চাঁদা জনপ্রতি {b(ev['break_even_contribution_per_student'], lang)}; ভর্তুকি উঠাতে অন্তত {ev['students_to_cover_subsidy_whole']} জন শিক্ষার্থী ধরে রাখতে বা আনতে হবে)।")
    else:
        text = (f"Brain-games kit: {k['classroom_need']} classroom + {k['extra_units']} extra = {k['order_qty']} sets at bulk {b(k['unit_price'], lang)} "
                f"(total cash {b(k['total_cash_needed'], lang)}, venture cost {b(k['venture_cost'], lang)}). Selling at {b(k['sale_price'], lang)} needs "
                f"{k['break_even_units']} sets to break even (base profit {b(k['base']['profit'], lang)}, downside loss {b(abs(k['downside']['profit']), lang)}), "
                f"or {b(k['rental_option']['monthly_fee'], lang)}/month rental recovers cost in {k['rental_option']['months_to_payback']} months after "
                f"{k['prebooking_rule']['prebookings_needed_before_ordering']} pre-bookings.\n"
                f"Annual fair: cost {b(ev['total_cost'], lang)}, collected {b(ev['collected'], lang)}, subsidy {b(ev['school_subsidy'], lang)} "
                f"(break-even fee {b(ev['break_even_contribution_per_student'], lang)}/student; needs {ev['students_to_cover_subsidy_whole']} retained or new student to cover subsidy).")
    return text + on_top(r, lang)


def render_documents(r: Dict[str, Any], lang: str) -> str:
    docs = "; ".join(r["documents"])
    return (f"{r['option']} — সাধারণত লাগে: {docs}। {r['note']}" if lang == "bn"
            else f"{r['option']} usually needs: {docs}. {r['note']}")


def render_questions(r: Dict[str, Any], lang: str) -> str:
    q = r["next_question"]
    if not q:
        return "এখন আমার আর কোনো তথ্য লাগবে না।" if lang == "bn" else "I have what I need for now."
    return (f"একটি প্রশ্ন (একবারে একটি): {q['question']}" if lang == "bn" else f"One question (one at a time): {q['question']}")


def render_action(r: Dict[str, Any], lang: str) -> str:
    if r.get("decision") == "NEEDS_APPROVAL":
        return (f"এটি আমি করতে পারি না: {r['reason']}" if lang == "bn" else f"I can't do that myself: {r['reason']}")
    instead = r.get("instead", "")
    return (f"আমি এটি করতে পারি না। {r['reason']} বিকল্প: {instead}" if lang == "bn" else f"I can't do that. {r['reason']} Instead: {instead}")


HELP = {
    "en": ("Of course — I’m here to help. I’m strongest at school cash flow, fee collection, budgeting for a picnic or class party, "
           "staff and expense workflows, admission planning, financing options, and getting the most from FinEdvise. "
           "If your question is outside those areas, I’ll still try to point you in a useful direction. "
           "What are you working on today? For current guidance and activity ideas, live web references appear when configured."),
    "bn": ("অবশ্যই — আমি সাহায্য করতে আছি। স্কুলের নগদ প্রবাহ, ফি আদায়, পিকনিক বা ক্লাস পার্টির বাজেট, "
           "শিক্ষক-কর্মী ও ব্যয়ের কাজ, ভর্তি পরিকল্পনা, অর্থায়ন এবং FinEdvise ব্যবহারে আমি সবচেয়ে ভালো সাহায্য করতে পারি। "
           "প্রশ্নটি অন্য বিষয়ে হলেও আমি উপকারী দিকনির্দেশনা দেওয়ার চেষ্টা করব। আজ কোন কাজে সাহায্য দরকার? "
           "বর্তমান নির্দেশনা ও কার্যক্রমের আইডিয়ার জন্য কনফিগার করা থাকলে লাইভ তথ্যসূত্রও দেখানো হবে।"),
}


def respond(ctx: ToolContext, message: str) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Return (intent, answer_text, tool_results_used)."""
    lang = ctx.lang
    intent = classify(message)
    results: List[Dict[str, Any]] = []

    def call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        out = run_tool(ctx, name, args)
        if out.get("ok"):
            results.append(out["result"])
            return out["result"]
        results.append(out)
        return {}

    if intent.startswith("action:"):
        action = intent.split(":", 1)[1]
        r = call("request_owner_action", {"action": action, "details": message[:200]})
        return intent, render_action(r, lang), results
    if intent == "draft_proposal":
        amount = parse_amount(message)
        plan = _plan_from_text(message)
        args: Dict[str, Any] = {"staged": True}
        if plan:
            args["plan_id"] = plan
        elif amount:
            args.update(amount=amount, staged=False)
        else:
            cmp = call("compare_plans", {})
            args["plan_id"] = cmp.get("recommended_plan_id") or "PLAN_BALANCED"
        r = call("draft_proposal", args)
        return intent, render_draft(r, lang), results
    if intent == "reminders":
        r = call("draft_parent_reminders", {})
        return intent, render_reminders(r, lang), results
    if intent == "loan_documents":
        option = _option_from_text(message)
        r = call("loan_document_checklist", {"option_id": option})
        return intent, render_documents(r, lang), results
    if intent == "extras":
        r = call("evaluate_extras", {})
        return intent, render_extras(r, lang), results
    if intent == "financing":
        args = {}
        plan = _plan_from_text(message)
        amount = parse_amount(message)
        if plan:
            args["plan_id"] = plan
        elif amount:
            args["amount"] = amount
        r = call("match_financing", args)
        return intent, render_financing(r, lang), results
    if intent == "break_even":
        amount = parse_amount(message) or _plan_total(ctx, _plan_from_text(message)) or 77000.0
        r = call("break_even", {"campaign_cost": amount})
        return intent, render_break_even(r, lang), results
    if intent == "compare_plans":
        r = call("compare_plans", {})
        return intent, render_plans(r, lang), results
    if intent == "what_if":
        shocks = parse_shocks(message)
        if not shocks:
            r = call("safe_to_invest", {})
            return intent, render_sti(r, lang, None), results
        base_r = call("safe_to_invest", {})
        r = call("safe_to_invest", shocks)
        return intent, render_what_if(r, base_r, lang), results
    if intent == "safe_to_invest":
        amount = parse_amount(message)
        r = call("safe_to_invest", {"amount": amount} if amount else {})
        return intent, render_sti(r, lang, amount), results
    if intent == "forecast" or intent == "state":
        r = call("get_state", {})
        return intent, render_state(r, lang), results
    if intent == "open_questions":
        r = call("get_open_questions", {})
        return intent, render_questions(r, lang), results
    return "help", HELP["bn" if lang == "bn" else "en"], results


def _plan_from_text(text: str) -> Optional[str]:
    low = text.lower()
    if re.search(AGGRESSIVE_WORDS, low):
        return "PLAN_AGGRESSIVE"
    if re.search(BALANCED_WORDS, low):
        return "PLAN_BALANCED"
    if re.search(CONSERVATIVE_WORDS, low):
        return "PLAN_CONSERVATIVE"
    return None


def _option_from_text(text: str) -> str:
    low = text.lower()
    if re.search(r"refinance|cmsme|9\s*%|পুনঃঅর্থায়ন", low):
        return "BANK_CMSME_REFINANCE"
    if re.search(r"ngo|mfi|micro|এনজিও|ক্ষুদ্র", low):
        return "NGO_MFI_ENTERPRISE"
    if re.search(r"supplier|press|ছাপাখানা|প্রেস", low):
        return "SUPPLIER_CREDIT_PRESS"
    return "BANK_SME_MARKET"


def _plan_total(ctx: ToolContext, plan_id: Optional[str]) -> Optional[float]:
    if not plan_id:
        return None
    plan = next((p for p in ctx.sandbox.seed["plans"] if p["id"] == plan_id), None)
    return float(sum(i["amount"] for i in plan["items"])) if plan else None
