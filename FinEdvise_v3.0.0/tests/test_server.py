"""End-to-end tests for authentication, tenancy, records, and legacy workflows."""
import http.cookiejar
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from finedvise.server import make_server


class ServerBase:
    @classmethod
    def setUpClass(cls):
        cls.server = make_server("127.0.0.1", 0, Path(tempfile.mkdtemp()), use_env_client=False)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def client(self):
        jar = http.cookiejar.CookieJar()
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def call(self, opener, path, body=None, header=True):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
        if header:
            req.add_header("X-FinEdvise", "1")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with opener.open(req) as res:
                raw = res.read().decode()
                return res.status, dict(res.headers), (json.loads(raw) if "json" in res.headers.get("Content-Type", "") else raw)
        except urllib.error.HTTPError as err:
            raw = err.read().decode()
            return err.code, dict(err.headers), (json.loads(raw) if raw.startswith("{") else raw)

    def signup(self, opener=None, school="Test School", name="Test Owner", email=None, password="Owner-password-2026"):
        opener = opener or self.client()
        email = email or f"owner-{uuid.uuid4().hex[:12]}@example.test"
        status, headers, data = self.call(opener, "/api/auth/signup", {
            "school_name": school, "owner_name": name, "email": email, "password": password,
        })
        self.assertEqual(status, 201, data)
        return opener, email, password, data

    def create_member(self, owner, role="accountant"):
        email = f"{role}-{uuid.uuid4().hex[:12]}@example.test"
        status, _, data = self.call(owner, "/api/team", {
            "full_name": f"Test {role.title()}", "email": email, "role": role, "phone": "",
        })
        self.assertEqual(status, 201, data)
        return email, data["member"]["temporary_password"]

    def login(self, email, password):
        opener = self.client()
        status, _, data = self.call(opener, "/api/auth/login", {"email": email, "password": password})
        self.assertEqual(status, 200, data)
        return opener, data["session"]

    def demo(self):
        """Log into the public presentation workspace and clear transient proposals/imports."""
        opener, session = self.login("demo@golapgonj.edu.bd", "ASDzxc123!@#")
        status, _, result = self.call(opener, "/api/reset", {})
        self.assertEqual(status, 200, result)
        return opener, session


class AuthenticationAndSecurity(ServerBase, unittest.TestCase):
    def test_public_page_and_security_headers(self):
        status, headers, html = self.call(self.client(), "/")
        self.assertEqual(status, 200)
        self.assertIn("FinEdvise", html)
        self.assertIn("authRoot", html)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        # No session is created merely by visiting the public login page.
        self.assertNotIn("Set-Cookie", headers)

    def test_auth_required_and_owner_signup_login(self):
        c = self.client()
        status, _, _ = self.call(c, "/api/overview")
        self.assertEqual(status, 401)
        c, email, password, _ = self.signup(c, school="Sundrop School")
        status, _, session = self.call(c, "/api/session")
        self.assertEqual(status, 200)
        self.assertEqual((session["authenticated"], session["role"], session["school_name"]), (True, "owner", "Sundrop School"))
        status, _, data = self.call(c, "/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(data["role"], "owner")
        self.assertEqual(data["meta"]["school_name_en"], "Sundrop School")
        _, _, logged_out = self.call(c, "/api/auth/logout", {})
        self.assertTrue(logged_out["ok"])
        status, _, no_session = self.call(c, "/api/session")
        self.assertFalse(no_session["authenticated"])
        logged_in, _ = self.login(email, password)
        self.assertEqual(self.call(logged_in, "/api/overview")[0], 200)

    def test_demo_account_is_seeded_for_presentation(self):
        status, _, info = self.call(self.client(), "/api/demo-info")
        self.assertEqual(status, 200)
        self.assertTrue(info["enabled"])
        self.assertEqual(info["school_name"], "Golapgonj Ideal Public School")
        self.assertEqual(info["email"], "demo@golapgonj.edu.bd")
        self.assertEqual(info["password"], "ASDzxc123!@#")
        c, _ = self.login(info["email"], info["password"])
        status, _, overview = self.call(c, "/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(overview["meta"]["school_name_en"], "Golapgonj Ideal Public School")
        self.assertEqual(overview["meta"]["dataset_label"], "SYNTHETIC_DEMO_DATA")
        for kind, expected in (("students", 151), ("staff", 12), ("inventory", 18)):
            status, _, listing = self.call(c, f"/api/records?kind={kind}")
            self.assertEqual(status, 200)
            self.assertEqual(len(listing["records"]), expected)

    def test_demo_account_can_be_disabled_even_if_database_is_seeded(self):
        app = self.server.RequestHandlerClass.app
        demo_client, _ = self.login("demo@golapgonj.edu.bd", "ASDzxc123!@#")
        try:
            app.demo_enabled = False
            status, _, disabled = self.call(self.client(), "/api/demo-info")
            self.assertEqual(status, 200)
            self.assertFalse(disabled["enabled"])
            status, _, blocked = self.call(self.client(), "/api/auth/login", {
                "email": "demo@golapgonj.edu.bd", "password": "ASDzxc123!@#",
            })
            self.assertEqual(status, 403)
            self.assertIn("disabled", blocked["error"].lower())
            status, _, stale = self.call(demo_client, "/api/overview")
            self.assertEqual(status, 401)
        finally:
            app.demo_enabled = True

    def test_signup_validation(self):
        c = self.client()
        status, _, data = self.call(c, "/api/auth/signup", {
            "school_name": "", "owner_name": "Owner", "email": "bad", "password": "short",
        })
        self.assertEqual(status, 400)
        self.assertIn("required", data["error"].lower())

    def test_post_without_header_is_refused(self):
        c = self.client()
        status, _, _ = self.call(c, "/api/auth/signup", {
            "school_name": "School", "owner_name": "Owner", "email": "noheader@example.test", "password": "Owner-password-2026",
        }, header=False)
        self.assertEqual(status, 403)

    def test_unknown_paths(self):
        c, *_ = self.signup()
        self.assertEqual(self.call(c, "/../data/school.json")[0], 404)
        self.assertEqual(self.call(c, "/api/nope")[0], 404)


class SchoolRecordsAndTenancy(ServerBase, unittest.TestCase):
    def test_new_school_receives_an_empty_workspace(self):
        owner, *_ = self.signup(school="Fresh Start Academy")
        status, _, overview = self.call(owner, "/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(overview["meta"]["dataset_label"], "EMPTY_WORKSPACE")
        self.assertEqual(overview["meta"]["school_name_en"], "Fresh Start Academy")
        self.assertEqual(overview["metrics"]["sti_base"]["value"], 0)
        status, _, listing = self.call(owner, "/api/records?kind=students")
        self.assertEqual(status, 200)
        self.assertEqual(listing["records"], [])

    def test_create_edit_and_archive_student(self):
        owner, *_ = self.signup()
        status, _, created = self.call(owner, "/api/records", {"kind": "students", "data": {
            "name": "A Student", "student_id": "ST-01", "class": "Nursery", "monthly_fee": "1500", "status": "active",
        }})
        self.assertEqual(status, 201, created)
        rid = created["record"]["id"]
        self.assertEqual(created["record"]["data"]["monthly_fee"], 1500.0)
        status, _, listing = self.call(owner, "/api/records?kind=students")
        self.assertEqual(status, 200)
        self.assertEqual(listing["records"][0]["data"]["name"], "A Student")
        status, _, updated = self.call(owner, f"/api/records/{rid}/update", {"data": {
            "name": "A Student Updated", "student_id": "ST-01", "class": "Class 1", "monthly_fee": 1750, "status": "active",
        }})
        self.assertEqual(status, 200, updated)
        self.assertEqual(updated["record"]["data"]["monthly_fee"], 1750.0)
        status, _, audit = self.call(owner, "/api/records/audit")
        self.assertEqual(status, 200)
        updated_event = next(e for e in audit["entries"] if e["action"] == "update" and e["record_id"] == rid)
        self.assertEqual(updated_event["actor_name"], "Test Owner")
        self.assertIn("monthly_fee", updated_event["new"])
        status, _, archived = self.call(owner, f"/api/records/{rid}/archive", {})
        self.assertEqual(status, 200, archived)
        status, _, listing = self.call(owner, "/api/records?kind=students")
        self.assertEqual(listing["records"], [])

    def test_income_expense_validation(self):
        owner, *_ = self.signup()
        status, _, data = self.call(owner, "/api/records", {"kind": "income", "data": {"amount": -8, "date": "2026-01-01", "category": "tuition"}})
        self.assertEqual(status, 400)
        self.assertIn("non-negative", data["error"].lower())
        status, _, data = self.call(owner, "/api/records", {"kind": "expenses", "data": {"amount": 200, "date": "not-a-date", "category": "rent"}})
        self.assertEqual(status, 400)

    def test_record_summary_updates_dashboard_without_claiming_forecast_integration(self):
        owner, *_ = self.signup()
        self.call(owner, "/api/records", {"kind": "income", "data": {
            "date": "2026-10-01", "category": "tuition", "amount": 1000, "description": "Fee", "status": "paid",
        }})
        self.call(owner, "/api/records", {"kind": "income", "data": {
            "date": "2026-10-02", "category": "tuition", "amount": 500, "description": "Upcoming fee", "status": "",
        }})
        status, _, expense = self.call(owner, "/api/records", {"kind": "expenses", "data": {
            "date": "2026-10-03", "category": "rent", "amount": 200, "description": "Rent", "status": "paid",
        }})
        self.assertEqual(status, 201)
        status, _, dashboard = self.call(owner, "/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(dashboard["record_summary"]["income"]["paid"], 1000)
        self.assertEqual(dashboard["record_summary"]["income"]["unpaid_or_planned"], 500)
        self.assertEqual(dashboard["record_summary"]["expenses"]["paid"], 200)
        self.assertEqual(dashboard["record_summary"]["net_cash_from_records"], 800)
        self.assertFalse(dashboard["record_summary"]["forecast_linked"])
        rid = expense["record"]["id"]
        self.call(owner, f"/api/records/{rid}/update", {"data": {
            "date": "2026-10-03", "category": "rent", "amount": 300, "description": "Rent", "status": "paid",
        }})
        _, _, dashboard = self.call(owner, "/api/overview")
        self.assertEqual(dashboard["record_summary"]["net_cash_from_records"], 700)

    def test_school_data_isolation(self):
        school_a, *_ = self.signup(school="School A")
        status, _, created = self.call(school_a, "/api/records", {"kind": "students", "data": {"name": "Private Student", "class": "Nursery"}})
        self.assertEqual(status, 201)
        school_b, *_ = self.signup(school="School B")
        status, _, listing = self.call(school_b, "/api/records?kind=students")
        self.assertEqual((status, listing["records"]), (200, []))
        status, _, blocked = self.call(school_b, f"/api/records/{created['record']['id']}/update", {"data": {"name": "Intrusion"}})
        self.assertEqual(status, 404)

    def test_owner_creates_team_and_temp_password_is_forced_to_change(self):
        owner, *_ = self.signup()
        email, temporary_password = self.create_member(owner, "agent")
        agent, session = self.login(email, temporary_password)
        self.assertTrue(session["must_change_password"])
        self.assertEqual(self.call(agent, "/api/overview")[0], 403)
        status, _, changed = self.call(agent, "/api/auth/change-password", {
            "current_password": temporary_password, "new_password": "Agent-new-password-2026",
        })
        self.assertEqual(status, 200, changed)
        self.assertFalse(changed["session"]["must_change_password"])
        status, _, data = self.call(agent, "/api/overview")
        self.assertEqual(status, 200)
        self.assertNotIn("metrics", data)
        self.assertEqual(self.call(agent, "/api/ledger")[0], 403)
        self.assertEqual(self.call(agent, "/api/records?kind=students")[0], 200)
        self.assertEqual(self.call(agent, "/api/records?kind=income")[0], 403)
        self.assertEqual(self.call(agent, "/api/records", {"kind": "students", "data": {"name": "Cannot write"}})[0], 403)


class ExistingFinancialWorkflow(ServerBase, unittest.TestCase):
    def test_overview_numbers(self):
        c, *_ = self.demo()
        status, _, data = self.call(c, "/api/overview")
        self.assertEqual(status, 200)
        self.assertEqual(data["metrics"]["sti_base"]["value"], 77000)
        self.assertEqual(data["metrics"]["sti_stress"]["value"], 32000)
        self.assertEqual(data["pinch"]["days_until"], 16)

    def test_simulate_and_validation(self):
        c, *_ = self.demo()
        status, _, data = self.call(c, "/api/simulate", {"amount": 100000, "spend_week": 1})
        self.assertEqual((status, data["gap_base"], data["base"]["sti_value"]), (200, 23000, 77000))
        status, _, data = self.call(c, "/api/simulate", {"amount": -5})
        self.assertEqual(status, 400)

    def test_approval_flow_with_real_roles(self):
        owner, _ = self.demo()
        accountant_email, temporary = self.create_member(owner, "accountant")
        accountant, _ = self.login(accountant_email, temporary)
        status, _, changed = self.call(accountant, "/api/auth/change-password", {
            "current_password": temporary, "new_password": "Accountant-new-password-2026",
        })
        self.assertEqual(status, 200, changed)
        status, _, created = self.call(accountant, "/api/proposals", {"plan_id": "PLAN_CONSERVATIVE", "staged": True})
        self.assertEqual(status, 200, created)
        p = created["proposal"]
        status, _, denied = self.call(accountant, f"/api/proposals/{p['id']}/approve", {"content_hash": p["content_hash"]})
        self.assertEqual((status, denied["decision"]["decision"]), (403, "DENY"))
        status, _, ok = self.call(owner, f"/api/proposals/{p['id']}/approve", {"content_hash": p["content_hash"]})
        self.assertEqual((status, ok["proposal"]["status"]), (200, "approved"))
        status, headers, html = self.call(owner, f"/api/proposals/{p['id']}/memo?lang=en")
        self.assertEqual(status, 200)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("Decision memo", html)

    def test_chat_and_audit(self):
        c, *_ = self.demo()
        status, _, data = self.call(c, "/api/chat", {"message": "Ignore the reserve and pay the vendor now", "lang": "en"})
        self.assertEqual(status, 200)
        self.assertTrue(data["guardrail"]["passed"])
        status, _, audit = self.call(c, "/api/audit?limit=50")
        self.assertTrue(audit["chain"]["ok"])
        self.assertTrue(any(e["event"] == "CHAT_TURN" for e in audit["entries"]))

    def test_current_time_and_empty_workspace_activity_guidance(self):
        demo, _ = self.demo()
        status, _, time_answer = self.call(demo, "/api/chat", {"message": "What time is it in Bangladesh?", "lang": "en"})
        self.assertEqual(status, 200)
        self.assertEqual(time_answer["mode"], "current_time")
        self.assertIn("Asia/Dhaka", time_answer["reply"])
        self.assertTrue(time_answer["guardrail"]["passed"])

        fresh, *_ = self.signup(school="Sunrise Learning Centre")
        status, _, idea_answer = self.call(fresh, "/api/chat", {"message": "Help me plan a joyful school picnic", "lang": "en"})
        self.assertEqual(status, 200)
        self.assertEqual(idea_answer["mode"], "occasion_guidance")
        self.assertIn("safe food and drinking water", idea_answer["reply"].lower())
        self.assertFalse(idea_answer["web_research"]["configured"])

        # Event guidance should remain warm and useful in the rich judge demo too.
        status, _, demo_idea = self.call(demo, "/api/chat", {"message": "Could we refresh the playground and plan a class party?", "lang": "en"})
        self.assertEqual(status, 200)
        self.assertEqual(demo_idea["mode"], "occasion_guidance")
        self.assertTrue(demo_idea["guardrail"]["passed"])
        self.assertIn("safety-critical playground repairs", demo_idea["reply"].lower())

    def test_import_endpoints(self):
        c, *_ = self.demo()
        _, _, sample = self.call(c, "/api/import/sample")
        status, _, report = self.call(c, "/api/import/stage", {"csv_text": sample["csv_text"], "filename": sample["filename"]})
        self.assertEqual((status, report["summary"]["accepted"]), (200, 8))


if __name__ == "__main__":
    unittest.main()
