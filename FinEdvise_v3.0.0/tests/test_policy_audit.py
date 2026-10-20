"""The policy can say yes as well as no; approvals need role and hash; logs are tamper-evident."""
import json
import tempfile
import unittest
from pathlib import Path

from finedvise.audit import ChainedLog
from finedvise.policy import ACTIONS, ALLOW, DENY, NEEDS_APPROVAL, evaluate, tier_table

from tests.helpers import sandbox


class PolicyDecisions(unittest.TestCase):
    def test_read_simulate_and_draft_are_allowed(self):
        for action in ("get_state", "safe_to_invest", "compare_plans", "match_financing", "draft_parent_reminders"):
            for actor in ("owner", "accountant", "agent"):
                self.assertEqual(evaluate(action, actor).decision, ALLOW, (action, actor))
        self.assertEqual(evaluate("draft_proposal", "agent", {"amount": 77000}).decision, ALLOW)

    def test_commit_needs_the_owner(self):
        ctx = {"proposal": {"status": "pending", "content_hash": "h"}, "submitted_hash": "h", "recomputed_hash": "h"}
        self.assertEqual(evaluate("approve_proposal", "owner", ctx).decision, ALLOW)
        self.assertEqual(evaluate("approve_proposal", "accountant", ctx).decision, DENY)
        self.assertEqual(evaluate("approve_proposal", "agent", ctx).decision, NEEDS_APPROVAL)

    def test_hash_and_status_checks(self):
        pending = {"status": "pending", "content_hash": "h"}
        self.assertEqual(evaluate("approve_proposal", "owner", {"proposal": pending, "submitted_hash": "x", "recomputed_hash": "h"}).rule, "hash_mismatch")
        self.assertEqual(evaluate("approve_proposal", "owner", {"proposal": pending, "submitted_hash": "h", "recomputed_hash": "x"}).rule, "hash_mismatch")
        done = {"status": "approved", "content_hash": "h"}
        self.assertEqual(evaluate("approve_proposal", "owner", {"proposal": done, "submitted_hash": "h", "recomputed_hash": "h"}).rule, "not_pending")

    def test_prohibited_for_everyone_and_unknown_denied(self):
        for action, tier in ACTIONS.items():
            if tier == "PROHIBITED":
                for actor in ("owner", "accountant", "agent"):
                    self.assertEqual(evaluate(action, actor).decision, DENY)
        self.assertEqual(evaluate("pay_vendor", "owner").rule, "unknown")
        self.assertEqual(evaluate("get_state", "hacker").rule, "unknown_role")

    def test_amount_validation(self):
        self.assertEqual(evaluate("set_reserve", "owner", {"amount": -1}).decision, DENY)
        self.assertEqual(evaluate("set_reserve", "owner", {"amount": float("inf")}).decision, DENY)
        self.assertEqual(evaluate("draft_proposal", "agent", {"amount": "lots"}).decision, DENY)

    def test_tier_table_covers_every_action(self):
        self.assertEqual(len(tier_table()), len(ACTIONS))


class SandboxFlow(unittest.TestCase):
    def test_forecast_alert_draft_approve_post(self):
        sb = sandbox()
        d, p = sb.create_proposal("agent", plan_id="PLAN_BALANCED", staged=True)
        self.assertEqual((d.decision, p["status"]), (ALLOW, "pending"))
        self.assertEqual(sb.commitments(), [])  # a draft changes nothing
        self.assertEqual(sb.approve("agent", p["id"], p["content_hash"])[0].decision, NEEDS_APPROVAL)
        self.assertEqual(sb.approve("accountant", p["id"], p["content_hash"])[0].decision, DENY)
        self.assertEqual(sb.approve("owner", p["id"], "0" * 64)[0].decision, DENY)
        d, p = sb.approve("owner", p["id"], p["content_hash"])
        self.assertEqual((d.decision, p["status"]), (ALLOW, "approved"))
        self.assertEqual(sum(l["amount"] for l in sb.commitments()), 77000)
        self.assertEqual(sb.approve("owner", p["id"], p["content_hash"])[0].rule, "not_pending")

    def test_editing_a_stored_draft_blocks_its_approval(self):
        sb = sandbox()
        _, p = sb.create_proposal("owner", plan_id="PLAN_CONSERVATIVE", staged=False)
        sb.state["proposals"][p["id"]]["content"]["total"] = 1
        self.assertEqual(sb.approve("owner", p["id"], p["content_hash"])[0].rule, "hash_mismatch")

    def test_reserve_change_is_owner_only_and_logged(self):
        sb = sandbox()
        self.assertEqual(sb.set_reserve("accountant", 60000).decision, DENY)
        self.assertEqual(sb.set_reserve("owner", 60000).decision, ALLOW)
        self.assertEqual(sb.data()["reserve_policy"]["minimum_reserve"], 60000)
        self.assertTrue(any(e["event"] == "RESERVE_CHANGED" for e in sb.audit.entries()))

    def test_reset_keeps_the_logs(self):
        sb = sandbox()
        _, p = sb.create_proposal("owner", plan_id="PLAN_BALANCED")
        sb.approve("owner", p["id"], p["content_hash"])
        self.assertEqual(sb.reset("accountant").decision, DENY)
        self.assertEqual(sb.reset("owner").decision, ALLOW)
        self.assertEqual(sb.commitments(), [])
        self.assertTrue(sb.audit.verify()["ok"])
        self.assertEqual([e["event"] for e in sb.journal.entries()], ["POSTING", "RESET"])


class AuditChain(unittest.TestCase):
    def test_fresh_log_has_no_pre_filled_rows(self):
        sb = sandbox()
        self.assertEqual([e["event"] for e in sb.audit.entries()], ["SANDBOX_CREATED"])

    def test_server_time_and_chain(self):
        log = ChainedLog(Path(tempfile.mkdtemp()) / "a.jsonl")
        for i in range(3):
            log.append("TEST", "owner", n=i)
        rows = log.entries()
        self.assertTrue(all(r["time_utc"].endswith("Z") for r in rows))
        self.assertEqual(rows[1]["prev_hash"], rows[0]["hash"])
        self.assertTrue(log.verify()["ok"])

    def test_editing_or_deleting_a_line_is_detected(self):
        path = Path(tempfile.mkdtemp()) / "a.jsonl"
        log = ChainedLog(path)
        for i in range(4):
            log.append("TEST", "owner", n=i)
        lines = path.read_text(encoding="utf-8").splitlines()
        edited = json.loads(lines[2]); edited["n"] = 99
        path.write_text("\n".join(lines[:2] + [json.dumps(edited)] + lines[3:]) + "\n", encoding="utf-8")
        self.assertEqual(ChainedLog(path).verify()["broken_at"], 3)
        path.write_text("\n".join(lines[:1] + lines[2:]) + "\n", encoding="utf-8")
        self.assertFalse(ChainedLog(path).verify()["ok"])


if __name__ == "__main__":
    unittest.main()
