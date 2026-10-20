"""Optional, privacy-conscious Google Programmable Search integration.

Only generic school/finance research questions are sent to Google. Messages that
contain contact details, student IDs or apparent transaction instructions are
never searched. Configure FINEDVISE_GOOGLE_CSE_API_KEY and FINEDVISE_GOOGLE_CSE_CX to enable it.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from typing import Any, Dict, List, Optional

PII_OR_PRIVATE = re.compile(
    r"(?:[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b(?:STU|GRD|GIPS)-?\d{2,}\b|\b(?:\+?\d[\d\s().-]{7,}\d)\b)",
    re.IGNORECASE,
)
SENSITIVE_ACTION = re.compile(r"\b(pay|transfer|send|delete|edit|approve|settle|share|export|message)\b.{0,50}\b(parent|guardian|student|vendor|supplier|record|account|data|money|fund|loan)\b", re.I)
CURRENT_TIME_QUESTION = re.compile(
    r"\b(what time|current time|time is it|today.s date|what date|date today|what day is it|current date and time)\b|এখন সময়|বর্তমান সময়|আজ কত তারিখ|আজ কী বার", re.I
)
SEARCH_CUES = re.compile(
    r"\b(current|currently|latest|recent|online|google|web|research|source|reference|guideline|guidance|law|legal|regulation|policy|market price|price|rate|budget|cost|expense|bill|saving|savings|tuition|fee|fees|admission|procurement|inventory|supplier|electricity|energy|maintenance|cash flow|financial|finance|salary|payroll|ideas|activity|activities|picnic|party|feast|feed|decoration|playground|repair|sports day|school event|best practice)\b|"
    r"(বর্তমান|সর্বশেষ|আজকের|গাইডলাইন|আইন|নিয়ম|দাম|দর|বাজেট|খরচ|ব্যয়|বিল|সঞ্চয়|টিউশন|বেতন|ফি|ভর্তি|ক্রয়|মজুত|সরবরাহকারী|বিদ্যুৎ|রক্ষণাবেক্ষণ|নগদ প্রবাহ|অর্থায়ন|পিকনিক|পার্টি|খাবার|সাজসজ্জা|খেলার মাঠ|মেরামত|অনুষ্ঠান)", re.I
)


def query_for_message(message: str) -> Optional[str]:
    """Return a generic search query, never the raw chat message."""
    text = (message or "").strip()
    if not text or len(text) > 2000 or CURRENT_TIME_QUESTION.search(text) or not SEARCH_CUES.search(text):
        return None
    if PII_OR_PRIVATE.search(text) or SENSITIVE_ACTION.search(text):
        return None
    low = text.lower()
    if re.search(r"picnic|class party|school feast|school feed|food day|পিকনিক|পার্টি|খাবার", low):
        topic = "school picnic class party healthy school feast activity ideas Bangladesh child safety"
    elif re.search(r"playground|decoration|repair|sports day|খেলার মাঠ|সাজসজ্জা|মেরামত", low):
        topic = "Bangladesh primary school playground safety maintenance decoration sports day ideas"
    elif re.search(r"law|legal|regulation|policy|data protection|privacy|আইন|নিয়ম", low):
        topic = "Bangladesh official education institution financial governance child data protection guidance"
    elif re.search(r"budget|cost|expense|bill|saving|tuition|fee|admission|procurement|inventory|supplier|electricity|energy|maintenance|cash flow|finance|loan|interest|rate|market price|financing|বাজেট|খরচ|ব্যয়|বিল|সঞ্চয়|টিউশন|বেতন|ফি|ভর্তি|ক্রয়|মজুত|সরবরাহকারী|বিদ্যুৎ|রক্ষণাবেক্ষণ|নগদ প্রবাহ|অর্থায়ন|ঋণ|সুদ|দাম", low):
        topic = "Bangladesh small private school budgeting costs fee collection procurement maintenance current guidance"
    elif re.search(r"website|app|copilot|software|সাইট|অ্যাপ", low):
        topic = "school finance software UX accessibility best practices"
    elif re.search(r"teacher|staff|salary|payroll|attendance|শিক্ষক|কর্মী|বেতন", low):
        topic = "Bangladesh private school teacher staff payroll administration best practice"
    else:
        # Never send the user's own phrasing, names, or amounts to the search provider.
        topic = "Bangladesh private school administration and financial management current guidance"
    return topic[:180]


def google_search(query: str, limit: int = 5) -> Dict[str, Any]:
    """Search the configured Programmable Search Engine, returning source snippets only."""
    key = os.environ.get("FINEDVISE_GOOGLE_CSE_API_KEY")
    cx = os.environ.get("FINEDVISE_GOOGLE_CSE_CX")
    if not key or not cx:
        return {"configured": False, "available": False, "results": [], "message": "Live web research is not configured. Add FINEDVISE_GOOGLE_CSE_API_KEY and FINEDVISE_GOOGLE_CSE_CX to enable it."}
    if not isinstance(query, str) or not query.strip() or len(query) > 240:
        return {"configured": True, "available": False, "results": [], "message": "A valid generic search query is required."}
    params = urlencode({"key": key, "cx": cx, "q": query, "num": max(1, min(int(limit), 5)), "safe": "active"})
    request = Request("https://www.googleapis.com/customsearch/v1?" + params,
                      headers={"Accept": "application/json", "User-Agent": "FinEdvise/3.0 school-research"})
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except Exception as exc:  # unavailable external research must never break Copilot
        return {"configured": True, "available": False, "results": [], "message": f"Live web research is temporarily unavailable ({type(exc).__name__})."}
    results: List[Dict[str, str]] = []
    for item in payload.get("items", [])[:5]:
        link = str(item.get("link", ""))
        if not link.startswith("https://"):
            continue
        results.append({
            "title": str(item.get("title", "Untitled source"))[:200],
            "link": link[:1000],
            "snippet": re.sub(r"\s+", " ", str(item.get("snippet", "")))[:500],
            "source": str(item.get("displayLink", ""))[:120],
        })
    return {"configured": True, "available": bool(results), "results": results, "query": query}
