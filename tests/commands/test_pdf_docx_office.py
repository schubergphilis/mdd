"""Office-bound tests for `mdd pdf-docx` — drive Word via AppleScript.

Builds a tiny .docx with python-docx and asks ``export_docx_to_pdf``
to drive Word via AppleScript. Only runs via ``mise run test-office``
(or ``test-all``) on macOS with Microsoft Word installed and granted
Automation permission for the running terminal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mdd.commands.pdf_docx import export_docx_to_pdf, run_docx_pipeline

pytestmark = pytest.mark.office


def _minimal_docx(path: Path) -> Path:
    from docx import Document  # pyright: ignore[reportMissingModuleSource]

    doc: Any = Document()  # pyright: ignore[reportAny]
    doc.add_paragraph("Office round-trip smoke")
    doc.save(str(path))
    return path


def test_export_single_docx_to_pdf(tmp_path: Path) -> None:
    src = _minimal_docx(tmp_path / "letter.docx")
    assert export_docx_to_pdf(src) is True
    pdf = Path(str(src) + ".pdf")
    assert pdf.exists()
    assert pdf.stat().st_size > 0
    assert pdf.read_bytes()[:4] == b"%PDF"


def test_pipeline_skips_up_to_date_pdf(tmp_path: Path) -> None:
    src = _minimal_docx(tmp_path / "letter.docx")
    assert run_docx_pipeline(tmp_path) == 0
    pdf = Path(str(src) + ".pdf")
    mtime1 = pdf.stat().st_mtime
    assert run_docx_pipeline(tmp_path) == 0
    assert pdf.stat().st_mtime == mtime1
