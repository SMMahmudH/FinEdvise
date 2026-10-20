import tempfile
from pathlib import Path

from finedvise.data import load_catalogue, load_school
from finedvise.store import Sandbox


def school():
    return load_school()


def catalogue():
    return load_catalogue()


def sandbox():
    return Sandbox(Path(tempfile.mkdtemp(prefix="finedvise-test-")))
