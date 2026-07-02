"""Repo-root conftest: put the project root on sys.path for the test suite."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
