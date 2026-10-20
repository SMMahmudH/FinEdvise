"""Factories for workspace-specific forecast data.

The judge demo intentionally uses the curated SYNTHETIC_DEMO_DATA scenario. New
schools receive a schema-valid zeroed workspace until an owner records their
own opening balances, fees, costs and forecast assumptions.
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
SCHOOL_FILE = ROOT / "data" / "school.json"


def dhaka_today() -> date:
    return datetime.now(ZoneInfo("Asia/Dhaka")).date()


def blank_workspace_data(school_name: str, source_path: Path | None = None, today: date | None = None) -> Dict[str, Any]:
    """Create a blank, internally consistent dataset for a new school.

    It retains the engine's schema and formulas but zeroes every school-specific
    financial assumption and transaction. It never copies the demo roster,
    cash balance, actuals, plans or forecasts into a newly registered account.
    """
    data = json.loads(Path(source_path or SCHOOL_FILE).read_text(encoding="utf-8"))
    now = today or dhaka_today()
    iso = now.isoformat()
    data["meta"].update({
        "dataset_label": "EMPTY_WORKSPACE",
        "school_name_en": school_name or "My School",
        "school_name_bn": school_name or "আমার স্কুল",
        "scenario_date": iso,
        "data_version": "3.0.0-empty-workspace",
        "notice_en": "Fresh school workspace. Forecasts are not ready until the owner adds verified school assumptions.",
        "notice_bn": "নতুন স্কুল ওয়ার্কস্পেস। মালিক যাচাইকৃত তথ্য যোগ না করা পর্যন্ত পূর্বাভাস প্রস্তুত নয়।",
    })

    data["profile"].update({
        "classes": "Not configured yet", "active_students": 0, "classroom_capacity": 0,
        "teachers": 0, "support_staff": 0, "years_operating": 0,
    })
    for key, value in list(data["fees"].items()):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            data["fees"][key] = 0
    data["fees"]["scholarships"]["students"] = 0
    data["fees"]["scholarships"]["monthly_waiver_per_student"] = 0
    data["fees"]["scholarships"]["note_en"] = "No fee or scholarship policy entered yet."
    data["fees"]["scholarships"]["note_bn"] = "এখনও কোনো ফি বা বৃত্তির নীতি যোগ করা হয়নি।"
    for key in data["monthly_costs"]:
        data["monthly_costs"][key] = 0

    data["reserve_policy"].update({
        "minimum_reserve": 0, "status": "SETUP_REQUIRED",
        "rationale_en": "No reserve target has been entered. Add a reserve after reviewing your school’s payroll and fixed costs.",
        "rationale_bn": "এখনও রিজার্ভ লক্ষ্য নির্ধারণ করা হয়নি। বেতন ও স্থায়ী খরচ পর্যালোচনা করে লক্ষ্য যোগ করুন।",
    })
    data["opening_position"].update({
        "as_of": iso, "cash_in_hand": 0, "bank": 0, "bkash_available": 0,
        "bkash_pending": {"amount": 0, "expected_date": iso, "note_en": "No opening position recorded.", "note_bn": "কোনো প্রারম্ভিক ব্যালেন্স রেকর্ড করা হয়নি।"},
        "source_en": "Not configured — add an opening cash count and bank balance.",
        "source_bn": "কনফিগার করা হয়নি — হাতে নগদ ও ব্যাংক ব্যালেন্স যোগ করুন।",
    })

    for month in data["monthly_actuals_2026"]["months"]:
        for key, value in list(month.items()):
            if key not in {"month", "note_en", "note_bn"} and isinstance(value, (int, float)):
                month[key] = 0
        month["note_en"] = "No actuals imported for this period."
        month["note_bn"] = "এই সময়ের কোনো প্রকৃত হিসাব ইমপোর্ট করা হয়নি।"
    data["monthly_actuals_2026"]["opening_cash_jan"] = 0
    data["monthly_actuals_2026"]["outstanding_tuition_opening_jan"] = 0

    data["november_to_date_actuals"] = []
    data["forecast"].update({
        "start_date": iso, "weeks": 8, "week_starts_on": "Sunday",
        "horizon_note_en": "An empty planning horizon. Add expected receipts and committed payments before relying on this forecast.",
        "horizon_note_bn": "পরিকল্পনার সময়সীমা খালি। পূর্বাভাসের ওপর নির্ভর করার আগে সম্ভাব্য আয় ও নির্ধারিত খরচ যোগ করুন।",
        "lines": [],
    })
    for key in ("admission_fee", "session_fee", "monthly_tuition", "new_student_discount",
                "variable_cost_books_id_diary", "variable_cost_exam_materials"):
        data["student_economics"][key] = 0
    data["student_economics"]["collection_rate"] = 0.0
    data["student_economics"]["retention_probability"] = 0.0
    data["student_economics"]["method_note_en"] = "Configure actual fees, collection rate and variable costs before estimating break-even."
    data["student_economics"]["method_note_bn"] = "ব্রেক-ইভেন হিসাবের আগে প্রকৃত ফি, আদায়ের হার ও পরিবর্তনশীল খরচ নির্ধারণ করুন।"
    data["plans"] = []
    data["history"] = [{
        "id": "NO_HISTORY", "period_en": "No campaign history entered yet", "period_bn": "এখনও কোনো প্রচারণার ইতিহাস নেই",
        "approved_budget": 0, "forecast_extra_admissions": 0, "actual_extra_admissions": 0,
        "forecast_collection_rate": 0, "actual_collection_rate": 0,
        "update_en": "This is a new workspace. Add verified historical results before using trend-based recommendations.",
        "update_bn": "এটি নতুন ওয়ার্কস্পেস। প্রবণতাভিত্তিক পরামর্শের আগে যাচাইকৃত অতীতের ফলাফল যোগ করুন।",
    }]
    data["open_questions"] = [{
        "id": "Q_SETUP", "priority": 1, "field": "workspace_setup",
        "q_en": "What are your current opening balances, monthly tuition and essential costs?",
        "q_bn": "আপনার বর্তমান প্রারম্ভিক ব্যালেন্স, মাসিক টিউশন ও জরুরি খরচ কত?",
    }]
    data["roster"].update({
        "note_en": "No student roster has been added to this workspace yet.",
        "note_bn": "এই ওয়ার্কস্পেসে এখনও কোনো শিক্ষার্থী তালিকা যোগ করা হয়নি।",
        "students": [],
    })
    # Keep calculation schemas accessible but remove demo-only business assumptions.
    data["extras"] = {
        "brain_games_kit": {
            "label_en": "School activity kit", "label_bn": "স্কুল কার্যক্রম কিট",
            "current_stock": 0, "needed_for_classrooms": 0, "unit_price_spot": 0, "unit_price_bulk": 0,
            "bulk_min_qty": 0, "storage_limit": 0, "proposed_extra_units": 0, "sale_price": 0,
            "rental_fee_monthly": 0, "demand_estimate": {"base": 0, "downside": 0, "status": "ASSUMED",
            "source_en": "Not configured.", "source_bn": "কনফিগার করা হয়নি।"}, "prebooking_rule_pct": 0.5,
        },
        "engagement_event": {
            "label_en": "School engagement event", "label_bn": "স্কুল অংশগ্রহণমূলক অনুষ্ঠান",
            "fixed_costs": 0, "cost_per_person": 0, "paying_students": 0, "free_guests_and_teachers": 0,
            "contribution_per_student": 0, "retention_and_referral_effect": {"retained_students": 0, "new_admissions": 0,
            "status": "ASSUMED", "source_en": "Not configured.", "source_bn": "কনফিগার করা হয়নি।"},
        },
    }
    return data
