#!/usr/bin/env python3
"""Start FinEdvise: python run.py  ->  http://127.0.0.1:8000

Optional settings (environment variables, or a .env file next to this script):
  GEMINI_API_KEY=...            turn on AI mode (otherwise rule-based mode)
  FINEDVISE_GEMINI_MODEL=a,b       model IDs to try in order
                                (default gemini-2.5-flash,gemini-2.5-flash-lite,gemini-2.0-flash)
  python run.py --port 9000     another port
"""
import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("FinEdvise needs Python 3.9 or newer.")

from finedvise.envfile import load_env_file  # noqa: E402

load_env_file(Path(__file__).resolve().parent / ".env")

from finedvise.server import main  # noqa: E402

if __name__ == "__main__":
    main()
