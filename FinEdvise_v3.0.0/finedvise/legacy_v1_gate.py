"""The v1 keyword gate from the first commit, kept only for the red-team comparison.

It matched five keyword patterns and was the whole of v1's "security". The
red-team suite runs the same attacks against it to show which ones it missed
and which design change fixed them. Not used anywhere else.
"""
import re

V1_PATTERNS = [
    (r"ignore\s+reserve|রিজার্ভ\s+নীতি\s+ভুলে\s+যাও|bypass\s+reserve", "RESERVE_POLICY_BYPASS_ATTEMPT"),
    (r"delete\s+.*entry|delete\s+.*transaction|মুছে\s+দাও|ডিলিট\s+করো", "LEDGER_TAMPERING_ATTEMPT"),
    (r"execute\s+payment\s+now|transfer\s+funds\s+immediately|এখনই.*পেমেন্ট\s+করো", "UNAUTHORIZED_PAYMENT_EXECUTION"),
    (r"system\s+prompt|ignore\s+previous\s+instructions|jailbreak", "PROMPT_INJECTION_ATTEMPT"),
]


def v1_would_block(text: str) -> bool:
    return any(re.search(pattern, text or "", flags=re.IGNORECASE) for pattern, _ in V1_PATTERNS)
