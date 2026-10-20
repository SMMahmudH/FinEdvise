"""The single data file must add up. Expected figures are worked out in the comments."""
import copy
import unittest
from collections import defaultdict
from datetime import date

from finedvise.data import (billable_tuition, month_to_date, monthly_ledger, opening_cash, outstanding_tuition,
                         validate_school)
from finedvise.engine import build_weeks, week_of

from tests.helpers import school


class LedgerReconciles(unittest.TestCase):
    def test_every_month_closes_into_the_next(self):
        rows = monthly_ledger(school())
        for prev, cur in zip(rows, rows[1:]):
            self.assertEqual(prev["closing_cash"], cur["opening_cash"], cur["month"])
        for r in rows:
            self.assertEqual(r["opening_cash"] + r["total_inflow"] - r["total_outflow"], r["closing_cash"], r["month"])

    def test_october_close_and_dues(self):
        # 55,000 opening in January; October closes at 220,000 with 38,400 of tuition unpaid
        last = monthly_ledger(school())[-1]
        self.assertEqual(last["closing_cash"], 220000)
        self.assertEqual(last["outstanding_tuition"], 38400)

    def test_month_to_date_bridges_october_close_to_c0(self):
        d = school()
        mtd = month_to_date(d)
        # 1-14 Nov: 200,000 in, 200,000 out
        self.assertEqual((mtd["receipts"], mtd["payments"]), (200000, 200000))
        self.assertEqual(monthly_ledger(d)[-1]["closing_cash"] + mtd["net"], opening_cash(d).value)


class OneDefinitionEach(unittest.TestCase):
    def test_c0_is_cash_bank_and_settled_bkash(self):
        # 22,000 + 185,000 + 13,000; the 4,000 still settling is not counted
        m = opening_cash(school())
        self.assertEqual(m.value, 220000)
        self.assertEqual(m.inputs["bkash_pending_not_counted"], 4000)

    def test_billable_tuition_explains_the_ledger(self):
        # 150 x 1,200 - 16 scholarship students x 500 = 172,000, the amount billed every month
        d = school()
        self.assertEqual(billable_tuition(d).value, 172000)
        for m in d["monthly_actuals_2026"]["months"]:
            self.assertEqual(m["tuition_billed"], 172000)

    def test_dues_on_scenario_date(self):
        # 38,400 + 172,000 November bill - (142,000 received + 4,000 paid by bKash, settling) = 64,400
        self.assertEqual(outstanding_tuition(school()).value, 64400)

    def test_roster_reconciles_after_the_register(self):
        d = school()
        before = sum(s["dues_before_register"] for s in d["roster"]["students"])
        self.assertEqual(before, 74600)  # 64,400 + 10,200 of payments in the 1-14 Nov register


class ForecastShape(unittest.TestCase):
    def test_weekly_totals(self):
        weeks, _, _ = build_weeks(school())
        got = [(w.receipts, w.payments, w.committed) for w in weeks]
        self.assertEqual(got, [
            (25000, 18000, 5000), (15000, 35000, 10000), (45000, 110000, 0), (35000, 15000, 5000),
            (60000, 12000, 0), (80000, 25000, 0), (70000, 15000, 0), (90000, 122000, 0)])

    def test_weeks_are_contiguous_and_named(self):
        weeks, _, _ = build_weeks(school())
        self.assertEqual([w.label for w in weeks], ["Nov W3", "Nov W4", "Dec W1", "Dec W2", "Dec W3", "Dec W4", "Dec W5", "Jan W1"])
        for a, b in zip(weeks, weeks[1:]):
            self.assertEqual((b.start - a.end).days, 1)

    def test_salary_week_holds_only_payroll_and_rent(self):
        d = school()
        cats = defaultdict(float)
        for line in d["forecast"]["lines"]:
            if line["type"] == "payment" and week_of(d, date.fromisoformat(line["date"])) == 3:
                cats[line["category"]] += line["amount"]
        self.assertEqual(dict(cats), {"payroll": 85000, "rent": 25000})

    def test_validation_catches_mistakes(self):
        d = copy.deepcopy(school())
        d["forecast"]["lines"][0]["amount"] = -5
        d["forecast"]["lines"][1]["category"] = "magic"
        d["forecast"]["lines"][2]["date"] = "2027-03-01"
        problems = " ".join(validate_school(d))
        self.assertIn("non-negative", problems)
        self.assertIn("unknown receipt category", problems)
        self.assertIn("outside forecast window", problems)

    def test_clean_file_has_no_problems(self):
        self.assertEqual(validate_school(school()), [])


if __name__ == "__main__":
    unittest.main()
