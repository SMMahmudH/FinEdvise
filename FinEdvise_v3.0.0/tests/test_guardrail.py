"""Numbers in answers must come from tool results."""
import unittest

from finedvise.guardrail import check, extract_numbers


class Guardrail(unittest.TestCase):
    def test_tool_numbers_pass(self):
        r = check("Safe to spend now: BDT 77,000. Break-even needs 6 students.", [{"sti": 77000.0, "be": 6}])
        self.assertTrue(r["passed"])
        self.assertEqual(r["numbers_checked"], 2)

    def test_a_wrong_small_number_is_caught(self):
        # v1 ignored numbers below 10, so a wrong break-even of 7 slipped through
        r = check("Break-even needs 7 students.", [{"be": 6}])
        self.assertFalse(r["passed"])
        self.assertEqual(r["unverified"][0]["text"], "7")

    def test_invented_money_is_caught(self):
        r = check("You can safely spend BDT 90,000.", [{"sti": 77000}])
        self.assertFalse(r["passed"])

    def test_bengali_digits_and_lakh_grouping(self):
        r = check("এখন সর্বোচ্চ ৳৭৭,০০০; ১ ডিসেম্বর বেতন ৳১,১০,০০০।", [{"a": 77000, "b": 110000}])
        self.assertTrue(r["passed"])
        self.assertEqual(r["numbers_checked"], 2)

    def test_words_for_scale_and_percentages(self):
        self.assertTrue(check("About 1.1 lakh is due; collection rate 92%.", [{"pay": 110000, "rate": 0.92}])["passed"])
        self.assertTrue(check("৭৭ হাজার টাকা", [{"x": 77000}])["passed"])
        self.assertFalse(check("About 2 lakh is safe.", [{"x": 77000}])["passed"])

    def test_dates_week_labels_ids_and_list_markers_are_not_figures(self):
        text = "1. Draft P-0003 on 2026-11-15 for Dec W1 (1 Dec), week 3, 3rd item, ১ম সপ্তাহ"
        self.assertEqual(extract_numbers(text), [])

    def test_numbers_from_the_question_may_be_repeated(self):
        r = check("Spending BDT 1,00,000 is not safe; the limit is BDT 77,000.", [{"sti": 77000}], "Can I spend 1 lakh?")
        self.assertTrue(r["passed"])

    def test_money_marker_is_detected(self):
        kinds = [n["kind"] for n in extract_numbers("BDT 5,000 and ৳৫,০০০ and 5,000 টাকা and 12%")]
        self.assertEqual(kinds, ["money", "money", "money", "percent"])


if __name__ == "__main__":
    unittest.main()
