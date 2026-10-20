"""Sandbox state: proposals, approvals, the sandbox ledger journal and settings.

Every state change goes through policy.evaluate() and is written to the
append-only audit log with server time. Approved proposals are posted to the
sandbox ledger journal (also append-only); the "plan" view of the forecast
adds those postings, while the "baseline" view never does.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import engine, financing
from .audit import ChainedLog, canonical, sha256, utc_now
from .csv_import import validate_register
from .data import ROOT, clone, load_catalogue, load_school, outstanding_tuition, scenario_date
from .policy import Decision, evaluate

DEFAULT_VAR = ROOT / "var"


class PolicyDenied(Exception):
    def __init__(self, decision: Decision) -> None:
        super().__init__(decision.reason_en)
        self.decision = decision


class Sandbox:
    def __init__(self, var_dir: Optional[Path] = None, data_path: Optional[Path] = None,
                 catalogue_path: Optional[Path] = None) -> None:
        self.var = Path(var_dir or os.environ.get("FINEDVISE_VAR_DIR") or DEFAULT_VAR)
        self.var.mkdir(parents=True, exist_ok=True)
        self.seed = load_school(data_path)
        self.catalogue = load_catalogue(catalogue_path)
        self.audit = ChainedLog(self.var / "audit_log.jsonl")
        self.journal = ChainedLog(self.var / "sandbox_ledger.jsonl")
        self.state_path = self.var / "state.json"
        self._lock = threading.RLock()
        self.state = self._load_state()

    # ------------------------------------------------------------------ state
    def _empty_state(self) -> Dict[str, Any]:
        return {"proposals": {}, "profile": {}, "reserve": None, "imports": {}, "applied_register": [],
                "counters": {"proposal": 0, "import": 0}, "created_utc": utc_now()}

    def _load_state(self) -> Dict[str, Any]:
        if self.state_path.exists():
            with open(self.state_path, encoding="utf-8") as handle:
                return json.load(handle)
        state = self._empty_state()
        self._write(state)
        self.audit.append("SANDBOX_CREATED", "system", details={"data_version": self.seed["meta"]["data_version"]})
        return state

    def _write(self, state: Optional[Dict[str, Any]] = None) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(state or self.state, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    def data(self) -> Dict[str, Any]:
        """The school data with owner settings applied (a copy; the seed file is never changed)."""
        data = clone(self.seed)
        if self.state.get("reserve") is not None:
            data["reserve_policy"]["minimum_reserve"] = self.state["reserve"]
            data["reserve_policy"]["status"] = "OWNER_SET"
        return data

    def profile(self) -> Dict[str, Any]:
        return {k: v["value"] for k, v in self.state["profile"].items()}

    # ---------------------------------------------------------------- policy
    def decide(self, action: str, actor: str, context: Optional[Dict[str, Any]] = None,
               details: Optional[Dict[str, Any]] = None, source: str = "screen") -> Decision:
        decision = evaluate(action, actor, context)
        self.audit.append("POLICY_DECISION", actor, action=action, tier=decision.tier, decision=decision.decision,
                          rule=decision.rule, source=source, details=details or {})
        return decision

    def require(self, action: str, actor: str, context: Optional[Dict[str, Any]] = None,
                details: Optional[Dict[str, Any]] = None, source: str = "screen") -> Decision:
        decision = self.decide(action, actor, context, details, source)
        if not decision.allowed:
            raise PolicyDenied(decision)
        return decision

    # ----------------------------------------------------------- commitments
    def postings(self) -> List[Dict[str, Any]]:
        """POSTING entries since the last RESET (the journal itself is never edited)."""
        return self.active_postings_since_reset()

    def commitments(self) -> List[Dict[str, Any]]:
        lines: List[Dict[str, Any]] = []
        for entry in self.postings():
            lines.extend(entry.get("lines", []))
        return lines

    # -------------------------------------------------------------- proposals
    def _proposal_content(self, plan_id: Optional[str], amount: Optional[float], staged: bool,
                          spend_week: int, note: str) -> Dict[str, Any]:
        data = self.data()
        start, n = engine.horizon(data)
        if plan_id:
            plan = next((p for p in data["plans"] if p["id"] == plan_id), None)
            if plan is None:
                raise ValueError(f"unknown plan {plan_id}")
            spends, items, staging_cost = engine.plan_schedule(plan, staged)
            title_en = f"{plan['name_en']} admission budget" + (" (staged)" if staged else " (paid now)")
            title_bn = f"{plan['name_bn']} ভর্তি বাজেট" + (" (ধাপে ধাপে)" if staged else " (এখনই পরিশোধ)")
        else:
            if not 1 <= spend_week <= n:
                raise ValueError("spend_week outside the horizon")
            items = [{"id": "X1", "label_en": "Admission campaign spending", "label_bn": "ভর্তি প্রচারণার খরচ",
                      "amount": float(amount), "pay_week": spend_week, "staging_cost": 0.0, "flex": None}]
            spends = {spend_week: float(amount)}
            staging_cost = 0.0
            title_en, title_bn = "Custom admission budget", "নিজস্ব ভর্তি বাজেট"
        total = float(sum(i["amount"] for i in items))
        schedule = []
        for item in items:
            pay_date = start + timedelta(days=7 * (item["pay_week"] - 1))
            schedule.append({"item_id": item["id"], "label_en": item["label_en"], "label_bn": item["label_bn"],
                             "amount": item["amount"], "pay_week": item["pay_week"], "pay_date": pay_date.isoformat(),
                             "staging_cost": item.get("staging_cost", 0.0)})
        commitments = self.commitments()
        c0 = engine.opening_cash(data).value
        reserve = engine.reserve_amount(data)
        base_weeks, _, _ = engine.build_weeks(data, engine.BASE, commitments)
        stress_weeks, _, _ = engine.build_weeks(data, engine.DOWNSIDE, commitments)
        base_rows = engine.cash_path(c0, base_weeks, reserve, spends)
        stress_rows = engine.cash_path(c0, stress_weeks, reserve, spends)
        return {
            "kind": "admission_budget",
            "plan_id": plan_id,
            "staged": bool(staged) if plan_id else False,
            "title_en": title_en,
            "title_bn": title_bn,
            "total": total,
            "staging_cost": staging_cost,
            "schedule": schedule,
            "checks": {
                "reserve": reserve,
                "base_ok": all(r["status"] == "OK" for r in base_rows),
                "stress_ok": all(r["status"] == "OK" for r in stress_rows),
                "base_worst": min(base_rows, key=lambda r: r["headroom"])["label"],
                "stress_worst": min(stress_rows, key=lambda r: r["headroom"])["label"],
                "stress_definition": engine.DOWNSIDE.to_dict(),
            },
            "note": (note or "")[:500],
            "data_version": data["meta"]["data_version"],
        }

    def create_proposal(self, actor: str, plan_id: Optional[str] = None, amount: Optional[float] = None,
                        staged: bool = True, spend_week: int = 1, note: str = "", source: str = "screen") -> Tuple[Decision, Optional[Dict[str, Any]]]:
        with self._lock:
            if plan_id is None and (amount is None or isinstance(amount, bool) or not isinstance(amount, (int, float))):
                decision = self.decide("draft_proposal", actor, {"amount": None}, {"plan_id": plan_id}, source)
                return decision, None
            preview_amount = amount
            if plan_id:
                plan = next((p for p in self.seed["plans"] if p["id"] == plan_id), None)
                preview_amount = engine.plan_total(plan) if plan else None
            decision = self.decide("draft_proposal", actor, {"amount": preview_amount},
                                   {"plan_id": plan_id, "amount": preview_amount, "staged": staged}, source)
            if not decision.allowed:
                return decision, None
            content = self._proposal_content(plan_id, amount, staged, spend_week, note)
            self.state["counters"]["proposal"] += 1
            pid = f"P-{self.state['counters']['proposal']:04d}"
            proposal = {
                "id": pid, "status": "pending", "created_by": actor, "created_utc": utc_now(),
                "content": content, "content_hash": sha256(canonical(content)),
                "decided_by": None, "decided_utc": None, "decision_note": None, "posting_seq": None,
            }
            self.state["proposals"][pid] = proposal
            self._write()
            self.audit.append("DRAFT_CREATED", actor, proposal_id=pid, content_hash=proposal["content_hash"],
                              total=content["total"], title=content["title_en"], source=source)
            return decision, proposal

    def _hash_at_creation(self, pid: str) -> Optional[str]:
        for entry in self.audit.entries():
            if entry["event"] == "DRAFT_CREATED" and entry.get("proposal_id") == pid:
                return entry.get("content_hash")
        return None

    def approve(self, actor: str, pid: str, submitted_hash: str, source: str = "screen") -> Tuple[Decision, Optional[Dict[str, Any]]]:
        with self._lock:
            proposal = self.state["proposals"].get(pid)
            recomputed = sha256(canonical(proposal["content"])) if proposal else None
            logged = self._hash_at_creation(pid) if proposal else None
            context = {"proposal": proposal, "submitted_hash": submitted_hash,
                       "recomputed_hash": recomputed if recomputed == logged else "mismatch-with-audit-log"}
            decision = self.decide("approve_proposal", actor, context, {"proposal_id": pid, "submitted_hash": submitted_hash}, source)
            if not decision.allowed:
                return decision, proposal
            lines = []
            for item in proposal["content"]["schedule"]:
                lines.append({
                    "id": f"{pid}-{item['item_id']}", "date": item["pay_date"], "type": "payment",
                    "category": "admission_campaign", "amount": item["amount"], "status": "committed",
                    "desc_en": item["label_en"], "desc_bn": item["label_bn"],
                })
            posting = self.journal.append("POSTING", actor, proposal_id=pid, content_hash=proposal["content_hash"],
                                          total=proposal["content"]["total"], lines=lines)
            proposal.update(status="approved", decided_by=actor, decided_utc=utc_now(), posting_seq=posting["seq"])
            self._write()
            self.audit.append("OWNER_APPROVED", actor, proposal_id=pid, content_hash=proposal["content_hash"],
                              posting_seq=posting["seq"], posting_hash=posting["hash"], source=source)
            return decision, proposal

    def reject(self, actor: str, pid: str, note: str = "", source: str = "screen") -> Tuple[Decision, Optional[Dict[str, Any]]]:
        with self._lock:
            proposal = self.state["proposals"].get(pid)
            decision = self.decide("reject_proposal", actor, {"proposal": proposal}, {"proposal_id": pid}, source)
            if not decision.allowed:
                return decision, proposal
            proposal.update(status="rejected", decided_by=actor, decided_utc=utc_now(), decision_note=(note or "")[:300])
            self._write()
            self.audit.append("OWNER_REJECTED", actor, proposal_id=pid, source=source)
            return decision, proposal

    def proposals(self) -> List[Dict[str, Any]]:
        return sorted(self.state["proposals"].values(), key=lambda p: p["id"], reverse=True)

    # --------------------------------------------------------------- settings
    def set_reserve(self, actor: str, amount: Any, source: str = "screen") -> Decision:
        with self._lock:
            old = engine.reserve_amount(self.data())
            decision = self.decide("set_reserve", actor, {"amount": amount}, {"old": old, "new": amount}, source)
            if decision.allowed:
                self.state["reserve"] = float(amount)
                self._write()
                self.audit.append("RESERVE_CHANGED", actor, old=old, new=float(amount), source=source)
            return decision

    def set_answer(self, actor: str, question_id: str, value: Any, via: str = "screen") -> Decision:
        with self._lock:
            known = {q["id"]: q for q in self.catalogue["eligibility_questions"]}
            for q in self.seed["open_questions"]:
                if q["id"] != "Q_RESERVE":  # the reserve is changed only through set_reserve
                    known[q["id"]] = {**q, "kind": "text"}
            ok = question_id in known
            if ok:
                kind = known[question_id]["kind"]
                if kind == "yes_no" and not isinstance(value, bool):
                    ok = False
                if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 600):
                    ok = False
                if kind == "text" and (not isinstance(value, str) or not value.strip() or len(value) > 300):
                    ok = False
            action = "record_owner_answer" if actor == "agent" else "set_eligibility_answer"
            decision = self.decide(action, actor, {"question_ok": ok}, {"question_id": question_id, "value": value}, via)
            if decision.allowed and ok:
                self.state["profile"][question_id] = {"value": value, "by": actor, "via": via, "time_utc": utc_now()}
                self._write()
            elif decision.allowed and not ok:
                return evaluate("set_eligibility_answer", "owner", {"question_ok": False})
            return decision

    # ---------------------------------------------------------------- imports
    def stage_import(self, actor: str, text: str, filename: str = "upload.csv", source: str = "screen") -> Dict[str, Any]:
        with self._lock:
            self.require("stage_import", actor, {}, {"filename": filename[:80]}, source)
            report = validate_register(text, self.seed["roster"]["students"], scenario_date(self.seed))
            self.state["counters"]["import"] += 1
            iid = f"I-{self.state['counters']['import']:04d}"
            self.state["imports"][iid] = {"id": iid, "status": "staged", "filename": filename[:80], "created_utc": utc_now(),
                                          "by": actor, "report": report, "content_hash": sha256(text)}
            self._write()
            self.audit.append("IMPORT_STAGED", actor, import_id=iid, summary=report["summary"], source=source)
            return {"import_id": iid, **report, "dues_preview": self.dues(extra=report["rows"])}

    def commit_import(self, actor: str, iid: str, source: str = "screen") -> Tuple[Decision, Optional[Dict[str, Any]]]:
        with self._lock:
            item = self.state["imports"].get(iid)
            ok = bool(item) and item["status"] == "staged"
            decision = self.decide("commit_import", actor, {"import_ok": ok}, {"import_id": iid}, source)
            if not decision.allowed:
                return decision, item
            accepted = [r for r in item["report"]["rows"] if r["status"] == "accepted"]
            already = {r["receipt_no"] for r in self.state["applied_register"]}
            fresh = [r for r in accepted if r["receipt_no"] not in already]
            self.state["applied_register"].extend(
                {"receipt_no": r["receipt_no"], "student_id": r["student_id"], "amount": r["amount"], "date": r["date"]} for r in fresh)
            item["status"] = "committed"
            self._write()
            entry = self.journal.append("REGISTER_IMPORT", actor, import_id=iid, rows=len(fresh),
                                        amount=float(sum(r["amount"] for r in fresh)),
                                        receipts=[r["receipt_no"] for r in fresh])
            self.audit.append("IMPORT_COMMITTED", actor, import_id=iid, rows=len(fresh), journal_seq=entry["seq"], source=source)
            return decision, item

    def dues(self, extra: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Per-student dues after applied register rows, reconciled against the ledger total."""
        students = self.seed["roster"]["students"]
        paid: Dict[str, float] = {}
        for r in self.state["applied_register"]:
            paid[r["student_id"]] = paid.get(r["student_id"], 0.0) + r["amount"]
        preview: Dict[str, float] = dict(paid)
        applied = {r["receipt_no"] for r in self.state["applied_register"]}
        for r in (extra or []):
            if r["status"] == "accepted" and r["receipt_no"] not in applied:
                preview[r["student_id"]] = preview.get(r["student_id"], 0.0) + r["amount"]
        rows = []
        for s in students:
            due_now = max(0.0, s["dues_before_register"] - paid.get(s["id"], 0.0))
            due_preview = max(0.0, s["dues_before_register"] - preview.get(s["id"], 0.0))
            rows.append({"student_id": s["id"], "name": s["name"], "class": s["class"], "guardian": s["guardian"],
                         "monthly_fee": s["monthly_fee"], "status": s["status"], "dues": due_now,
                         "dues_after_import": due_preview, "months_due": round(due_now / s["monthly_fee"], 1) if s["monthly_fee"] else 0})
        ledger_total = outstanding_tuition(self.seed).value
        total_now = sum(r["dues"] for r in rows)
        total_preview = sum(r["dues_after_import"] for r in rows)
        return {"students": rows, "ledger_outstanding": ledger_total, "per_student_total": total_now,
                "per_student_total_after_import": total_preview, "reconciled": abs(total_now - ledger_total) < 0.5,
                "reconciled_after_import": abs(total_preview - ledger_total) < 0.5,
                "difference": total_now - ledger_total}

    # ------------------------------------------------------------------ reset
    def reset(self, actor: str, source: str = "screen") -> Decision:
        with self._lock:
            decision = self.decide("reset_sandbox", actor, {}, {}, source)
            if not decision.allowed:
                return decision
            self.state = self._empty_state()
            self._write()
            # the journal is append-only: record the reset instead of deleting postings
            self.journal.append("RESET", actor, note="Sandbox reset; earlier postings no longer apply.")
            self.audit.append("SANDBOX_RESET", actor, source=source)
            return decision

    def active_postings_since_reset(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for entry in self.journal.entries():
            if entry["event"] == "RESET":
                out = []
            elif entry["event"] == "POSTING":
                out.append(entry)
        return out
