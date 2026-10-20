"""Permission policy: one function decides every action.

evaluate(action, actor, context) -> Decision(ALLOW | NEEDS_APPROVAL | DENY, reason)

Tiers
  READ        look at data                          -> ALLOW for everyone
  SIMULATE    what-if maths, never writes records   -> ALLOW for everyone
  DRAFT       prepare something with no effect yet  -> ALLOW for everyone
  COMMIT      change the plan or the sandbox ledger -> owner only, with checks;
                                                       the agent gets NEEDS_APPROVAL
  PROHIBITED  move money, delete or edit records,   -> DENY for everyone; the app has
              contact people, apply for loans          no code that can do these
Unknown actions are denied (default deny). Security comes from this rule
table and from the tools that exist, not from keyword matching.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

READ, SIMULATE, DRAFT, COMMIT, PROHIBITED = "READ", "SIMULATE", "DRAFT", "COMMIT", "PROHIBITED"
ALLOW, NEEDS_APPROVAL, DENY = "ALLOW", "NEEDS_APPROVAL", "DENY"
ROLES = ("owner", "accountant", "agent")

ACTIONS: Dict[str, str] = {
    # agent tools
    "get_state": READ,
    "get_weekly_forecast": READ,
    "get_open_questions": READ,
    "loan_document_checklist": READ,
    "safe_to_invest": SIMULATE,
    "compare_plans": SIMULATE,
    "break_even": SIMULATE,
    "match_financing": SIMULATE,
    "evaluate_extras": SIMULATE,
    "draft_proposal": DRAFT,
    "draft_parent_reminders": DRAFT,
    "record_owner_answer": DRAFT,
    "request_owner_action": READ,      # only asks the policy and explains; never executes
    # screen actions
    "view_audit_log": READ,
    "run_red_team": SIMULATE,
    "stage_import": DRAFT,
    "approve_proposal": COMMIT,
    "reject_proposal": COMMIT,
    "set_reserve": COMMIT,
    "commit_import": COMMIT,
    "set_eligibility_answer": COMMIT,
    "reset_sandbox": COMMIT,
    # never possible in this app
    "execute_payment": PROHIBITED,
    "transfer_funds": PROHIBITED,
    "delete_record": PROHIBITED,
    "edit_record": PROHIBITED,
    "disable_audit_log": PROHIBITED,
    "send_message_to_parents": PROHIBITED,
    "apply_for_loan": PROHIBITED,
    "share_data_externally": PROHIBITED,
    "ignore_reserve_policy": PROHIBITED,
}

REASONS = {
    "unknown": ("Action is not in the policy, so it is denied by default.", "এই কাজটি নীতিতে নেই, তাই ডিফল্টভাবে নিষিদ্ধ।"),
    "prohibited": ("This app has no ability to do this: it cannot move money, change or delete records, contact people or apply for loans.",
                   "এই অ্যাপ এটি করতে পারে না: টাকা পাঠানো, রেকর্ড বদলানো বা মোছা, কারো সাথে যোগাযোগ বা ঋণের আবেদন সম্ভব নয়।"),
    "read": ("Reading data is allowed.", "ডেটা দেখা অনুমোদিত।"),
    "simulate": ("Simulation only; nothing is written to records.", "শুধু হিসাব; কোনো রেকর্ডে কিছু লেখা হয় না।"),
    "draft": ("Draft only; it has no effect until the owner approves it.", "শুধু খসড়া; মালিক অনুমোদন না দেওয়া পর্যন্ত এর কোনো প্রভাব নেই।"),
    "agent_commit": ("Only the owner can do this, with the Approve button. The agent can prepare a draft.",
                     "শুধু মালিক 'অনুমোদন' বোতাম দিয়ে এটি করতে পারেন। এজেন্ট খসড়া তৈরি করতে পারে।"),
    "role": ("Only the owner role can do this.", "শুধু মালিকের ভূমিকায় এটি করা যায়।"),
    "unknown_role": ("Unknown role.", "অজানা ভূমিকা।"),
    "no_proposal": ("Proposal not found.", "প্রস্তাবটি পাওয়া যায়নি।"),
    "not_pending": ("This proposal was already decided.", "এই প্রস্তাবের সিদ্ধান্ত আগেই হয়েছে।"),
    "hash_mismatch": ("The proposal's content does not match what was approved (hash mismatch).",
                      "প্রস্তাবের বিষয়বস্তু অনুমোদিত সংস্করণের সাথে মেলে না (হ্যাশ মেলেনি)।"),
    "commit_ok": ("Owner action with matching content and role.", "মালিকের কাজ; বিষয়বস্তু ও ভূমিকা মিলেছে।"),
    "bad_amount": ("The amount is missing, not a number, negative or too large.", "পরিমাণ নেই, সংখ্যা নয়, ঋণাত্মক বা অনেক বড়।"),
    "no_import": ("Import not found or already committed.", "ইমপোর্ট পাওয়া যায়নি বা আগেই যোগ হয়েছে।"),
    "bad_answer": ("Unknown eligibility question.", "অজানা যোগ্যতার প্রশ্ন।"),
}

MAX_AMOUNT = 10_000_000


@dataclass
class Decision:
    action: str
    actor: str
    tier: str
    decision: str
    reason_en: str
    reason_bn: str
    rule: str

    @property
    def allowed(self) -> bool:
        return self.decision == ALLOW

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _d(action: str, actor: str, tier: str, decision: str, rule: str) -> Decision:
    en, bn = REASONS[rule]
    return Decision(action, actor, tier, decision, en, bn, rule)


def _valid_amount(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0 <= value <= MAX_AMOUNT)


def evaluate(action: str, actor: str, context: Optional[Dict[str, Any]] = None) -> Decision:
    context = context or {}
    tier = ACTIONS.get(action)
    if actor not in ROLES:
        return _d(action, actor, tier or "UNKNOWN", DENY, "unknown_role")
    if tier is None:
        return _d(action, actor, "UNKNOWN", DENY, "unknown")
    if tier == PROHIBITED:
        return _d(action, actor, tier, DENY, "prohibited")
    if tier == READ:
        return _d(action, actor, tier, ALLOW, "read")
    if tier == SIMULATE:
        return _d(action, actor, tier, ALLOW, "simulate")
    if tier == DRAFT:
        if action == "draft_proposal" and not _valid_amount(context.get("amount")):
            return _d(action, actor, tier, DENY, "bad_amount")
        return _d(action, actor, tier, ALLOW, "draft")

    # COMMIT
    if actor == "agent":
        return _d(action, actor, tier, NEEDS_APPROVAL, "agent_commit")
    if actor != "owner":
        return _d(action, actor, tier, DENY, "role")
    if action in ("approve_proposal", "reject_proposal"):
        proposal = context.get("proposal")
        if not proposal:
            return _d(action, actor, tier, DENY, "no_proposal")
        if proposal.get("status") != "pending":
            return _d(action, actor, tier, DENY, "not_pending")
        if action == "approve_proposal":
            submitted = context.get("submitted_hash")
            recomputed = context.get("recomputed_hash")
            if not submitted or submitted != proposal.get("content_hash") or recomputed != proposal.get("content_hash"):
                return _d(action, actor, tier, DENY, "hash_mismatch")
        return _d(action, actor, tier, ALLOW, "commit_ok")
    if action == "set_reserve":
        if not _valid_amount(context.get("amount")):
            return _d(action, actor, tier, DENY, "bad_amount")
        return _d(action, actor, tier, ALLOW, "commit_ok")
    if action == "commit_import":
        if not context.get("import_ok"):
            return _d(action, actor, tier, DENY, "no_import")
        return _d(action, actor, tier, ALLOW, "commit_ok")
    if action == "set_eligibility_answer":
        if not context.get("question_ok"):
            return _d(action, actor, tier, DENY, "bad_answer")
        return _d(action, actor, tier, ALLOW, "commit_ok")
    return _d(action, actor, tier, ALLOW, "commit_ok")


def tier_table() -> list:
    """For the Security screen and the docs."""
    out = []
    for action, tier in ACTIONS.items():
        row = {"action": action, "tier": tier}
        for role in ROLES:
            row[role] = evaluate(action, role, _example_context(action)).decision
        out.append(row)
    return out


def _example_context(action: str) -> Dict[str, Any]:
    if action in ("approve_proposal", "reject_proposal"):
        proposal = {"status": "pending", "content_hash": "h"}
        return {"proposal": proposal, "submitted_hash": "h", "recomputed_hash": "h"}
    if action in ("set_reserve", "draft_proposal"):
        return {"amount": 50000}
    if action == "commit_import":
        return {"import_ok": True}
    if action == "set_eligibility_answer":
        return {"question_ok": True}
    return {}
