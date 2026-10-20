"""The evidence runner: one full sandbox story, written to files."""
import json
import tempfile
import unittest
from pathlib import Path

from finedvise import sandbox
from finedvise.router import _plan_from_text, classify


class EvidenceRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        cls.summary = sandbox.run(cls.out, None)

    def test_files_are_written(self):
        for name in ("sandbox_execution_log.json", "audit_log.jsonl", "sandbox_ledger.jsonl", "redteam_results.json",
                     "parent_reminder_drafts.txt", "decision_memo_P-0001_en.html", "decision_memo_P-0001_bn.html"):
            self.assertTrue((self.out / name).is_file(), name)
        saved = json.loads((self.out / "sandbox_execution_log.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["red_team"], self.summary["red_team"])

    def test_story_holds_together(self):
        s = self.summary
        self.assertTrue(s["audit_log"]["chain_ok"])
        self.assertTrue(s["sandbox_ledger"]["chain_ok"])
        self.assertTrue(s["guardrail_all_passed"])
        self.assertEqual(s["red_team"], "23/23 passed")
        attempts = [st["decision"] for st in s["steps"] if st["kind"] in ("approval_attempt", "owner_approval")]
        self.assertEqual(attempts, ["DENY", "NEEDS_APPROVAL", "ALLOW"])
        chats = [st for st in s["steps"] if st["kind"] == "chat"]
        self.assertFalse(any(st["ledger_changed"] for st in chats), "no chat turn may write to the ledger")
        forecast = next(st for st in s["steps"] if st["kind"] == "forecast")
        self.assertEqual((forecast["safe_to_invest_base"], forecast["safe_to_invest_stress"]), (77000, 32000))

    def test_bengali_replies_are_shown_with_bengali_digits(self):
        bn = [st for st in self.summary["steps"] if st["kind"] == "chat" and st["lang"] == "bn"]
        self.assertTrue(bn)
        for st in bn:
            self.assertFalse(any(ch.isdigit() and ch.isascii() for ch in st["reply_as_shown"]), st["reply_as_shown"])


class PlanWords(unittest.TestCase):
    def test_bengali_and_english_names_for_plans(self):
        self.assertEqual(_plan_from_text("আক্রমণাত্মক পরিকল্পনার জন্য কি ঋণ লাগবে?"), "PLAN_AGGRESSIVE")
        self.assertEqual(_plan_from_text("ব্যালান্সড প্ল্যান"), "PLAN_BALANCED")
        self.assertEqual(_plan_from_text("the cautious option"), "PLAN_CONSERVATIVE")
        self.assertEqual(classify("আগ্রাসী আর রক্ষণশীলের তুলনা"), "compare_plans")


if __name__ == "__main__":
    unittest.main()
