"""Fixtures for the headless model suite (no Tk, no display).

`model` is an AppModel over the synthetic placeholder doc; `loaded`/`scanned` build one over a
real in-memory PDF (text pages → Normal, image pages → Scanned). `run_job` drives a BatchJob to
completion exactly as ui/app_window would, so batch commands are testable synchronously.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Callable

import fitz
import pytest
from helpers import text_image
from PIL import Image

from core.batch import BatchResult
from core.enums import PagesMode
from core.model import AppModel


def _text_pdf(path: Path, pages: int) -> str:
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((90, 120), f"Page {i + 1}: lorem ipsum dolor sit amet", fontsize=18)
        for ln in range(8):
            pg.insert_text((90, 160 + ln * 18), "consectetur adipiscing elit sed do", fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


def _scanned_pdf(path: Path, pages: int, w: int = 160, h: int = 210) -> str:
    doc = fitz.open()
    for j in range(pages):
        arr = text_image(w=w * 3, h=h * 3, lines=12, noise=4.0, seed=10 + j)
        buf = io.BytesIO()
        Image.fromarray(arr).convert("RGB").save(buf, format="PNG")
        pg = doc.new_page(width=w, height=h)
        pg.insert_image(pg.rect, stream=buf.getvalue())
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def model() -> AppModel:
    return AppModel()


@pytest.fixture
def text_pdf(tmp_path: Path) -> Callable[..., str]:
    def make(pages: int = 5, name: str = "doc.pdf") -> str:
        return _text_pdf(tmp_path / name, pages)
    return make


@pytest.fixture
def loaded(text_pdf: Callable[..., str]) -> Callable[..., AppModel]:
    def make(pages: int = 5) -> AppModel:
        m = AppModel()
        m.load_files([text_pdf(pages)])
        return m
    return make


@pytest.fixture
def scanned(tmp_path: Path) -> Callable[..., AppModel]:
    def make(pages: int = 2) -> AppModel:
        m = AppModel()
        m.load_files([_scanned_pdf(tmp_path / "scan.pdf", pages)])
        return m
    return make


@pytest.fixture
def select() -> Callable[[AppModel, str], None]:
    """Switch to the Selected page-scope and set its pattern (the two-step UI flow, §11)."""
    def _sel(model: AppModel, pattern: str) -> None:
        model.set_pages_mode(PagesMode.SELECT)
        model.set_select_pattern(pattern)
    return _sel


@pytest.fixture
def run_job() -> Callable[..., BatchResult]:
    def run(job: object) -> BatchResult:
        while not job.is_finished():    # type: ignore[attr-defined]
            job.step()                  # type: ignore[attr-defined]
        return job.result()             # type: ignore[attr-defined,no-any-return]
    return run
