"""Shared fixtures. The sample PDF is built once per session into tests/assets/."""
from __future__ import annotations

import fitz
import pytest
from helpers import ASSETS, make_sample_pdf


@pytest.fixture(scope="session")
def sample_pdf_path():
    path = ASSETS / "sample.pdf"
    make_sample_pdf(path)
    return path


@pytest.fixture(scope="session")
def sample_doc(sample_pdf_path):
    doc = fitz.open(str(sample_pdf_path))
    yield doc
    doc.close()
