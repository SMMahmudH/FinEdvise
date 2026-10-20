"""Extras, kept out of the main flow: a brain-games kit venture and an event.

Demand and retention effects are owner guesses, labelled ASSUMED. The screen
shows break-even thresholds ("how many must it bring") rather than claims
("it will bring"). The kit idea carries risk flags and a 50% pre-booking rule.
"""
from __future__ import annotations

import math
from typing import Any, Dict

from . import engine


def brain_games_kit(data: Dict[str, Any], commitments=()) -> Dict[str, Any]:
    k = data["extras"]["brain_games_kit"]
    need = max(0, k["needed_for_classrooms"] - k["current_stock"])
    extra = k["proposed_extra_units"]
    order = need + extra
    bulk = order >= k["bulk_min_qty"]
    unit = k["unit_price_bulk"] if bulk else k["unit_price_spot"]
    venture_cost = extra * unit
    total_cash = order * unit
    base_sold = min(extra, k["demand_estimate"]["base"])
    down_sold = min(extra, k["demand_estimate"]["downside"])
    base_profit = base_sold * k["sale_price"] - venture_cost
    down_profit = down_sold * k["sale_price"] - venture_cost
    breakeven_units = math.ceil(venture_cost / k["sale_price"])
    prebook_needed = math.ceil(extra * k["prebooking_rule_pct"])
    rental_monthly = base_sold * k["rental_fee_monthly"]
    sim = engine.simulate(data, 0.0, 1, engine.DOWNSIDE, commitments)
    return {
        "label_en": k["label_en"], "label_bn": k["label_bn"],
        "classroom_need": need, "extra_units": extra, "order_qty": order, "bulk_price_applies": bulk, "unit_price": unit,
        "classroom_saving_from_bulk": need * (k["unit_price_spot"] - unit),
        "venture_cost": venture_cost, "total_cash_needed": total_cash,
        "storage_ok": k["current_stock"] + order <= k["storage_limit"],
        "sale_price": k["sale_price"], "break_even_units": breakeven_units,
        "demand_estimate": k["demand_estimate"],
        "base": {"units_sold": base_sold, "profit": base_profit, "roi_pct": round(100 * base_profit / venture_cost, 1) if venture_cost else 0},
        "downside": {"units_sold": down_sold, "profit": down_profit, "unsold_units": extra - down_sold,
                     "cash_locked_in_unsold": (extra - down_sold) * unit},
        "rental_option": {"monthly_fee": k["rental_fee_monthly"], "monthly_income_base": rental_monthly,
                          "months_to_payback": round(venture_cost / rental_monthly, 1) if rental_monthly else None},
        "prebooking_rule": {"pct": k["prebooking_rule_pct"], "prebookings_needed_before_ordering": prebook_needed},
        "safe_to_spend_now": {"base": sim["base"]["sti"]["value"], "stress": sim["stress"]["sti"]["value"]},
        "risk_flags": [
            {"en": "Stock risk: in the downside guess, unsold kits lock up cash.", "bn": "মজুদের ঝুঁকি: খারাপ অনুমানে না বিক্রি হওয়া কিটে টাকা আটকে যায়।"},
            {"en": "Pressure on parents: the kit must stay optional; no child is treated differently.", "bn": "অভিভাবকদের ওপর চাপ: কিট ঐচ্ছিক থাকবে; কোনো শিশুর সাথে আলাদা আচরণ নয়।"},
            {"en": "Same cash as the admission budget: it competes with the safe-to-spend limit.", "bn": "ভর্তি বাজেটের একই টাকা: এটি নিরাপদ খরচের সীমায় ভাগ বসায়।"},
            {"en": "Demand is a guess (ASSUMED): order extra kits only after the pre-booking rule is met.", "bn": "চাহিদা অনুমান (ASSUMED): প্রি-বুকিং নিয়ম পূরণ হলে তবেই অতিরিক্ত কিট অর্ডার।"},
        ],
    }


def engagement_event(data: Dict[str, Any]) -> Dict[str, Any]:
    ev = data["extras"]["engagement_event"]
    heads = ev["paying_students"] + ev["free_guests_and_teachers"]
    cost = ev["fixed_costs"] + heads * ev["cost_per_person"]
    collected = ev["paying_students"] * ev["contribution_per_student"]
    subsidy = cost - collected
    breakeven_fee = math.ceil(cost / ev["paying_students"])
    contribution = engine.student_economics(data)["net_contribution"].value
    students_to_cover = round(subsidy / contribution, 2) if contribution else None
    return {
        "label_en": ev["label_en"], "label_bn": ev["label_bn"],
        "people_fed": heads, "total_cost": cost, "collected": collected, "school_subsidy": subsidy,
        "break_even_contribution_per_student": breakeven_fee,
        "students_to_cover_subsidy": students_to_cover,
        "students_to_cover_subsidy_whole": math.ceil(subsidy / contribution) if contribution and subsidy > 0 else 0,
        "owner_belief": ev["retention_and_referral_effect"],
        "honest_reading_en": "The fair costs the school its subsidy for sure; it pays for itself only if it keeps or brings at least this many students. That effect is a guess, not a forecast.",
        "honest_reading_bn": "মেলার ভর্তুকি নিশ্চিত খরচ; অন্তত এতজন শিক্ষার্থী ধরে রাখতে বা আনতে পারলে তবেই খরচ ওঠে। এই প্রভাব অনুমান, পূর্বাভাস নয়।",
    }
