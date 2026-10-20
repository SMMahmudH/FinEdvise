"""Tests for fresh school workspaces and privacy-preserving topical web research."""
from datetime import date
import unittest

from finedvise.data import validate_school
from finedvise.research import query_for_message
from finedvise.workspace_data import blank_workspace_data


class WorkspaceDataTests(unittest.TestCase):
    def test_blank_workspace_isolated_and_schema_valid(self):
        data = blank_workspace_data("Riverbend School", today=date(2030, 1, 2))
        self.assertEqual(data["meta"]["dataset_label"], "EMPTY_WORKSPACE")
        self.assertEqual(data["meta"]["school_name_en"], "Riverbend School")
        self.assertEqual(data["meta"]["scenario_date"], "2030-01-02")
        self.assertEqual(data["opening_position"]["cash_in_hand"], 0)
        self.assertEqual(data["opening_position"]["bank"], 0)
        self.assertEqual(data["profile"]["active_students"], 0)
        self.assertEqual(data["roster"]["students"], [])
        self.assertEqual(data["forecast"]["lines"], [])
        self.assertEqual(data["plans"], [])
        self.assertEqual(validate_school(data), [])

    def test_google_queries_are_category_only_and_never_send_raw_message(self):
        message = "Plan a school picnic for Golapgonj Ideal Public School for Tk 45000"
        query = query_for_message(message)
        self.assertIsNotNone(query)
        self.assertIn("school picnic", query.lower())
        self.assertNotIn("Golapgonj", query)
        self.assertNotIn("45000", query)

    def test_current_time_is_local_and_not_searched(self):
        for message in ("What time is it in Bangladesh?", "What is today's date?", "আজ কত তারিখ?"):
            with self.subTest(message=message):
                self.assertIsNone(query_for_message(message))

    def test_general_school_finance_topics_can_use_generic_search(self):
        cases = {
            "How can our school reduce electricity costs?": "budgeting costs",
            "What should we consider for tuition fee collection?": "budgeting costs",
            "How to maintain school inventory?": "budgeting costs",
        }
        for message, expected_fragment in cases.items():
            with self.subTest(message=message):
                query = query_for_message(message)
                self.assertIsNotNone(query)
                self.assertIn(expected_fragment, query.lower())
                self.assertNotIn(message, query)

    def test_private_or_sensitive_prompts_are_not_searched(self):
        for message in (
            "List guardian phone numbers for student ST-001",
            "Send 50000 to the supplier now",
            "My email is principal@example.com",
        ):
            with self.subTest(message=message):
                self.assertIsNone(query_for_message(message))


if __name__ == "__main__":
    unittest.main()
