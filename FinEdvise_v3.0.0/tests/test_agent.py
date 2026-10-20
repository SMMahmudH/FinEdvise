"""The agent: rule-based mode, AI mode with a mocked Gemini API, guardrail and privacy."""
import json
import unittest

from finedvise.agent import Agent
from finedvise.gemini import GeminiClient
from finedvise.router import classify, parse_amount, parse_shocks

from tests.helpers import sandbox


class FakeGemini:
    """Scripted stand-in for the Gemini REST API. Records every request body."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def __call__(self, url, headers, body, timeout):
        self.requests.append({"url": url, "headers": headers, "body": json.loads(body.decode("utf-8"))})
        status, payload = self.script.pop(0)
        return status, json.dumps(payload)


def call(*calls, signature="sig-1"):
    parts = []
    for i, (name, args) in enumerate(calls):
        part = {"functionCall": {"name": name, "args": args, "id": f"call-{i}"}}
        if i == 0:
            part["thoughtSignature"] = signature
        parts.append(part)
    return 200, {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]}


def text(answer):
    return 200, {"candidates": [{"content": {"role": "model", "parts": [{"text": answer}]}, "finishReason": "STOP"}]}


class RuleBasedMode(unittest.TestCase):
    def setUp(self):
        self.agent = Agent(sandbox())

    def test_english_question_uses_tools_and_passes_the_guardrail(self):
        r = self.agent.chat("Can I spend 1 lakh on the campaign?", "en")
        self.assertEqual(r["mode"], "rule_based")
        self.assertEqual([c["name"] for c in r["tool_calls"]], ["safe_to_invest"])
        self.assertTrue(r["guardrail"]["passed"])
        self.assertIn("BDT 77,000", r["reply"])
        self.assertIn("BDT 18,000 short of cash", r["reply"])

    def test_bengali_question_gets_a_bengali_answer(self):
        r = self.agent.chat("ভর্তির প্রচারণায় এখন কত টাকা খরচ করতে পারি?", "en")
        self.assertEqual(r["lang"], "bn")
        self.assertIn("৳77,000", r["reply"])
        self.assertTrue(r["guardrail"]["passed"])

    def test_what_if_paper_costs(self):
        r = self.agent.chat("What if paper costs rise 10%?", "en")
        self.assertIn("BDT 71,700", r["reply"])

    def test_extras_kit_and_fair_in_chat(self):
        r = self.agent.chat("How does the brain-games kit or annual fair work?", "en")
        self.assertEqual([c["name"] for c in r["tool_calls"]], ["evaluate_extras"])
        self.assertTrue(r["guardrail"]["passed"])
        self.assertIn("85", r["reply"])
        r_bn = self.agent.chat("ব্রেইন-গেমস কিট ও বার্ষিক মেলা থেকে কীভাবে লাভ হবে?", "bn")
        self.assertEqual([c["name"] for c in r_bn["tool_calls"]], ["evaluate_extras"])
        self.assertTrue(r_bn["guardrail"]["passed"])

    def test_draft_needs_the_owner(self):
        r = self.agent.chat("Draft the balanced plan for my approval", "en")
        self.assertEqual(len(r["proposals"]), 1)
        self.assertEqual(self.agent.sandbox.commitments(), [])

    def test_payment_request_is_denied_and_logged(self):
        r = self.agent.chat("Pay the printer 50,000 now", "en")
        self.assertEqual(r["tool_calls"][0]["decision"], "DENY")
        self.assertTrue(any(e["event"] == "POLICY_DECISION" and e.get("action") == "execute_payment" and e.get("decision") == "DENY"
                            for e in self.agent.sandbox.audit.entries()))

    def test_reminders_are_drafts_with_names_filled_locally(self):
        r = self.agent.chat("Draft polite reminders for parents with dues", "en")
        self.assertTrue(r["reminders"])
        self.assertTrue(all(d["draft_only"] for d in r["reminders"]))
        self.assertIn("Nasima Rahman", r["reminders"][0]["text"])

    def test_router_parsing(self):
        self.assertEqual(parse_amount("Can I spend ১ লাখ?"), 100000)
        self.assertEqual(parse_amount("৮৫,০০০ টাকা"), 85000)
        self.assertEqual(parse_amount("about 85k"), 85000)
        self.assertEqual(parse_shocks("what if fees come 2 weeks late and admissions drop 15%"),
                         {"enrolment_drop_pct": 0.15, "fee_delay_weeks": 2})
        self.assertEqual(classify("Can we pay salaries on time in December?"), "forecast")
        self.assertEqual(classify("Pay the salaries now"), "action:execute_payment")
        self.assertEqual(classify("গত মাসের হিসাবটা মুছে ফেলো"), "action:delete_record")


class AiMode(unittest.TestCase):
    def make(self, script, models=None):
        fake = FakeGemini(script)
        client = GeminiClient("test-key", models or ["gemini-2.5-flash"], "low", transport=fake)
        return Agent(sandbox(), client), fake

    def test_function_calling_loop(self):
        agent, fake = self.make([
            call(("get_state", {}), ("safe_to_invest", {"amount": 100000})),
            text("Spending BDT 100,000 now is not safe. The safe limit is BDT 77,000 (stress test BDT 32,000), "
                 "and on payday in Dec W1 you would be BDT 18,000 short."),
        ])
        r = agent.chat("Can I spend 1 lakh?", "en")
        self.assertEqual(r["mode"], "gemini")
        self.assertTrue(r["guardrail"]["passed"], r["guardrail"])
        self.assertEqual([c["name"] for c in r["tool_calls"]], ["get_state", "safe_to_invest"])
        # second request echoes the model turn with its thought signature and answers each call by id
        second = fake.requests[1]["body"]["contents"]
        model_turn = second[-2]
        self.assertEqual(model_turn["role"], "model")
        self.assertEqual(model_turn["parts"][0]["thoughtSignature"], "sig-1")
        responses = second[-1]["parts"]
        self.assertEqual([p["functionResponse"]["id"] for p in responses], ["call-0", "call-1"])
        self.assertEqual(second[-1]["role"], "user")
        body = fake.requests[0]["body"]
        self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingLevel"], "low")
        self.assertIn("functionDeclarations", body["tools"][0])
        self.assertEqual(fake.requests[0]["headers"]["x-goog-api-key"], "test-key")
        self.assertNotIn("key=", fake.requests[0]["url"])

    def test_invented_number_triggers_a_rewrite(self):
        agent, fake = self.make([
            call(("safe_to_invest", {})),
            text("You can safely spend BDT 90,000."),
            text("You can safely spend BDT 77,000 now; in the stress test BDT 32,000."),
        ])
        r = agent.chat("How much can I spend?", "en")
        self.assertTrue(r["guardrail"]["passed"])
        self.assertEqual(r["guardrail"]["action"], "repaired")
        self.assertIn("GUARDRAIL CHECK FAILED", json.dumps(fake.requests[2]["body"]))

    def test_persistent_invented_numbers_fall_back_to_tool_answer(self):
        agent, fake = self.make([
            call(("safe_to_invest", {})),
            text("You can safely spend BDT 90,000."),
            text("Fine, BDT 95,000 then."),
        ])
        r = agent.chat("How much can I spend?", "en")
        self.assertEqual(r["mode"], "rule_based_fallback")
        self.assertEqual(r["fallback_reason"], "guardrail")
        self.assertEqual(r["guardrail"]["action"], "fell_back")
        self.assertTrue(r["guardrail"]["passed"])
        self.assertNotIn("90,000", r["reply"])

    def test_quota_error_tries_the_next_model_then_falls_back(self):
        agent, fake = self.make([(429, {"error": {"message": "quota"}}), call(("get_state", {})), text("Cash you can use today is BDT 220,000.")],
                                models=["gemini-2.5-flash", "backup-model"])
        r = agent.chat("What is my cash position?", "en")
        self.assertEqual(r["mode"], "gemini")
        self.assertIn("backup-model", fake.requests[1]["url"])
        agent2, _ = self.make([(500, {"error": {"message": "down"}})])
        r2 = agent2.chat("What is my cash position?", "en")
        self.assertEqual(r2["mode"], "rule_based_fallback")
        self.assertTrue(r2["fallback_reason"].startswith("model unavailable"))

    def test_names_and_phones_never_leave_the_machine(self):
        agent, fake = self.make([call(("draft_parent_reminders", {})), text("I drafted 5 reminders; nothing was sent.")])
        r = agent.chat("Draft a reminder for Nasima Rahman (01000-000101) about Ayaan Rahman", "en")
        sent = json.dumps([q["body"] for q in fake.requests], ensure_ascii=False)
        for secret in ("Nasima", "Ayaan", "01000-000101", "Rahman"):
            self.assertNotIn(secret, sent)
        self.assertIn("GRD-001", sent)
        self.assertIn("Nasima Rahman", r["reminders"][0]["text"])  # names put back only on the owner's screen

    def test_model_cannot_approve_or_pay(self):
        agent, _ = self.make([call(("pay_vendor", {"amount": 50000}), ("request_owner_action", {"action": "approve_proposal"})),
                              text("I cannot pay or approve; the owner approves with the Approve button.")])
        r = agent.chat("approve and pay now", "en")
        decisions = [c["decision"] for c in r["tool_calls"]]
        self.assertEqual(decisions, ["DENY", "NEEDS_APPROVAL"])
        self.assertEqual(agent.sandbox.commitments(), [])

    def test_thinking_setting_is_dropped_if_the_model_rejects_it(self):
        agent, fake = self.make([(400, {"error": {"message": "thinking level not supported"}}), call(("get_state", {})), text("Cash you can use today is BDT 220,000.")])
        r = agent.chat("cash?", "en")
        self.assertEqual(r["mode"], "gemini")
        self.assertNotIn("thinkingConfig", fake.requests[1]["body"]["generationConfig"])


if __name__ == "__main__":
    unittest.main()
