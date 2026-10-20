"""Cost of credit, eligibility and the weakest-week test."""
import unittest

from finedvise.financing import cost_of_credit, eligibility, loan_checklist, match_financing, next_question

from tests.helpers import catalogue, school

FLAT_14_12_WEEKS = {"id": "X", "rate_pct": 14, "rate_basis": "flat", "tenor_weeks": 12, "repayment": "weekly", "upfront_fee_pct": 0}


class CostOfCredit(unittest.TestCase):
    def test_reproduces_the_mentors_flat_rate_example(self):
        # "14%, 12 weeks" as a flat rate is about 26% a year, about 38% with a 1.5% up-front fee
        self.assertAlmostEqual(cost_of_credit(FLAT_14_12_WEEKS, 23000)["apr_pct"], 25.7, delta=0.3)
        self.assertAlmostEqual(cost_of_credit({**FLAT_14_12_WEEKS, "upfront_fee_pct": 0.015}, 23000)["apr_pct"], 38.0, delta=0.5)

    def test_reproduces_the_published_flat_15_percent_example(self):
        # bdnews24 (13 Oct 2026): a loan advertised at a flat 15% costs about 27% effectively
        opt = next(o for o in catalogue()["options"] if o["id"] == "NGO_FLAT_RATE")
        self.assertAlmostEqual(cost_of_credit(opt, 50000)["apr_pct"], 27.0, delta=0.6)

    def test_declining_balance_rate_equals_its_apr(self):
        opt = next(o for o in catalogue()["options"] if o["id"] == "NGO_MFI_ENTERPRISE")
        c = cost_of_credit(opt, 100000)
        self.assertAlmostEqual(c["apr_pct"], 24.0, delta=0.1)
        self.assertGreater(c["ear_pct"], c["apr_pct"])

    def test_supplier_credit_cost_is_the_lost_discount(self):
        opt = next(o for o in catalogue()["options"] if o["id"] == "SUPPLIER_CREDIT_PRESS")
        c = cost_of_credit(opt, 20000)
        self.assertEqual(c["total_cost"], 200)
        self.assertAlmostEqual(c["apr_pct"], 12.3, delta=0.2)  # 1/99 per 30 days x 365/30

    def test_same_method_for_every_option(self):
        for opt in catalogue()["options"]:
            c = cost_of_credit(opt, 60000)
            self.assertIn("apr_pct", c)
            self.assertGreaterEqual(c["total_repaid"] + c["upfront_fee"], 60000 - 1e-6 if opt["rate_basis"] != "lost_discount" else 0)


class Catalogue(unittest.TestCase):
    def test_every_option_has_a_source_or_is_labelled(self):
        for opt in catalogue()["options"]:
            with self.subTest(opt["id"]):
                if opt["rate_badge"] == "VERIFIED":
                    self.assertTrue(opt["rate_sources"])
                    for src in opt["rate_sources"]:
                        self.assertTrue(src["url"].startswith("https://"))
                        self.assertEqual(src["checked_on"], "2026-10-20")
                else:
                    self.assertIn(opt["rate_badge"], ("ILLUSTRATIVE", "ASSUMED"))
                self.assertIn(opt["terms_badge"], ("ILLUSTRATIVE", "ASSUMED", "VERIFIED"))


class Matching(unittest.TestCase):
    def test_balanced_needs_no_loan_after_rescheduling(self):
        m = match_financing(school(), catalogue(), {}, plan_id="PLAN_BALANCED")
        self.assertEqual(m["gap_if_paid_now"], 45000)
        self.assertEqual(m["gap_after_fixes"], 0)
        self.assertFalse(m["borrowing_needed"])
        self.assertEqual(m["staging_cost"], 200)
        self.assertEqual(m["credit_options"], [])

    def test_aggressive_still_needs_money_and_asks_one_question(self):
        m = match_financing(school(), catalogue(), {}, plan_id="PLAN_AGGRESSIVE")
        self.assertEqual(m["gap_after_fixes"], 10645)  # January payroll week, stress test
        self.assertTrue(m["borrowing_needed"])
        self.assertEqual(m["next_question"]["id"], "has_trade_licence")

    def test_cheap_refinance_loan_arrives_too_late(self):
        m = match_financing(school(), catalogue(), {}, plan_id="PLAN_AGGRESSIVE")
        refi = next(o for o in m["credit_options"] if o["id"] == "BANK_CMSME_REFINANCE")
        self.assertFalse(refi["arrives_in_time"])
        self.assertFalse(refi["passes_weakest_week_test"])
        self.assertEqual(refi["fail_reason"], "arrives_too_late")

    def test_eligibility_answers_change_the_ranking(self):
        profile = {"has_trade_licence": True, "has_tin": True, "bank_statement_months": 12,
                   "can_offer_collateral": False, "has_guarantor": True, "owner_can_lend": False}
        m = match_financing(school(), catalogue(), profile, plan_id="PLAN_AGGRESSIVE")
        status = {o["id"]: o["eligibility"]["status"] for o in m["credit_options"]}
        self.assertEqual(status["BANK_SME_MARKET"], "not_eligible")
        self.assertEqual(status["NGO_FLAT_RATE"], "eligible")
        self.assertEqual(status["OWNER_BRIDGE"], "not_eligible")
        self.assertIsNone(m["next_question"])

    def test_eligibility_rules(self):
        opt = {"requires": {"has_tin": True, "bank_statement_months": 6}}
        self.assertEqual(eligibility(opt, {})["status"], "unknown")
        self.assertEqual(eligibility(opt, {"has_tin": True, "bank_statement_months": 3})["status"], "not_eligible")
        self.assertEqual(eligibility(opt, {"has_tin": True, "bank_statement_months": 9})["status"], "eligible")

    def test_one_question_at_a_time_in_priority_order(self):
        cat = catalogue()
        opts = [o for o in cat["options"] if o["kind"] != "supplier_credit"]
        self.assertEqual(next_question(cat, {}, opts)["id"], "has_trade_licence")
        self.assertEqual(next_question(cat, {"has_trade_licence": True}, opts)["id"], "has_tin")

    def test_checklist_is_a_checklist_only(self):
        c = loan_checklist(catalogue(), "BANK_CMSME_REFINANCE", {})
        self.assertTrue(c["draft_only"])
        self.assertIn("Current trade licence", c["documents_en"])
        with self.assertRaises(ValueError):
            loan_checklist(catalogue(), "NOPE", {})


if __name__ == "__main__":
    unittest.main()
