"""Tests for mdd.converters.registry."""

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mdd.converters.registry import (
    CONVERTERS,
    converter_for,
    register,
)

if TYPE_CHECKING:
    from mdd.converters.protocol import Converter, ConvertResult

# ---------------------------------------------------------------------------
# Minimal stub converter for testing registration behaviour
# ---------------------------------------------------------------------------


class _StubConverter:
    """Minimal Converter implementation for testing the registry."""

    extensions: tuple[str, ...] = (".stub",)
    output_suffix: str = ".md"

    def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult:
        raise NotImplementedError


class _AnotherStubConverter:
    """Second stub for testing duplicate-registration error."""

    extensions: tuple[str, ...] = (".stub",)  # same as _StubConverter
    output_suffix: str = ".md"

    def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuiltinRegistrations:
    """The built-in converters are registered when the package is imported."""

    def test_docx_registered(self) -> None:
        assert ".docx" in CONVERTERS

    def test_pptx_registered(self) -> None:
        assert ".pptx" in CONVERTERS

    def test_pdf_registered(self) -> None:
        assert ".pdf" in CONVERTERS


class TestConverterFor:
    def test_exact_extension_lookup(self) -> None:
        path = Path("document.docx")
        result = converter_for(path)
        assert result is not None

    def test_case_insensitive_lookup(self) -> None:
        upper = converter_for(Path("deck.PPTX"))
        lower = converter_for(Path("deck.pptx"))
        assert upper is not None
        assert lower is not None
        assert upper is lower

    def test_mixed_case_extension(self) -> None:
        result = converter_for(Path("report.Docx"))
        assert result is not None

    def test_miss_returns_none(self) -> None:
        result = converter_for(Path("archive.zip"))
        assert result is None

    def test_no_extension_returns_none(self) -> None:
        result = converter_for(Path("README"))
        assert result is None

    def test_unknown_extension_returns_none(self) -> None:
        result = converter_for(Path("spreadsheet.xlsx"))
        assert result is None


class TestRegisterErrors:
    def test_double_registration_raises(self) -> None:
        stub: Converter = _StubConverter()
        duplicate: Converter = _AnotherStubConverter()

        # Register the first time — should succeed
        register(stub)
        try:
            # Attempt to register the same extension again — must raise
            with pytest.raises(ValueError, match=".stub"):  # noqa: RUF043
                register(duplicate)
        finally:
            # Clean up so we don't pollute other tests
            CONVERTERS.pop(".stub", None)

    def test_register_new_extension_succeeds(self) -> None:
        class _UniqueConverter:
            extensions: tuple[str, ...] = (".uniquetest",)
            output_suffix: str = ".md"

            def convert(self, src: Path, *, dest: Path | None = None) -> ConvertResult:
                raise NotImplementedError

        conv: Converter = _UniqueConverter()
        register(conv)
        try:
            assert converter_for(Path("file.uniquetest")) is conv
        finally:
            CONVERTERS.pop(".uniquetest", None)
