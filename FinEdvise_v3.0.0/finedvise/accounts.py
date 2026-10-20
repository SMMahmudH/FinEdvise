"""SQLite-backed accounts, school memberships, sessions, and editable records.

This module intentionally uses only the Python standard library. Passwords are
PBKDF2-HMAC-SHA256 hashes; session IDs are random bearer tokens whose hashes
are stored in SQLite. Never use the local demo server as an internet-facing
production deployment without HTTPS, backups, and an operational security review.
"""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PBKDF2_ROUNDS = 310_000
DEMO_SCHOOL_NAME = "Golapgonj Ideal Public School"
DEMO_EMAIL = "demo@golapgonj.edu.bd"
DEMO_PASSWORD = "ASDzxc123!@#"
SESSION_SECONDS = 12 * 60 * 60
EMAIL_RE = re.compile(r"^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,63}$")
KINDS = {"students", "staff", "income", "expenses", "inventory"}

FIELDS = {
    "students": {
        "name": "text", "student_id": "text", "class": "text", "guardian_name": "text",
        "guardian_phone": "text", "admission_date": "date", "monthly_fee": "money", "status": "status",
    },
    "staff": {
        "name": "text", "title": "text", "phone": "text", "salary": "money",
        "salary_due_day": "integer", "status": "status",
    },
    "income": {
        "date": "date", "category": "text", "amount": "money", "description": "text",
        "payment_method": "text", "status": "transaction_status", "reference": "text",
    },
    "expenses": {
        "date": "date", "category": "text", "amount": "money", "description": "text",
        "supplier": "text", "due_date": "date", "payment_method": "text", "status": "transaction_status",
    },
    "inventory": {
        "item_name": "text", "category": "text", "quantity": "number", "unit": "text",
        "unit_cost": "money", "reorder_level": "number", "supplier": "text", "purchase_date": "date",
    },
}


class AccountError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id() -> str:
    return str(uuid.uuid4())


def _password_hash(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _validate_password(password: Any) -> str:
    if not isinstance(password, str) or len(password) < 10 or len(password) > 200:
        raise AccountError("Password must be between 10 and 200 characters.")
    return password


def _clean_text(value: Any, label: str, maximum: int = 200, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise AccountError(f"{label} must be text.")
    result = str(value).strip()
    if required and not result:
        raise AccountError(f"{label} is required.")
    if len(result) > maximum:
        raise AccountError(f"{label} must be {maximum} characters or fewer.")
    return result


def _email(value: Any) -> str:
    email = _clean_text(value, "Email", 254, True).lower()
    if not EMAIL_RE.fullmatch(email):
        raise AccountError("Enter a valid email address.")
    return email


def validate_record(kind: Any, raw: Any) -> Dict[str, Any]:
    kind = _clean_text(kind, "Record type", 30, True).lower()
    if kind not in KINDS:
        raise AccountError("Unknown record type.")
    if not isinstance(raw, dict):
        raise AccountError("Record data must be an object.")
    allowed = FIELDS[kind]
    unknown = set(raw) - set(allowed)
    if unknown:
        raise AccountError(f"Unsupported field: {sorted(unknown)[0]}.")
    result: Dict[str, Any] = {}
    for key, field_type in allowed.items():
        if key not in raw:
            continue
        value = raw[key]
        if field_type == "text":
            result[key] = _clean_text(value, key.replace("_", " "), 500, key in {"name", "description"} and kind in {"income", "expenses"} or key == "name" and kind in {"students", "staff"} or key == "item_name")
        elif field_type == "money":
            if value == "" or value is None:
                continue
            if isinstance(value, bool):
                raise AccountError(f"{key.replace('_', ' ').title()} must be a number.")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise AccountError(f"{key.replace('_', ' ').title()} must be a number.")
            if number < 0 or number > 1_000_000_000_000 or number != number or number in (float("inf"), float("-inf")):
                raise AccountError(f"{key.replace('_', ' ').title()} must be a valid non-negative amount.")
            result[key] = round(number, 2)
        elif field_type == "number":
            if value == "" or value is None:
                continue
            if isinstance(value, bool):
                raise AccountError(f"{key.replace('_', ' ').title()} must be a number.")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise AccountError(f"{key.replace('_', ' ').title()} must be a number.")
            if number < 0 or number > 1_000_000_000:
                raise AccountError(f"{key.replace('_', ' ').title()} must be non-negative.")
            result[key] = int(number) if number.is_integer() else number
        elif field_type == "integer":
            if value == "" or value is None:
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise AccountError(f"{key.replace('_', ' ').title()} must be a whole number.")
            if not 1 <= number <= 31:
                raise AccountError("Salary due day must be from 1 to 31.")
            result[key] = number
        elif field_type == "date":
            text = _clean_text(value, key.replace("_", " "), 10)
            if text:
                try:
                    date.fromisoformat(text)
                except ValueError:
                    raise AccountError(f"{key.replace('_', ' ').title()} must use YYYY-MM-DD format.")
                result[key] = text
        elif field_type == "status":
            text = _clean_text(value, key, 30).lower() or "active"
            if text not in {"active", "inactive", "graduated", "left", "on_leave"}:
                raise AccountError("Invalid status value.")
            result[key] = text
        elif field_type == "transaction_status":
            text = _clean_text(value, key, 30).lower() or "unpaid"
            if text not in {"paid", "unpaid", "partial", "planned", "cancelled"}:
                raise AccountError("Invalid transaction status.")
            result[key] = text
    if kind == "students" and "monthly_fee" in result and result["monthly_fee"] < 0:
        raise AccountError("Monthly fee cannot be negative.")
    if kind in {"income", "expenses"} and not result.get("amount") and result.get("amount") != 0:
        raise AccountError("Amount is required.")
    if kind in {"income", "expenses"} and not result.get("date"):
        raise AccountError("Date is required.")
    return result


class AccountStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    @contextmanager
    def _connection(self):
        """Close each short-lived SQLite connection after commit/rollback."""
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connection() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS schools (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    address TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    phone TEXT NOT NULL DEFAULT '',
                    password_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memberships (
                    user_id TEXT NOT NULL REFERENCES users(id),
                    school_id TEXT NOT NULL REFERENCES schools(id),
                    role TEXT NOT NULL CHECK(role IN ('owner','accountant','agent')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, school_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS records (
                    id TEXT PRIMARY KEY,
                    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT NOT NULL REFERENCES users(id),
                    updated_by TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_school_kind ON records(school_id, kind, archived, updated_at);
                CREATE TABLE IF NOT EXISTS record_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    record_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    at TEXT NOT NULL,
                    old_json TEXT,
                    new_json TEXT
                );
                CREATE TABLE IF NOT EXISTS system_flags (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

    def ensure_demo_account(self) -> None:
        """Create the local presentation account and a rich, clearly synthetic dataset once.

        The server only calls this when the demo account is enabled. This credential is
        intentionally shared for judging; never use it for real-school data or leave the
        demo account enabled on an internet-facing deployment.
        """
        app_root = Path(__file__).resolve().parent.parent
        demo_data_path = app_root / "data" / "school.json"
        demo_data = json.loads(demo_data_path.read_text(encoding="utf-8"))
        with self._connection() as c:
            flag = c.execute("SELECT value FROM system_flags WHERE key='demo_seed_v1'").fetchone()
            if flag:
                return
            existing = c.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (DEMO_EMAIL,)).fetchone()
            if existing:
                user_id = existing["id"]
                member = c.execute("SELECT school_id FROM memberships WHERE user_id=? AND role='owner' ORDER BY created_at LIMIT 1", (user_id,)).fetchone()
                if not member:
                    return
                school_id = member["school_id"]
                c.execute("UPDATE schools SET name=? WHERE id=?", (DEMO_SCHOOL_NAME, school_id))
                c.execute("UPDATE users SET full_name=?, active=1, must_change_password=0 WHERE id=?", ("Golapgonj Demo Owner", user_id))
                # The seeded password is for the public presentation workspace only.
                c.execute("UPDATE users SET password_hash=? WHERE id=?", (_password_hash(DEMO_PASSWORD), user_id))
            else:
                school_id, user_id, now = _id(), _id(), utc_now()
                c.execute("INSERT INTO schools(id,name,address,created_at) VALUES(?,?,?,?)",
                          (school_id, DEMO_SCHOOL_NAME, "Golapgonj, Sylhet, Bangladesh (fictional demo)", now))
                c.execute("INSERT INTO users(id,full_name,email,phone,password_hash,active,must_change_password,created_at) VALUES(?,?,?,?,?,1,0,?)",
                          (user_id, "Golapgonj Demo Owner", DEMO_EMAIL, "01000-000000", _password_hash(DEMO_PASSWORD), now))
                c.execute("INSERT INTO memberships(user_id,school_id,role,created_at) VALUES(?,?, 'owner',?)", (user_id, school_id, now))

            existing_records = c.execute("SELECT COUNT(*) AS n FROM records WHERE school_id=?", (school_id,)).fetchone()["n"]
            if not existing_records:
                now = utc_now()
                records = []
                # Seed 150 active students plus one historical withdrawn student to match
                # the scenario's active enrollment while giving the Records page real depth.
                first_names = ["Ayaan", "Maliha", "Tahmid", "Nusrat", "Rafi", "Sumaiya", "Arif", "Lamia", "Zarif", "Tasnim", "Imran", "Farzana", "Siam", "Rumana", "Nafis", "Afia", "Rifat", "Shila", "Hasib", "Nabila", "Sadia", "Fahim", "Jannat", "Rayhan", "Mim", "Adnan", "Sohana", "Abrar", "Anika", "Sakib"]
                surnames = ["Rahman", "Akter", "Hasan", "Jahan", "Chowdhury", "Islam", "Hossain", "Ferdous", "Ahmed", "Haque", "Sarker", "Mim", "Mollah", "Khatun", "Iqbal", "Tabassum", "Mia", "Das", "Uddin", "Sultana", "Karim", "Begum", "Roy", "Siddique", "Khan"]
                classes = ["Play", "Nursery", "KG", "Class 1", "Class 2", "Class 3", "Class 4", "Class 5"]
                roster = {str(x.get("id", "")).replace("STU-", ""): x for x in demo_data.get("roster", {}).get("students", [])}
                # IDs 001–020 use the curated demo roster; more records complete enrollment.
                for idx in range(1, 152):
                    sid = f"{idx:03d}"
                    old = roster.get(sid)
                    name = old["name"] if old else f"{first_names[(idx * 7) % len(first_names)]} {surnames[(idx * 11) % len(surnames)]}"
                    guardian = old.get("guardian", "") if old else f"{first_names[(idx * 13 + 3) % len(first_names)]} {surnames[(idx * 17 + 2) % len(surnames)]}"
                    phone = old.get("phone", "") if old else f"01000-{200000 + idx:06d}"
                    monthly_fee = float(old.get("monthly_fee", 1200)) if old else (700 if idx <= 16 else 1200)
                    status = old.get("status", "active") if old else "active"
                    payload = {"name": name, "student_id": f"GIPS-{idx:03d}", "class": old.get("class", classes[(idx - 1) % len(classes)]) if old else classes[(idx - 1) % len(classes)],
                               "guardian_name": guardian, "guardian_phone": phone, "admission_date": f"{2022 + ((idx - 1) % 5)}-{((idx - 1) % 12) + 1:02d}-{((idx - 1) % 27) + 1:02d}",
                               "monthly_fee": monthly_fee, "status": status}
                    records.append(("students", payload))

                staff_names = [
                    ("Shahana Akter", "Head Teacher", 12500, 5), ("Mizanur Rahman", "Senior Teacher", 9000, 5),
                    ("Farida Yasmin", "Senior Teacher", 8500, 5), ("Abdul Karim", "Teacher", 7500, 5),
                    ("Nargis Sultana", "Teacher", 7200, 5), ("Rasheda Begum", "Teacher", 7000, 5),
                    ("Jamal Uddin", "Teacher", 7000, 5), ("Nasima Khatun", "Teacher", 6800, 5),
                    ("Sanjida Islam", "Teacher", 6800, 5), ("Ruhul Amin", "Teacher", 6700, 5),
                    ("Babul Mia", "Office Assistant", 7000, 5), ("Salma Begum", "Caretaker", 6000, 5),
                ]
                for idx, (name, title, salary, due_day) in enumerate(staff_names, 1):
                    records.append(("staff", {"name": name, "title": title, "phone": f"01000-{300000 + idx:06d}", "salary": salary, "salary_due_day": due_day, "status": "active"}))

                for month in demo_data.get("monthly_actuals_2026", {}).get("months", []):
                    ym = month["month"]
                    year, mon = (int(part) for part in ym.split("-"))
                    dt = f"{ym}-{calendar.monthrange(year, mon)[1]:02d}"
                    for field, category, label in [
                        ("tuition_collected", "Tuition", "Monthly tuition collections"),
                        ("session_and_admission", "Admissions & session fees", "Admission and session fees"),
                        ("exam_fees", "Examination fees", "Examination fee collection"),
                        ("merchandise", "Books and uniforms", "Books, diaries and uniform receipts"),
                    ]:
                        amount = float(month.get(field, 0) or 0)
                        if amount > 0:
                            records.append(("income", {"date": dt, "category": category, "amount": amount, "description": f"{label} — {ym}", "payment_method": "Bank / cash", "status": "paid", "reference": f"GIPS-IN-{ym}-{field}"}))
                    for field, category, label in [
                        ("fixed_costs", "Payroll, rent & utilities", "Monthly fixed operating costs"),
                        ("exam_paper_printing", "Exam printing", "Examination paper and printing"),
                        ("admission_campaign", "Admission campaign", "Admission-season marketing"),
                        ("events_repairs_merch", "Events & maintenance", "Events, repairs and school supplies"),
                    ]:
                        amount = float(month.get(field, 0) or 0)
                        if amount > 0:
                            records.append(("expenses", {"date": dt, "category": category, "amount": amount, "description": f"{label} — {ym}", "supplier": "Local school supplier", "due_date": dt, "payment_method": "Bank / cash", "status": "paid"}))

                # A small, visible set of outstanding fee follow-ups, kept separate from cash.
                for idx, amount in enumerate((3600, 2400, 1800, 1200, 2400, 600), 1):
                    records.append(("income", {"date": f"2026-10-{10 + idx:02d}", "category": "Tuition dues", "amount": amount,
                        "description": f"Synthetic unpaid tuition follow-up {idx}", "payment_method": "Pending", "status": "unpaid", "reference": f"GIPS-DUE-{idx:03d}"}))

                inventory = [
                    ("Exercise books", "Teaching supplies", 450, "pcs", 22, 100, "Rahman Stationery"),
                    ("Whiteboard markers", "Teaching supplies", 48, "pcs", 35, 12, "Rahman Stationery"),
                    ("A4 paper reams", "Printing", 34, "reams", 420, 10, "Modern Paper House"),
                    ("Student diaries", "Books & uniforms", 95, "pcs", 85, 25, "School Book Depot"),
                    ("School uniforms", "Uniforms", 62, "sets", 520, 15, "Ideal Uniforms"),
                    ("Sports cones", "Playground", 16, "pcs", 140, 8, "Active Sports"),
                    ("First-aid refills", "Safety", 4, "kits", 650, 2, "Care Supplies"),
                    ("Classroom fans", "Maintenance", 12, "pcs", 2600, 2, "Golapgonj Electrical"),
                    ("Playground balls", "Playground", 22, "pcs", 180, 8, "Active Sports"),
                    ("Story books", "Library", 126, "pcs", 160, 30, "Little Readers"),
                    ("Art paper packs", "Activities", 41, "packs", 110, 10, "Rahman Stationery"),
                    ("Reusable event banners", "Events", 5, "pcs", 850, 2, "Local Print Studio"),
                    ("Classroom LED bulbs", "Maintenance", 28, "pcs", 95, 8, "Golapgonj Electrical"),
                    ("Floor mats", "Classrooms", 18, "pcs", 480, 4, "Home & School"),
                    ("Handwash bottles", "Hygiene", 36, "bottles", 75, 10, "Care Supplies"),
                    ("Waste bins", "Hygiene", 14, "pcs", 320, 4, "Home & School"),
                    ("Craft scissors", "Activities", 32, "pcs", 55, 10, "Rahman Stationery"),
                    ("Portable speaker", "Events", 2, "pcs", 3200, 1, "AV Corner"),
                ]
                for name, category, qty, unit, cost, reorder, supplier in inventory:
                    records.append(("inventory", {"item_name": name, "category": category, "quantity": qty, "unit": unit,
                        "unit_cost": cost, "reorder_level": reorder, "supplier": supplier, "purchase_date": "2026-08-15"}))

                for kind, payload in records:
                    rid = _id()
                    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                    c.execute("INSERT INTO records(id,school_id,kind,data_json,archived,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,0,?,?,?,?)",
                              (rid, school_id, kind, encoded, user_id, user_id, now, now))
                    c.execute("INSERT INTO record_audit(school_id,record_id,kind,action,actor_user_id,at,old_json,new_json) VALUES(?,?,?,'demo_seed',?,?,NULL,?)",
                              (school_id, rid, kind, user_id, now, encoded))
            c.execute("INSERT OR REPLACE INTO system_flags(key,value,updated_at) VALUES('demo_seed_v1','complete',?)", (utc_now(),))

    def _create_session(self, c: sqlite3.Connection, user_id: str, school_id: str) -> Tuple[str, Dict[str, Any]]:
        token = secrets.token_urlsafe(32)
        now = time.time()
        c.execute("INSERT INTO sessions(token_hash,user_id,school_id,created_at,expires_at) VALUES(?,?,?,?,?)",
                  (hashlib.sha256(token.encode()).hexdigest(), user_id, school_id, now, now + SESSION_SECONDS))
        row = c.execute("""SELECT u.id user_id,u.full_name,u.email,u.must_change_password,m.role,m.school_id,s.name school_name
                           FROM users u JOIN memberships m ON m.user_id=u.id JOIN schools s ON s.id=m.school_id
                           WHERE u.id=? AND s.id=?""", (user_id, school_id)).fetchone()
        return token, self._public_session(row)

    @staticmethod
    def _public_session(row: sqlite3.Row) -> Dict[str, Any]:
        return {"authenticated": True, "user_id": row["user_id"], "full_name": row["full_name"],
                "email": row["email"], "role": row["role"], "school_id": row["school_id"],
                "school_name": row["school_name"], "must_change_password": bool(row["must_change_password"])}

    def signup(self, school_name: Any, owner_name: Any, email: Any, password: Any, phone: Any = "", address: Any = "") -> Tuple[str, Dict[str, Any]]:
        school_name = _clean_text(school_name, "School name", 160, True)
        owner_name = _clean_text(owner_name, "Owner name", 120, True)
        email = _email(email)
        password = _validate_password(password)
        phone = _clean_text(phone, "Phone", 40)
        address = _clean_text(address, "Address", 250)
        sid, uid, now = _id(), _id(), utc_now()
        with self._connection() as c:
            try:
                c.execute("BEGIN IMMEDIATE")
                c.execute("INSERT INTO schools(id,name,address,created_at) VALUES(?,?,?,?)", (sid, school_name, address, now))
                c.execute("INSERT INTO users(id,full_name,email,phone,password_hash,created_at) VALUES(?,?,?,?,?,?)",
                          (uid, owner_name, email, phone, _password_hash(password), now))
                c.execute("INSERT INTO memberships(user_id,school_id,role,created_at) VALUES(?,?, 'owner',?)", (uid, sid, now))
                result = self._create_session(c, uid, sid)
                c.commit()
                return result
            except sqlite3.IntegrityError as exc:
                c.rollback()
                if "users.email" in str(exc).lower() or "unique constraint failed: users.email" in str(exc).lower():
                    raise AccountError("An account with that email already exists. Please log in instead.", 409)
                raise AccountError("Could not create the school account. Please check the details.", 409)

    def login(self, email_value: Any, password_value: Any) -> Tuple[str, Dict[str, Any]]:
        email = _email(email_value)
        if not isinstance(password_value, str) or not password_value or len(password_value) > 200:
            raise AccountError("Invalid email or password.", 401)
        password = password_value
        with self._connection() as c:
            row = c.execute("""SELECT u.id user_id,u.full_name,u.email,u.password_hash,u.active,u.must_change_password,
                                      m.school_id,m.role,s.name school_name
                               FROM users u JOIN memberships m ON m.user_id=u.id JOIN schools s ON s.id=m.school_id
                               WHERE u.email=? COLLATE NOCASE ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END LIMIT 1""", (email,)).fetchone()
            if not row or not row["active"] or not _password_matches(password, row["password_hash"]):
                raise AccountError("Invalid email or password.", 401)
            return self._create_session(c, row["user_id"], row["school_id"])

    def resolve_session(self, token: Optional[str]) -> Dict[str, Any]:
        if not token or len(token) > 200:
            return {"authenticated": False}
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._connection() as c:
            row = c.execute("""SELECT u.id user_id,u.full_name,u.email,u.active,u.must_change_password,m.role,m.school_id,s.name school_name,se.expires_at
                               FROM sessions se JOIN users u ON u.id=se.user_id
                               JOIN memberships m ON m.user_id=u.id AND m.school_id=se.school_id
                               JOIN schools s ON s.id=se.school_id WHERE se.token_hash=?""", (digest,)).fetchone()
            if not row or not row["active"] or row["expires_at"] < time.time():
                c.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
                return {"authenticated": False}
            c.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?", (time.time() + SESSION_SECONDS, digest))
            return {"authenticated": True, "user_id": row["user_id"], "full_name": row["full_name"],
                    "email": row["email"], "role": row["role"], "school_id": row["school_id"],
                    "school_name": row["school_name"], "must_change_password": bool(row["must_change_password"])}

    def logout(self, token: Optional[str]) -> None:
        if token:
            with self._connection() as c:
                c.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def change_password(self, session: Dict[str, Any], current_password: Any, new_password: Any) -> None:
        new_password = _validate_password(new_password)
        with self._connection() as c:
            row = c.execute("SELECT password_hash FROM users WHERE id=?", (session["user_id"],)).fetchone()
            if not isinstance(current_password, str) or not row or not _password_matches(current_password, row["password_hash"]):
                raise AccountError("Current password is incorrect.", 403)
            c.execute("UPDATE users SET password_hash=?,must_change_password=0 WHERE id=?",
                      (_password_hash(new_password), session["user_id"]))

    def create_member(self, session: Dict[str, Any], full_name: Any, email_value: Any, role_value: Any, phone: Any = "") -> Dict[str, Any]:
        if session.get("role") != "owner":
            raise AccountError("Only the school owner can manage accounts.", 403)
        full_name = _clean_text(full_name, "Full name", 120, True)
        email = _email(email_value)
        role = _clean_text(role_value, "Role", 30, True).lower()
        if role not in {"accountant", "agent"}:
            raise AccountError("Role must be accountant or agent.")
        phone = _clean_text(phone, "Phone", 40)
        temp_password = secrets.token_urlsafe(12)
        uid, now = _id(), utc_now()
        with self._connection() as c:
            try:
                c.execute("BEGIN IMMEDIATE")
                c.execute("INSERT INTO users(id,full_name,email,phone,password_hash,must_change_password,created_at) VALUES(?,?,?,?,?,1,?)",
                          (uid, full_name, email, phone, _password_hash(temp_password), now))
                c.execute("INSERT INTO memberships(user_id,school_id,role,created_at) VALUES(?,?,?,?)",
                          (uid, session["school_id"], role, now))
                c.execute("""INSERT INTO record_audit(school_id,record_id,kind,action,actor_user_id,at,old_json,new_json)
                             VALUES(?,?,'team','create_member',?,?,NULL,?)""",
                          (session["school_id"], uid, session["user_id"], now, json.dumps({"email": email, "role": role})))
                c.commit()
            except sqlite3.IntegrityError:
                c.rollback()
                raise AccountError("That email already has an account. Use another email.", 409)
        return {"user_id": uid, "full_name": full_name, "email": email, "phone": phone,
                "role": role, "active": True, "temporary_password": temp_password,
                "must_change_password": True, "created_at": now}

    def list_team(self, session: Dict[str, Any]) -> List[Dict[str, Any]]:
        if session.get("role") != "owner":
            raise AccountError("Only the school owner can view team accounts.", 403)
        with self._connection() as c:
            rows = c.execute("""SELECT u.id user_id,u.full_name,u.email,u.phone,u.active,u.must_change_password,u.created_at,m.role
                               FROM users u JOIN memberships m ON m.user_id=u.id WHERE m.school_id=?
                               ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'accountant' THEN 1 ELSE 2 END,u.full_name""",
                             (session["school_id"],)).fetchall()
            return [{"user_id": r["user_id"], "full_name": r["full_name"], "email": r["email"], "phone": r["phone"],
                     "active": bool(r["active"]), "must_change_password": bool(r["must_change_password"]),
                     "created_at": r["created_at"], "role": r["role"]} for r in rows]

    def set_member_active(self, session: Dict[str, Any], user_id: str, active: bool) -> None:
        if session.get("role") != "owner":
            raise AccountError("Only the school owner can manage accounts.", 403)
        if user_id == session["user_id"]:
            raise AccountError("You cannot deactivate your own owner account.", 400)
        with self._connection() as c:
            row = c.execute("SELECT u.id,m.role FROM users u JOIN memberships m ON m.user_id=u.id WHERE u.id=? AND m.school_id=?",
                            (user_id, session["school_id"])).fetchone()
            if not row:
                raise AccountError("Team member not found in this school.", 404)
            if row["role"] == "owner":
                raise AccountError("The owner account cannot be deactivated here.", 403)
            c.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
            if not active:
                c.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            c.execute("INSERT INTO record_audit(school_id,record_id,kind,action,actor_user_id,at,old_json,new_json) VALUES(?,?,'team',?,?,?, ?,?)",
                      (session["school_id"], user_id, "activate_member" if active else "deactivate_member", session["user_id"], utc_now(),
                       json.dumps({"active": not active}), json.dumps({"active": active})))

    @staticmethod
    def can_access_kind(role: str, kind: str, write: bool = False) -> bool:
        if role == "owner":
            return True
        if role == "accountant":
            return kind in KINDS
        if role == "agent":
            return kind in {"students", "staff", "inventory"} and not write
        return False

    def list_records(self, session: Dict[str, Any], kind: Any, include_archived: bool = False) -> List[Dict[str, Any]]:
        kind = _clean_text(kind, "Record type", 30, True).lower()
        if kind not in KINDS:
            raise AccountError("Unknown record type.")
        if not self.can_access_kind(session.get("role", ""), kind, False):
            raise AccountError("You do not have permission to view these records.", 403)
        with self._connection() as c:
            rows = c.execute("""SELECT id,kind,data_json,archived,created_by,updated_by,created_at,updated_at FROM records
                               WHERE school_id=? AND kind=? AND (?=1 OR archived=0) ORDER BY updated_at DESC LIMIT 1000""",
                             (session["school_id"], kind, 1 if include_archived else 0)).fetchall()
            return [{"id": r["id"], "kind": r["kind"], "data": json.loads(r["data_json"]), "archived": bool(r["archived"]),
                     "created_by": r["created_by"], "updated_by": r["updated_by"], "created_at": r["created_at"], "updated_at": r["updated_at"]}
                    for r in rows]

    def create_record(self, session: Dict[str, Any], kind: Any, raw: Any) -> Dict[str, Any]:
        kind = _clean_text(kind, "Record type", 30, True).lower()
        if not self.can_access_kind(session.get("role", ""), kind, True):
            raise AccountError("You do not have permission to create this record.", 403)
        data = validate_record(kind, raw)
        rid, now = _id(), utc_now()
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        with self._connection() as c:
            c.execute("INSERT INTO records(id,school_id,kind,data_json,created_by,updated_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                      (rid, session["school_id"], kind, encoded, session["user_id"], session["user_id"], now, now))
            c.execute("INSERT INTO record_audit(school_id,record_id,kind,action,actor_user_id,at,old_json,new_json) VALUES(?,?,?,'create',?,?,NULL,?)",
                      (session["school_id"], rid, kind, session["user_id"], now, encoded))
        return {"id": rid, "kind": kind, "data": data, "archived": False, "created_by": session["user_id"],
                "updated_by": session["user_id"], "created_at": now, "updated_at": now}

    def update_record(self, session: Dict[str, Any], rid: str, raw: Any) -> Dict[str, Any]:
        with self._connection() as c:
            row = c.execute("SELECT kind,data_json,archived FROM records WHERE id=? AND school_id=?",
                            (rid, session["school_id"])).fetchone()
            if not row:
                raise AccountError("Record not found in this school.", 404)
            kind = row["kind"]
            if not self.can_access_kind(session.get("role", ""), kind, True):
                raise AccountError("You do not have permission to edit this record.", 403)
            if row["archived"]:
                raise AccountError("Archived records cannot be edited. Restore it first.", 409)
            data = validate_record(kind, raw)
            old = row["data_json"]
            encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            now = utc_now()
            c.execute("UPDATE records SET data_json=?,updated_by=?,updated_at=? WHERE id=? AND school_id=?",
                      (encoded, session["user_id"], now, rid, session["school_id"]))
            c.execute("INSERT INTO record_audit(school_id,record_id,kind,action,actor_user_id,at,old_json,new_json) VALUES(?,?,?,'update',?,?,?,?)",
                      (session["school_id"], rid, kind, session["user_id"], now, old, encoded))
            return {"id": rid, "kind": kind, "data": data, "archived": False,
                    "created_by": None, "updated_by": session["user_id"], "updated_at": now}

    def archive_record(self, session: Dict[str, Any], rid: str) -> None:
        with self._connection() as c:
            row = c.execute("SELECT kind,data_json,archived FROM records WHERE id=? AND school_id=?",
                            (rid, session["school_id"])).fetchone()
            if not row:
                raise AccountError("Record not found in this school.", 404)
            if not self.can_access_kind(session.get("role", ""), row["kind"], True):
                raise AccountError("You do not have permission to archive this record.", 403)
            if row["archived"]:
                return
            now = utc_now()
            c.execute("UPDATE records SET archived=1,updated_by=?,updated_at=? WHERE id=? AND school_id=?",
                      (session["user_id"], now, rid, session["school_id"]))
            c.execute("INSERT INTO record_audit(school_id,record_id,kind,action,actor_user_id,at,old_json,new_json) VALUES(?,?,?,'archive',?,?,?,NULL)",
                      (session["school_id"], rid, row["kind"], session["user_id"], now, row["data_json"]))

    def records_summary(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize manually recorded transactions without guessing cash status."""
        if session.get("role") not in {"owner", "accountant"}:
            raise AccountError("This role cannot view financial record summaries.", 403)
        totals = {
            "income": {"count": 0, "paid": 0.0, "unpaid_or_planned": 0.0, "partial": 0.0, "cancelled": 0.0},
            "expenses": {"count": 0, "paid": 0.0, "unpaid_or_planned": 0.0, "partial": 0.0, "cancelled": 0.0},
        }
        counts = {kind: {"count": 0, "active": 0} for kind in ("students", "staff", "inventory")}
        with self._connection() as c:
            rows = c.execute("SELECT kind,data_json FROM records WHERE school_id=? AND archived=0 AND kind IN ('income','expenses')",
                             (session["school_id"],)).fetchall()
            count_rows = c.execute("SELECT kind,data_json FROM records WHERE school_id=? AND archived=0 AND kind IN ('students','staff','inventory')",
                                   (session["school_id"],)).fetchall()
        for row in count_rows:
            item = json.loads(row["data_json"])
            bucket = counts[row["kind"]]
            bucket["count"] += 1
            if str(item.get("status", "active")).lower() == "active" or row["kind"] == "inventory":
                bucket["active"] += 1
        for row in rows:
            kind = row["kind"]
            data = json.loads(row["data_json"])
            target = totals[kind]
            target["count"] += 1
            try:
                amount = float(data.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amount = 0.0
            status = str(data.get("status", "unpaid")).lower()
            if status == "paid":
                target["paid"] += amount
            elif status == "partial":
                target["partial"] += amount
            elif status == "cancelled":
                target["cancelled"] += amount
            else:
                target["unpaid_or_planned"] += amount
        for item in totals.values():
            for key, value in list(item.items()):
                if key != "count":
                    item[key] = round(value, 2)
        return {**totals, **counts, "net_cash_from_records": round(totals["income"]["paid"] - totals["expenses"]["paid"], 2),
                "basis": "Only entries explicitly marked paid are included in paid totals. Partial entries are shown separately because the paid portion is not stored separately.",
                "forecast_linked": False}

    def record_audit(self, session: Dict[str, Any], limit: int = 200) -> List[Dict[str, Any]]:
        if session.get("role") != "owner":
            raise AccountError("Only the owner can view the record audit history.", 403)
        with self._connection() as c:
            rows = c.execute("""SELECT a.record_id,a.kind,a.action,a.actor_user_id,u.full_name actor_name,a.at,a.old_json,a.new_json
                               FROM record_audit a LEFT JOIN users u ON u.id=a.actor_user_id
                               WHERE a.school_id=? ORDER BY a.id DESC LIMIT ?""",
                             (session["school_id"], max(1, min(int(limit), 500)))).fetchall()
            return [{"record_id": r["record_id"], "kind": r["kind"], "action": r["action"],
                     "actor_user_id": r["actor_user_id"], "actor_name": r["actor_name"] or "Unknown user",
                     "at": r["at"], "old": json.loads(r["old_json"]) if r["old_json"] else None,
                     "new": json.loads(r["new_json"]) if r["new_json"] else None} for r in rows]
