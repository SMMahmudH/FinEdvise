"""CSV validation, the decision memo, extras and the red-team suite."""
import unittest
from datetime import date
from pathlib import Path

from finedvise import extras, memo, redteam
from finedvise.csv_import import validate_register
from finedvise.data import ROOT

from tests.helpers import sandbox, school

MESSY = (ROOT / "data" / "samples" / "fee_register_messy.csv").read_text(encoding="utf-8")


class CsvImport(unittest.TestCase):
    def setUp(self):
        self.report = validate_register(MESSY, school()["roster"]["students"], date(2026, 11, 15))
        self.by_row = {r["row"]: r for r in self.report["rows"]}

    def codes(self, row):
        return [m["code"] for m in self.by_row[row]["messages"]]

    def test_summary(self):
        s = self.report["summary"]
        self.assertEqual((s["accepted"], s["accepted_amount"], s["held"], s["rejected"], s["flagged_memos"]), (8, 10200, 1, 6, 2))

    def test_each_mess_gets_its_message(self):
        self.assertIn("duplicate", self.codes(3))
        self.assertIn("partial", self.codes(4))
        self.assertEqual(self.by_row[5]["status"], "held")
        self.assertIn("withdrawn", self.codes(5))
        self.assertIn("missing_date", self.codes(6))
        self.assertIn("normalised", self.codes(7))       # ১২০০ in Bengali digits
        self.assertIn("unknown_student", self.codes(8))
        self.assertIn("non_positive", self.codes(9))
        self.assertIn("memo_flag", self.codes(10))       # instructions in the memo are data
        self.assertIn("future_date", self.codes(12))
        self.assertIn("multi_month", self.codes(13))
        self.assertIn("bad_amount", self.codes(16))

    def test_memo_text_is_kept_verbatim_as_data(self):
        self.assertIn("<script>", self.by_row[15]["memo"])

    def test_import_needs_the_owner_and_reconciles_dues(self):
        sb = sandbox()
        staged = sb.stage_import("accountant", MESSY, "messy.csv")
        self.assertFalse(sb.dues()["reconciled"])
        self.assertTrue(staged["dues_preview"]["reconciled_after_import"])
        self.assertEqual(sb.commit_import("accountant", staged["import_id"])[0].decision, "DENY")
        self.assertEqual(sb.commit_import("owner", staged["import_id"])[0].decision, "ALLOW")
        self.assertTrue(sb.dues()["reconciled"])
        self.assertEqual(sb.dues()["per_student_total"], 64400)
        self.assertEqual(sb.commit_import("owner", staged["import_id"])[0].decision, "DENY")  # only once

    def test_missing_columns_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_register("a,b\n1,2\n", school()["roster"]["students"], date(2026, 11, 15))


class DecisionMemo(unittest.TestCase):
    def test_memo_has_engine_numbers_and_escapes_text(self):
        sb = sandbox()
        _, p = sb.create_proposal("owner", plan_id="PLAN_BALANCED", staged=True, note="<b>bold</b> & <script>x</script>")
        sb.approve("owner", p["id"], p["content_hash"])
        html = memo.render(sb, p["id"], "en")
        self.assertIn("BDT 77,000", html)
        self.assertIn(p["content_hash"], html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>x", html)
        self.assertIn("APPROVED", html)
        self.assertIn("৳", memo.render(sb, p["id"], "bn"))


class Extras(unittest.TestCase):
    def test_kit_and_event_are_thresholds_with_assumed_inputs(self):
        k = extras.brain_games_kit(school())
        self.assertEqual((k["order_qty"], k["unit_price"], k["venture_cost"], k["break_even_units"]), (85, 360, 25200, 46))
        self.assertEqual(k["base"]["roi_pct"], 52.8)
        self.assertEqual(k["prebooking_rule"]["prebookings_needed_before_ordering"], 35)
        self.assertEqual(k["demand_estimate"]["status"], "ASSUMED")
        e = extras.engagement_event(school())
        self.assertEqual((e["total_cost"], e["school_subsidy"], e["break_even_contribution_per_student"]), (27750, 13750, 199))
        self.assertEqual(e["students_to_cover_subsidy_whole"], 1)


class RedTeam(unittest.TestCase):
    def test_all_attacks_pass_and_v1_misses_most(self):
        result = redteam.run(sandbox())
        failed = [r["id"] for r in result["results"] if r["verdict"] != "PASS"]
        self.assertEqual(failed, [])
        self.assertEqual(result["total"], 23)
        self.assertGreaterEqual(len(result["v1_comparison"]["v1_missed"]), 10)
        self.assertTrue(result["audit_chain"]["ok"])

    def test_red_team_does_not_touch_the_real_sandbox(self):
        sb = sandbox()
        before = sb.audit.count()
        redteam.run(sb)
        self.assertEqual(sb.audit.count(), before)
        self.assertEqual(sb.proposals(), [])


if __name__ == "__main__":
    unittest.main()
