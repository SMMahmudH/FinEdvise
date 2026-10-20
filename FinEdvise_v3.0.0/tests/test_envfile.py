"""The .env reader used by run.py, the evidence runner and the key check."""
import os
import tempfile
import unittest
from pathlib import Path

from finedvise.envfile import load_env_file


class EnvFile(unittest.TestCase):
    def test_reads_keys_skips_comments_and_keeps_shell_values(self):
        path = Path(tempfile.mkdtemp()) / ".env"
        # Windows Notepad may add a byte-order mark; quotes and blank values are common too
        path.write_text('﻿FINEDVISE_T_KEY="abc"\n# comment\nFINEDVISE_T_EMPTY=\nFINEDVISE_T_SHELL=file\n', encoding="utf-8")
        os.environ["FINEDVISE_T_SHELL"] = "shell"
        try:
            load_env_file(path)
            self.assertEqual(os.environ.get("FINEDVISE_T_KEY"), "abc")
            self.assertNotIn("FINEDVISE_T_EMPTY", os.environ)
            self.assertEqual(os.environ["FINEDVISE_T_SHELL"], "shell")
        finally:
            for key in ("FINEDVISE_T_KEY", "FINEDVISE_T_SHELL"):
                os.environ.pop(key, None)

    def test_missing_file_is_fine(self):
        load_env_file(Path(tempfile.mkdtemp()) / "nope.env")


if __name__ == "__main__":
    unittest.main()
