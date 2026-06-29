"""Mechanical boundary guard (ARCHITECTURE §7): every core/ module must be Tk-free — no import
of tkinter, customtkinter or ui. Walked via ast, so importing the module is not required."""
from __future__ import annotations

import ast
import pathlib

import pytest

CORE = pathlib.Path(__file__).parent.parent / "core"
FORBIDDEN = {"tkinter", "customtkinter", "ui"}


def _imported_top_levels(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            tops.add(node.module.split(".")[0])
    return tops


@pytest.mark.parametrize("path", sorted(CORE.glob("*.py")), ids=lambda p: p.name)
def test_core_module_is_tk_free(path):
    leaked = _imported_top_levels(path) & FORBIDDEN
    assert not leaked, f"{path.name} imports forbidden module(s): {leaked}"


def test_core_has_no_self_app_import():
    # the deleted mixin god-object (core.app) must not reappear anywhere in core/
    for path in CORE.glob("*.py"):
        assert "core.app" not in path.read_text(encoding="utf-8"), path.name
