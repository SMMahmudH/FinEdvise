"""Safe-to-Invest, shocks, alerts and plans. Expected numbers are worked by hand.

Base forecast week-end cash C_t (C_0 = 220,000):
  W1 220,000 - 23,000 + 25,000 = 222,000      W2 222,000 - 45,000 + 15,000 = 192,000
  W3 192,000 - 110,000 + 45,000 = 127,000     W4 127,000 - 20,000 + 35,000 = 142,000
  W5 190,000   W6 245,000   W7 300,000   W8 268,000
Reserve 50,000, so the tightest week is Dec W1: 127,000 - 50,000 = 77,000.
"""
import copy
import unittest

from finedvise import engine
from finedvise.engine import BASE, DOWNSIDE, Shocks, build_weeks, cash_path, compare_plans, scenario_view, simulate

from tests.helpers import school


class SafeToInvest(unittest.TestCase):
    def test_base_is_77000_set_by_the_salary_week(self):
        v = scenario_view(school(), BASE)
        self.assertEqual(v["sti"]["value"], 77000)
        self.assertEqual(v["sti"]["binding_row"]["label"], "Dec W1")
        self.assertEqual(v["sti"]["binding_kind"], "reserve")
        self.assertEqual([r["closing"] for r in v["rows"]], [222000, 192000, 127000, 142000, 190000, 245000, 300000, 268000])

    def test_paper_and_operating_costs_plus_10_percent(self):
        # +10% on not-yet-fixed operating payments only: W1 18,000 and W2 35,000 -> +5,300 before Dec W1
        v = scenario_view(school(), Shocks(cost_increase_pct=0.10))
        self.assertEqual(v["sti"]["value"], 71700)

    def test_salaries_and_rent_are_not_shocked(self):
        weeks, _, _ = build_weeks(school(), Shocks(cost_increase_pct=0.10))
        self.assertEqual(weeks[2].payments, 110000)

    def test_fees_one_week_late_are_carried_not_dropped(self):
        v = scenario_view(school(), Shocks(fee_delay_weeks=1))
        self.assertEqual(v["sti"]["value"], 32000)  # Dec W1: 177,000 - 110,000 + 15,000 = 82,000; minus 50,000
        self.assertEqual(v["carried_total"], 90000)  # Jan W1's fees arrive after the window
        total_in = sum(w["receipts"] for w in v["weeks"]) + v["carried_total"]
        self.assertEqual(total_in, 25000 + 15000 + 45000 + 35000 + 60000 + 80000 + 70000 + 90000)

    def test_bkash_settlement_is_not_delayed_by_a_fee_shock(self):
        weeks, _, _ = build_weeks(school(), Shocks(fee_delay_weeks=1))
        self.assertEqual(weeks[0].receipts, 4000)

    def test_enrolment_drop_hits_only_enrolment_money(self):
        base, _, _ = build_weeks(school())
        low, _, _ = build_weeks(school(), Shocks(enrolment_drop_pct=0.15))
        self.assertEqual([w.receipts for w in base[:4]], [w.receipts for w in low[:4]])
        self.assertEqual(round(base[4].receipts - low[4].receipts, 2), round(0.15 * (54000 + 4100), 2))
        self.assertEqual(scenario_view(school(), Shocks(enrolment_drop_pct=0.15))["sti"]["value"], 77000)

    def test_standard_stress_test(self):
        v = scenario_view(school(), DOWNSIDE)
        self.assertEqual(v["sti"]["value"], 32000)
        self.assertEqual(v["carried_total"], 84585)

    def test_emergency_repair(self):
        self.assertEqual(scenario_view(school(), Shocks(emergency_cost=15000))["sti"]["value"], 62000)

    def test_later_spend_week_only_faces_later_weeks(self):
        v = scenario_view(school(), BASE, spend_week=4)
        self.assertEqual(v["sti"]["value"], 92000)  # min(142,000, 190,000, ...) - 50,000

    def test_spending_exactly_sti_keeps_every_week_ok(self):
        sim = simulate(school(), 77000)
        self.assertTrue(sim["safe_in_base"])
        self.assertTrue(all(r["status"] == "OK" for r in sim["base"]["rows"]))
        sim2 = simulate(school(), 77001)
        self.assertFalse(sim2["safe_in_base"])
        self.assertEqual(sim2["gap_base"], 1)


class ReserveBreachVersusCashShortfall(unittest.TestCase):
    def test_100k_now_runs_out_of_cash_on_payday(self):
        # Dec W1 low point: 192,000 - 110,000 - 100,000 = -18,000 (salaries before that week's fees)
        sim = simulate(school(), 100000)
        w = sim["base"]["rows"][2]
        self.assertEqual((w["status"], w["cash_shortfall"], w["reserve_gap"]), ("CASH_SHORTFALL", 18000, 23000))

    def test_reserve_breach_with_cash_still_positive(self):
        # 80,000 now: Dec W1 low point 82,000 - 80,000 = 2,000 (cash never negative),
        # week end 127,000 - 80,000 = 47,000 < 50,000 reserve
        sim = simulate(school(), 80000)
        w = sim["base"]["rows"][2]
        self.assertEqual((w["status"], w["low_point"], w["closing"], w["reserve_gap"]), ("RESERVE_BREACH", 2000, 47000, 3000))

    def test_alerts_are_generated_with_days_until_payday(self):
        sim = simulate(school(), 100000)
        a = next(x for x in sim["base"]["alerts"] if x["label"] == "Dec W1")
        self.assertEqual((a["type"], a["days_until"], a["due_date"]), ("CASH_SHORTFALL", 16, "2026-12-01"))
        self.assertIn("16 days", a["message_en"])

    def test_no_alerts_without_spending(self):
        sim = simulate(school(), 0)
        self.assertEqual(sim["base"]["alerts"], [])

    def test_next_pinch_message_from_the_engine(self):
        d = school()
        p = engine.next_pinch(d, scenario_view(d, BASE), scenario_view(d, DOWNSIDE))
        self.assertEqual((p["days_until"], p["payroll_and_rent"], p["sti_base"], p["sti_stress"]), (16, 110000, 77000, 32000))


class BreakEvenAndPlans(unittest.TestCase):
    def test_student_economics(self):
        e = engine.student_economics(school())
        # (18,900 - 400) x 0.92 x 0.95 - 1,100 - 500 = 14,569
        self.assertEqual(e["net_contribution"].value, 14569)
        # (2,500 + 2,000 + 1,200 - 400) x 0.92 - 1,100 = 3,776
        self.assertEqual(e["window_cash"].value, 3776)

    def test_break_even_versus_cash_payback(self):
        be = engine.break_even(school(), 100000, {"base": 12})
        self.assertEqual(be["economic_break_even"]["value"], 7)   # ceil(100,000 / 14,569)
        self.assertEqual(be["cash_payback"]["value"], 27)         # ceil(100,000 / 3,776)
        self.assertEqual(be["scenarios"]["base"]["economic_gain"], 74828)

    def test_plan_table_uses_the_data(self):
        cmp = compare_plans(school())
        by = {p["id"]: p["lump_sum"] for p in cmp["plans"]}
        self.assertEqual(by["PLAN_AGGRESSIVE"]["extra_students_estimate"]["base"], 12)
        self.assertEqual(by["PLAN_AGGRESSIVE"]["gains"]["base"], 74828)
        self.assertEqual(by["PLAN_BALANCED"]["gains"]["base"], 68690)

    def test_balanced_wins_because_aggressive_breaks_the_reserve(self):
        cmp = compare_plans(school())
        self.assertEqual(cmp["recommended_plan_id"], "PLAN_BALANCED")
        self.assertIn("breaks the reserve in Dec W1 by BDT 23,000", cmp["reason"]["en"])
        self.assertIn("not because it earns less", cmp["reason"]["en"])

    def test_staged_balanced_plan_survives_the_stress_test(self):
        cmp = compare_plans(school())
        bal = next(p for p in cmp["plans"] if p["id"] == "PLAN_BALANCED")
        self.assertFalse(bal["lump_sum"]["stress"]["ok"])
        self.assertTrue(bal["staged"]["stress"]["ok"])
        self.assertEqual(bal["staged"]["staging_cost"], 200)
        self.assertTrue(cmp["advice"]["use_staged"])


class Safety(unittest.TestCase):
    def test_shocks_never_change_the_data(self):
        d = school()
        before = copy.deepcopy(d)
        simulate(d, 100000, 1, Shocks(enrolment_drop_pct=0.5, fee_delay_weeks=2, cost_increase_pct=0.3, emergency_cost=9000))
        self.assertEqual(d, before)

    def test_bad_inputs_are_rejected(self):
        d = school()
        for kwargs in ({"amount": -1}, {"amount": float("nan")}, {"amount": True}, {"spend_week": 0}, {"spend_week": 9}):
            with self.subTest(kwargs), self.assertRaises(ValueError):
                simulate(d, **kwargs)
        for raw in ({"fee_delay_weeks": 9}, {"enrolment_drop_pct": 2}, {"unknown": 1}, {"fee_delay_weeks": 1.5}):
            with self.subTest(raw), self.assertRaises(ValueError):
                Shocks.from_dict(raw)

    def test_cash_path_payments_go_first(self):
        weeks, _, _ = build_weeks(school())
        rows = cash_path(220000, weeks, 50000)
        self.assertEqual(rows[2]["low_point"], 82000)  # 192,000 - 110,000


if __name__ == "__main__":
    unittest.main()
