"""Check the Gemini setup in under a minute.

    GEMINI_API_KEY=... python -m finedvise.check_gemini

Lists the models your key can use for generateContent, then asks one
question through the real agent and prints which tools were called and
whether the answer passed the number check. Uses 2-4 requests.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from .agent import Agent
from .data import ROOT
from .envfile import load_env_file
from .gemini import GeminiClient, GeminiError
from .store import Sandbox


def main() -> None:
    load_env_file(ROOT / ".env")
    client = GeminiClient.from_env()
    if client is None:
        sys.exit("GEMINI_API_KEY is not set. The app will run in rule-based mode.")
    try:
        models = client.list_models()
        flash = [m for m in models if "flash" in m]
        print(f"Your key can use {len(models)} models. Flash models: {', '.join(flash[:12]) or 'none'}")
        if client.models[0] not in models:
            print(f"Note: {client.models[0]} is not in that list. Set FINEDVISE_GEMINI_MODEL to one of the models above.")
    except GeminiError as exc:
        print(f"Could not list models: {exc}")
    agent = Agent(Sandbox(Path(tempfile.mkdtemp(prefix="finedvise-check-"))), client)
    reply = agent.chat("How much can I safely spend on the admission campaign now?", "en")
    print(f"Mode used: {reply['mode']} {reply['model'] or ''}")
    if reply["fallback_reason"]:
        print(f"Fallback reason: {reply['fallback_reason']}")
    print("Tools called:", ", ".join(f"{c['name']} ({c['decision']})" for c in reply["tool_calls"]) or "none")
    print(f"Number check passed: {reply['guardrail'].get('passed')} ({reply['guardrail'].get('numbers_checked')} numbers)")
    print("Answer:", reply["reply"])
    print(f"Requests made: {client.requests_made}")


if __name__ == "__main__":
    main()
