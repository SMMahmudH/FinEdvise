"""HTTP server: JSON API plus the web interface. Standard library only.

Run:  python run.py            (http://127.0.0.1:8000)

Security notes
  * binds to 127.0.0.1 unless --host is given;
  * session cookie is HttpOnly, SameSite=Strict; POST requests must carry the
    X-FinEdvise header, which other sites cannot send without CORS (we send none);
  * strict Content-Security-Policy, nosniff, no-referrer, frame-ancestors none;
  * request bodies are limited to 1.5 MB; static files come from an allow-list;
  * the Gemini API key stays on the server and is never returned or logged.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from . import __version__, engine, extras, financing, fmt, memo, redteam
from .accounts import AccountError, AccountStore, DEMO_EMAIL, DEMO_PASSWORD, DEMO_SCHOOL_NAME
from .agent import Agent
from .data import (CATEGORY_LABELS, ROOT, billable_tuition, month_to_date, monthly_ledger, opening_cash,
                   outstanding_tuition, reserve_metric)
from .gemini import GeminiClient
from .policy import tier_table
from .provenance import BADGE_MEANING
from .research import google_search, query_for_message
from .store import PolicyDenied, Sandbox
from .workspace_data import blank_workspace_data
from .tools import ToolContext, open_questions, run_tool

WEB = ROOT / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
    "/charts.js": ("charts.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}
SAMPLE_CSV = ROOT / "data" / "samples" / "fee_register_messy.csv"
MAX_BODY = 1_500_000
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")
MEMO_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'self'; base-uri 'none'"


class App:
    def __init__(self, sandbox: Sandbox, client: Optional[GeminiClient],
                 auth_store: Optional[AccountStore] = None, base_var: Optional[Path] = None,
                 demo_enabled: bool = False) -> None:
        self.sb = sandbox
        self.client = client
        self.agent = Agent(sandbox, client)
        self.auth = auth_store
        self.base_var = Path(base_var or sandbox.var)
        self._workspaces: Dict[str, "App"] = {}
        self._workspace_lock = threading.RLock()
        self.school_id: Optional[str] = None
        self.demo_enabled = demo_enabled

    def for_session(self, session: Dict[str, Any]) -> "App":
        """Return an isolated financial sandbox for the authenticated school."""
        school_id = str(session.get("school_id") or "")
        if not school_id:
            raise AccountError("A school account is required.", 401)
        with self._workspace_lock:
            if school_id in self._workspaces:
                return self._workspaces[school_id]
            root = self.base_var / "schools" / school_id
            root.mkdir(parents=True, exist_ok=True)
            school_path = root / "school.json"
            if not school_path.exists():
                is_demo = self.demo_enabled and str(session.get("email", "")).lower() == DEMO_EMAIL.lower()
                if is_demo:
                    source = ROOT / "data" / "school.json"
                    data = json.loads(source.read_text(encoding="utf-8"))
                    data["meta"]["school_name_en"] = session.get("school_name") or DEMO_SCHOOL_NAME
                    data["meta"]["school_name_bn"] = session.get("school_name") or DEMO_SCHOOL_NAME
                    data["meta"]["dataset_label"] = "SYNTHETIC_DEMO_DATA"
                    data["meta"]["notice_en"] = "Judge-ready synthetic demo scenario. All people and transactions are fictional."
                    data["meta"]["notice_bn"] = "বিচারকদের প্রদর্শনের জন্য কৃত্রিম ডেমো। সব ব্যক্তি ও লেনদেন কাল্পনিক।"
                else:
                    data = blank_workspace_data(session.get("school_name") or "My School")
                school_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            sandbox = Sandbox(var_dir=root / "var", data_path=school_path)
            workspace = App(sandbox, self.client, self.auth, self.base_var, self.demo_enabled)
            workspace.school_id = school_id
            self._workspaces[school_id] = workspace
            return workspace

    # ------------------------------------------------------------- payloads
    def overview(self) -> Dict[str, Any]:
        sb = self.sb
        data = sb.data()
        commitments = sb.commitments()
        base = engine.scenario_view(data, engine.BASE, commitments)
        stress = engine.scenario_view(data, engine.DOWNSIDE, commitments)
        base0 = engine.scenario_view(data, engine.BASE, [])
        stress0 = engine.scenario_view(data, engine.DOWNSIDE, [])
        c0 = opening_cash(data).value
        reserve = engine.reserve_amount(data)
        hist = data["history"][0]
        qs = open_questions(sb, "en")
        return {
            "version": __version__,
            "server_now": datetime.now(ZoneInfo("Asia/Dhaka")).isoformat(timespec="seconds"),
            "timezone": "Asia/Dhaka",
            "meta": data["meta"],
            "agent": self.agent.info(),
            "position": data["opening_position"],
            "metrics": {
                "opening_cash": opening_cash(data).to_dict(),
                "outstanding": outstanding_tuition(data).to_dict(),
                "reserve": reserve_metric(data).to_dict(),
                "billable_tuition": billable_tuition(data).to_dict(),
                "sti_base": engine.sti_metric(c0, reserve, base["sti"], "base", engine.BASE, 1).to_dict(),
                "sti_stress": engine.sti_metric(c0, reserve, stress["sti"], "stress", engine.DOWNSIDE, 1).to_dict(),
            },
            "pinch": engine.next_pinch(data, base, stress),
            "alerts": engine.alerts(data, base, "base") + engine.alerts(data, stress, "stress"),
            "weeks": {
                "plan": {"base": base["rows"], "stress": stress["rows"]},
                "baseline": {"base": base0["rows"], "stress": stress0["rows"]},
            },
            "carried": {"plan_stress": stress["carried_total"]},
            "stress": {"shocks": engine.DOWNSIDE.to_dict(), "label": engine.DOWNSIDE_LABEL},
            "commitments_total": float(sum(l["amount"] for l in commitments)),
            "commitments": commitments,
            "pending_count": sum(1 for p in sb.proposals() if p["status"] == "pending"),
            "next_question": qs[0] if qs else None,
            "history": {**hist, "admissions_variance": hist["actual_extra_admissions"] - hist["forecast_extra_admissions"],
                        "collection_variance": round(hist["actual_collection_rate"] - hist["forecast_collection_rate"], 2)},
            "economics": {k: m.to_dict() for k, m in engine.student_economics(data).items()},
            "badges": BADGE_MEANING,
            "horizon": {"start": data["forecast"]["start_date"], "weeks": data["forecast"]["weeks"]},
            "reserve_status": data["reserve_policy"]["status"],
            "profile": sb.state["profile"],
        }

    def simulate(self, body: Dict[str, Any]) -> Dict[str, Any]:
        data = self.sb.data()
        _, n = engine.horizon(data)
        amount = body.get("amount", 0)
        week = body.get("spend_week", 1)
        if isinstance(week, float) and week.is_integer():
            week = int(week)
        shocks = engine.Shocks.from_dict(body.get("shocks"), n) if body.get("shocks") else engine.DOWNSIDE
        if shocks.is_base():
            shocks = engine.DOWNSIDE
        commitments = self.sb.commitments() if body.get("view", "plan") == "plan" else []
        sim = engine.simulate(data, amount, week, shocks, commitments)
        for key in ("base", "stress"):
            sim[key].pop("lines", None)
            sim[key].pop("weeks", None)
            sti = sim[key].pop("sti")
            sim[key]["sti_value"] = sti["value"]
            sim[key]["binding_week"] = sti["binding_row"]["label"]
            sim[key]["binding_kind"] = sti["binding_kind"]
        return sim

    def plans(self) -> Dict[str, Any]:
        commitments = self.sb.commitments()
        cmp = engine.compare_plans(self.sb.data(), engine.DOWNSIDE, commitments)
        cmp["commitments_total"] = float(sum(line["amount"] for line in commitments))
        for p in cmp["plans"]:
            for mode in ("lump_sum", "staged"):
                ev = p[mode]
                ev["break_even"] = {"economic_break_even": ev["break_even"]["economic_break_even"],
                                    "cash_payback": ev["break_even"]["cash_payback"], "scenarios": ev["break_even"]["scenarios"]}
                ev.pop("base_rows", None)
                ev.pop("stress_rows", None)
        return cmp

    def financing(self, body: Dict[str, Any]) -> Dict[str, Any]:
        sb = self.sb
        plan_id = body.get("plan_id")
        amount = body.get("amount")
        if not plan_id and not amount:
            plan_id = engine.compare_plans(sb.data(), engine.DOWNSIDE, sb.commitments())["recommended_plan_id"] or "PLAN_BALANCED"
        result = financing.match_financing(sb.data(), sb.catalogue, sb.profile(), plan_id=plan_id, amount=amount,
                                           commitments=sb.commitments(), allow_fixes=not body.get("without_fixes"))
        result["commitments_total"] = float(sum(line["amount"] for line in sb.commitments()))
        result["questions"] = sb.catalogue["eligibility_questions"]
        result["profile"] = sb.state["profile"]
        result["catalogue_notice"] = {"en": sb.catalogue["notice_en"], "bn": sb.catalogue["notice_bn"]}
        result["checked_on"] = sb.catalogue["checked_on"]
        return result

    def ledger(self) -> Dict[str, Any]:
        sb = self.sb
        data = sb.data()
        return {
            "months": monthly_ledger(data),
            "forecast_months": {"baseline": engine.forecast_months(data, []), "plan": engine.forecast_months(data, sb.commitments())},
            "month_to_date": {"lines": data["november_to_date_actuals"], "totals": month_to_date(data)},
            "billable_tuition": billable_tuition(data).to_dict(),
            "insight": engine.collection_insight(data),
            "journal": sb.journal.entries(),
            "journal_chain": sb.journal.verify(),
            "dues": sb.dues(),
            "imports": [{k: v for k, v in i.items() if k != "report"} | {"summary": i["report"]["summary"]}
                        for i in sb.state["imports"].values()],
            "category_labels": {k: {"en": v[0], "bn": v[1]} for k, v in CATEGORY_LABELS.items()},
        }

    def audit(self, limit: int) -> Dict[str, Any]:
        return {"entries": self.sb.audit.entries(limit), "chain": self.sb.audit.verify(), "count": self.sb.audit.count(),
                "tiers": tier_table()}

    def proposals(self) -> Dict[str, Any]:
        return {"proposals": self.sb.proposals()}

    def extras(self) -> Dict[str, Any]:
        data = self.sb.data()
        if data.get("meta", {}).get("dataset_label") == "EMPTY_WORKSPACE":
            return {"configured": False, "kit": None, "event": None}
        return {"configured": True, "kit": extras.brain_games_kit(data, self.sb.commitments()), "event": extras.engagement_event(data)}


def _json_default(obj: Any) -> Any:
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"not serialisable: {type(obj)}")


class Handler(BaseHTTPRequestHandler):
    app: App = None  # set by make_server
    server_version = "FinEdvise"
    sys_version = ""

    def log_message(self, fmt_: str, *args: Any) -> None:  # quieter console
        if os.environ.get("FINEDVISE_QUIET"):
            return
        super().log_message(fmt_, *args)

    # ------------------------------------------------------------- helpers
    def _cookie_token(self) -> Optional[str]:
        raw = self.headers.get("Cookie", "")
        m = re.search(r"(?:^|;\s*)finedvise_sid=([A-Za-z0-9_\-]+)", raw)
        return m.group(1) if m else None

    def _common_headers(self, content_type: str, csp: str = CSP, cache: bool = False) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if csp == MEMO_CSP else "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cache-Control", "no-cache" if cache else "no-store")

    def _send(self, status: int, payload: Any, token: Optional[str] = None, new: bool = False, clear_cookie: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self._common_headers("application/json; charset=utf-8")
        secure = "; Secure" if os.environ.get("FINEDVISE_COOKIE_SECURE", "0") == "1" else ""
        if clear_cookie:
            self.send_header("Set-Cookie", f"finedvise_sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{secure}")
        elif new and token:
            self.send_header("Set-Cookie", f"finedvise_sid={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200{secure}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, text: str, content_type: str, csp: str = CSP, extra: Optional[Dict[str, str]] = None) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self._common_headers(content_type, csp, cache=True)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("request too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON object expected")
        return data

    # ---------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = url.path
        query = parse_qs(url.query)
        if path in STATIC:
            name, ctype = STATIC[path]
            file = WEB / name
            if not file.exists():
                return self._send_text(404, "not found", "text/plain; charset=utf-8")
            return self._send_text(200, file.read_text(encoding="utf-8"), ctype)
        if not path.startswith("/api/"):
            return self._send_text(404, "not found", "text/plain; charset=utf-8")
        token = self._cookie_token()
        session = self.app.auth.resolve_session(token) if self.app.auth else {"authenticated": False}
        if (session.get("authenticated") and str(session.get("email", "")).lower() == DEMO_EMAIL.lower()
                and not self.app.demo_enabled):
            self.app.auth.logout(token)
            session = {"authenticated": False}
        try:
            if path == "/api/health":
                return self._send(200, {"ok": True, "version": __version__, "auth_required": True, "product": "FinEdvise"})
            if path == "/api/demo-info":
                return self._send(200, {"enabled": bool(self.app.demo_enabled),
                    "school_name": DEMO_SCHOOL_NAME if self.app.demo_enabled else None,
                    "email": DEMO_EMAIL if self.app.demo_enabled else None,
                    "password": DEMO_PASSWORD if self.app.demo_enabled else None,
                    "notice": "Fictional judge/demo account only. Do not store real school data here." if self.app.demo_enabled else None})
            if path == "/api/session":
                return self._send(200, session)
            if not session.get("authenticated"):
                return self._send(401, {"error": "Please log in to continue.", "authenticated": False})
            if session.get("must_change_password") and path not in {"/api/session"}:
                return self._send(403, {"error": "Please change your temporary password before continuing.", "password_change_required": True})
            app = self.app.for_session(session)
            if path == "/api/overview":
                if session["role"] == "agent":
                    return self._send(200, {"role": "agent", "meta": {"school_name_en": session["school_name"],
                        "school_name_bn": session["school_name"], "notice_en": "Restricted school workspace", "notice_bn": "সীমিত স্কুল ওয়ার্কস্পেস"},
                        "agent": {"mode": "rule", "model": ""}, "pending_count": 0,
                        "account": {"full_name": session["full_name"], "email": session["email"], "role": "agent"}})
                payload = app.overview()
                payload["role"] = session["role"]
                payload["school"] = {"id": session["school_id"], "name": session["school_name"]}
                payload["account"] = {"full_name": session["full_name"], "email": session["email"],
                                        "role": session["role"], "must_change_password": session.get("must_change_password", False)}
                payload["record_summary"] = self.app.auth.records_summary(session)
                return self._send(200, payload)
            if path == "/api/plans":
                if session["role"] == "agent": return self._send(403, {"error": "This role cannot access financial plans."})
                if app.sb.data().get("meta", {}).get("dataset_label") == "EMPTY_WORKSPACE":
                    return self._send(200, {"configured": False, "plans": [], "recommended_plan_id": None,
                        "reason": {"en": "Add verified school fees, cash balances and costs before comparing plans.", "bn": "প্ল্যান তুলনার আগে যাচাইকৃত ফি, নগদ ব্যালেন্স ও খরচ যোগ করুন।"}})
                return self._send(200, app.plans())
            if path == "/api/ledger":
                if session["role"] == "agent": return self._send(403, {"error": "This role cannot access the financial ledger."})
                return self._send(200, app.ledger())
            if path == "/api/audit":
                if session["role"] != "owner":
                    return self._send(403, {"error": "Only the owner can view audit details."})
                limit = int((query.get("limit") or ["200"])[0])
                return self._send(200, app.audit(max(1, min(limit, 2000))))
            if path == "/api/proposals":
                if session["role"] == "agent": return self._send(403, {"error": "This role cannot access financial proposals."})
                return self._send(200, app.proposals())
            if path == "/api/extras":
                if session["role"] == "agent": return self._send(403, {"error": "This role cannot access financial planning tools."})
                return self._send(200, app.extras())
            if path == "/api/financing/catalogue":
                if session["role"] == "agent": return self._send(403, {"error": "This role cannot access financing details."})
                return self._send(200, app.sb.catalogue)
            if path == "/api/financing/checklist":
                if session["role"] == "agent": return self._send(403, {"error": "This role cannot access financing details."})
                option = (query.get("option_id") or [""])[0]
                return self._send(200, financing.loan_checklist(app.sb.catalogue, option, app.sb.profile()))
            if path == "/api/import/sample":
                if session["role"] == "agent": return self._send(403, {"error": "This role cannot access financial imports."})
                return self._send(200, {"filename": SAMPLE_CSV.name, "csv_text": SAMPLE_CSV.read_text(encoding="utf-8")})
            if path == "/api/team":
                return self._send(200, {"members": self.app.auth.list_team(session)})
            if path == "/api/records":
                kind = (query.get("kind") or [""])[0]
                include_archived = (query.get("archived") or ["0"])[0] == "1"
                return self._send(200, {"records": self.app.auth.list_records(session, kind, include_archived)})
            if path == "/api/records/audit":
                limit = int((query.get("limit") or ["100"])[0])
                return self._send(200, {"entries": self.app.auth.record_audit(session, limit)})
            m = re.fullmatch(r"/api/proposals/(P-\d{4})/memo", path)
            if m:
                if session["role"] == "agent":
                    return self._send(403, {"error": "This role cannot access financial decision memos."})
                lang = (query.get("lang") or ["en"])[0]
                html = memo.render(app.sb, m.group(1), lang)
                if html is None:
                    return self._send(404, {"error": "proposal not found"})
                return self._send_text(200, html, "text/html; charset=utf-8", csp=MEMO_CSP)
            return self._send(404, {"error": "unknown endpoint"})
        except AccountError as exc:
            return self._send(exc.status, {"error": str(exc)})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})

    # --------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        token = self._cookie_token()
        session = self.app.auth.resolve_session(token) if self.app.auth else {"authenticated": False}
        if (session.get("authenticated") and str(session.get("email", "")).lower() == DEMO_EMAIL.lower()
                and not self.app.demo_enabled):
            self.app.auth.logout(token)
            session = {"authenticated": False}
        if self.headers.get("X-FinEdvise") != "1":
            return self._send(403, {"error": "missing X-FinEdvise header"})
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": f"bad request: {exc}"})
        try:
            # Public authentication endpoints.
            if path == "/api/auth/signup":
                new_token, new_session = self.app.auth.signup(
                    body.get("school_name"), body.get("owner_name"), body.get("email"),
                    body.get("password"), body.get("phone", ""), body.get("address", ""))
                self.app.for_session(new_session)  # create an isolated workspace before responding
                return self._send(201, {"session": new_session}, new_token, True)
            if path == "/api/auth/login":
                if not self.app.demo_enabled and str(body.get("email", "")).strip().lower() == DEMO_EMAIL.lower():
                    return self._send(403, {"error": "The presentation demo account is disabled on this server."})
                new_token, new_session = self.app.auth.login(body.get("email"), body.get("password"))
                self.app.for_session(new_session)
                return self._send(200, {"session": new_session}, new_token, True)
            if path == "/api/auth/logout":
                self.app.auth.logout(token)
                return self._send(200, {"ok": True}, clear_cookie=True)
            if not session.get("authenticated"):
                return self._send(401, {"error": "Please log in to continue.", "authenticated": False})
            if path == "/api/auth/change-password":
                self.app.auth.change_password(session, body.get("current_password"), body.get("new_password"))
                refreshed = self.app.auth.resolve_session(token)
                return self._send(200, {"ok": True, "session": refreshed})
            if session.get("must_change_password"):
                return self._send(403, {"error": "Please change your temporary password before continuing.", "password_change_required": True})
            app = self.app.for_session(session)
            role = session["role"]
            sb = app.sb
            # Team accounts are owned by the school owner.
            if path == "/api/team":
                member = self.app.auth.create_member(session, body.get("full_name"), body.get("email"), body.get("role"), body.get("phone", ""))
                return self._send(201, {"member": member})
            m = re.fullmatch(r"/api/team/([0-9a-fA-F-]{36})/active", path)
            if m:
                if not isinstance(body.get("active"), bool):
                    raise AccountError("Active must be a true/false value.")
                self.app.auth.set_member_active(session, m.group(1), body["active"])
                return self._send(200, {"ok": True})
            if path == "/api/records":
                record = self.app.auth.create_record(session, body.get("kind"), body.get("data"))
                return self._send(201, {"record": record})
            m = re.fullmatch(r"/api/records/([0-9a-fA-F-]{36})/(update|archive)", path)
            if m:
                rid, verb = m.group(1), m.group(2)
                if verb == "update":
                    record = self.app.auth.update_record(session, rid, body.get("data"))
                    return self._send(200, {"record": record})
                self.app.auth.archive_record(session, rid)
                return self._send(200, {"ok": True})
            if path == "/api/session/role":
                return self._send(410, {"error": "Demo role switching has been removed. Use a separate account for each role."})
            if path == "/api/simulate":
                if role == "agent": return self._send(403, {"error": "This role cannot access financial simulations."})
                if sb.data().get("meta", {}).get("dataset_label") == "EMPTY_WORKSPACE":
                    return self._send(409, {"configured": False, "error": "Add your school's opening balances, fee rules and forecast lines before running a cash-flow simulation."})
                return self._send(200, app.simulate(body))
            if path == "/api/financing":
                if role == "agent": return self._send(403, {"error": "This role cannot access financing details."})
                if sb.data().get("meta", {}).get("dataset_label") == "EMPTY_WORKSPACE":
                    return self._send(409, {"configured": False, "error": "Financing matches need your school's forecast gap and verified eligibility details first."})
                return self._send(200, app.financing(body))
            if path == "/api/financing/answer":
                if role != "owner": return self._send(403, {"error": "Only the owner can update financing assumptions."})
                decision = sb.set_answer(role, str(body.get("question_id", "")), body.get("value"), via="screen")
                code = 200 if decision.allowed else 403
                return self._send(code, {"decision": decision.to_dict(), "profile": sb.state["profile"]})
            if path == "/api/chat":
                message = str(body.get("message", ""))
                if not message.strip(): return self._send(400, {"error": "empty message"})
                lang = body.get("lang") if body.get("lang") in ("en", "bn") else "en"
                # Search only broad, privacy-safe queries derived from topic cues; raw
                # prompts and any student/staff identifiers are never sent to Google.
                research_query = query_for_message(message)
                search_payload = google_search(research_query) if research_query else {"configured": False, "results": []}
                result = app.agent.chat(message, lang, session_id=token or "", actor_role=role,
                                        external_sources=search_payload.get("results", []))
                result["web_research"] = {
                    "attempted": bool(research_query),
                    "configured": bool(search_payload.get("configured")),
                    "available": bool(search_payload.get("results")),
                    "message": search_payload.get("message") if research_query and not search_payload.get("results") else None,
                }
                return self._send(200, result)
            if path == "/api/proposals":
                if role == "agent": return self._send(403, {"error": "This role cannot create financial proposals."})
                amount = body.get("amount")
                decision, proposal = sb.create_proposal(role, plan_id=body.get("plan_id"), amount=amount,
                                                        staged=bool(body.get("staged", True)), spend_week=int(body.get("spend_week") or 1),
                                                        note=str(body.get("note") or ""))
                code = 200 if decision.allowed else 403
                return self._send(code, {"decision": decision.to_dict(), "proposal": proposal})
            m = re.fullmatch(r"/api/proposals/(P-\d{4})/(approve|reject)", path)
            if m:
                pid, verb = m.group(1), m.group(2)
                if verb == "approve":
                    decision, proposal = sb.approve(role, pid, str(body.get("content_hash", "")))
                else:
                    decision, proposal = sb.reject(role, pid, str(body.get("note") or ""))
                code = 200 if decision.allowed else 403
                return self._send(code, {"decision": decision.to_dict(), "proposal": proposal})
            if path == "/api/import/stage":
                if role == "agent": return self._send(403, {"error": "This role cannot import financial data."})
                text = str(body.get("csv_text", ""))
                report = sb.stage_import(role, text, str(body.get("filename") or "upload.csv"))
                return self._send(200, report)
            m = re.fullmatch(r"/api/import/(I-\d{4})/commit", path)
            if m:
                if role != "owner": return self._send(403, {"error": "Only the owner can commit a fee-register import."})
                decision, item = sb.commit_import(role, m.group(1))
                code = 200 if decision.allowed else 403
                return self._send(code, {"decision": decision.to_dict(), "dues": sb.dues()})
            if path == "/api/reminders":
                if role == "agent": return self._send(403, {"error": "This role cannot access guardian reminders."})
                ctx = ToolContext(sb, body.get("lang") if body.get("lang") in ("en", "bn") else "en", actor=role, source="screen")
                out = run_tool(ctx, "draft_parent_reminders", {})
                drafts = app.agent._render_reminders(ctx.reminder_drafts, ctx.lang)  # noqa: SLF001
                return self._send(200, {"result": out.get("result"), "drafts": drafts})
            if path == "/api/settings/reserve":
                if role != "owner": return self._send(403, {"error": "Only the owner can change the reserve policy."})
                decision = sb.set_reserve(role, body.get("amount"))
                return self._send(200 if decision.allowed else 403, {"decision": decision.to_dict()})
            if path == "/api/redteam/run":
                if role != "owner": return self._send(403, {"error": "Only the owner can run security diagnostics."})
                use_ai = bool(body.get("use_ai")) and app.client is not None
                sb.decide("run_red_team", role, {}, {"use_ai": use_ai})
                result = redteam.run(sb, app.client if use_ai else None)
                sb.audit.append("RED_TEAM_RUN", role, total=result["total"], passed=result["passed"],
                                mode=result["agent_mode"], result_hash=result["result_hash"])
                return self._send(200, result)
            if path == "/api/reset":
                if role != "owner": return self._send(403, {"error": "Only the owner can reset this school workspace."})
                decision = sb.reset(role)
                return self._send(200 if decision.allowed else 403, {"decision": decision.to_dict()})
            return self._send(404, {"error": "unknown endpoint"})
        except AccountError as exc:
            return self._send(exc.status, {"error": str(exc)})
        except PolicyDenied as exc:
            return self._send(403, {"decision": exc.decision.to_dict()})
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})


def make_server(host: str = "127.0.0.1", port: int = 8000, var_dir: Optional[Path] = None,
                client: Optional[GeminiClient] = None, use_env_client: bool = True) -> ThreadingHTTPServer:
    sandbox = Sandbox(var_dir)
    if client is None and use_env_client:
        client = GeminiClient.from_env()
    auth_path = sandbox.var / "accounts.sqlite3"
    auth_store = AccountStore(auth_path)
    explicit_demo = os.environ.get("FINEDVISE_ENABLE_DEMO_ACCOUNT")
    if explicit_demo is None:
        demo_enabled = host in ("127.0.0.1", "localhost", "::1")
    else:
        demo_enabled = explicit_demo.strip().lower() in {"1", "true", "yes", "on"}
    if demo_enabled:
        auth_store.ensure_demo_account()
    handler = type("BoundHandler", (Handler,), {"app": App(sandbox, client, auth_store, sandbox.var, demo_enabled)})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="FinEdvise school finance copilot server")
    parser.add_argument("--host", default=os.environ.get("FINEDVISE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--var", default=None, help="folder for sandbox state and logs (default ./var)")
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port, Path(args.var) if args.var else None)
    info = server.RequestHandlerClass.app.agent.info()
    mode = f"AI mode ({info['model']})" if info["mode"] == "gemini" else "rule-based mode (set GEMINI_API_KEY for AI mode)"
    print(f"FinEdvise {__version__} - {mode}")
    print(f"Open http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}  (Ctrl+C to stop)")
    if args.host not in ("127.0.0.1", "localhost"):
        print("Warning: listening on all interfaces. Use HTTPS, secure cookies, database backups, and a reviewed production deployment before exposing this service to the internet.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
