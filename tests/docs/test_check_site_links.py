"""Tests for scripts/check-site-links.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

SCRIPT = Path(__file__).resolve().parent.parent.parent / "scripts" / "check-site-links.py"


def _load_check_site_links() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_site_links", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_site_links"] = module
    spec.loader.exec_module(module)
    return module


# Keep the module reference untyped rather than rebinding its members with
# explicit annotations; ModuleType attribute access resolves to Any, and a
# hand-written annotation here would declare the wrong type.
check_site_links = _load_check_site_links()


def write_page(dist: Path, slug: str, body: str) -> None:
    path = dist / slug / "index.html" if slug else dist / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")


def test_resolving_links_are_not_reported(tmp_path: Path) -> None:
    write_page(tmp_path, "guide/install", '<a href="/mdd/guide/safety/">Safety</a>')
    write_page(tmp_path, "guide/safety", "ok")

    assert check_site_links.find_broken(tmp_path) == {}


def test_case_mismatch_against_a_lowercased_slug_is_caught(tmp_path: Path) -> None:
    """The regression this check exists for.

    Starlight serves `S07-data-protection.md` at `.../s07-data-protection/`. A
    link that keeps the filename's case points at nothing.
    """
    write_page(tmp_path, "guide/safety", '<a href="/mdd/spec/S07-data-protection/">S07</a>')
    write_page(tmp_path, "spec/s07-data-protection", "ok")

    broken = check_site_links.find_broken(tmp_path)
    assert "/mdd/spec/S07-data-protection/" in broken
    assert broken["/mdd/spec/S07-data-protection/"] == {"guide/safety/index.html"}


def test_emitted_asset_resolves(tmp_path: Path) -> None:
    """Raw Markdown twins and images are files, not pages with an index.html."""
    write_page(tmp_path, "guide/install", '<a href="/mdd/guide/install.md">Markdown</a>')
    (tmp_path / "guide" / "install.md").write_text("# Install\n", encoding="utf-8")

    assert check_site_links.find_broken(tmp_path) == {}


def test_missing_asset_is_caught(tmp_path: Path) -> None:
    write_page(tmp_path, "guide/install", '<img src="/mdd/img/missing.png">')

    assert "/mdd/img/missing.png" in check_site_links.find_broken(tmp_path)


def test_site_root_resolves(tmp_path: Path) -> None:
    write_page(tmp_path, "guide/install", '<a href="/mdd/">Home</a>')
    write_page(tmp_path, "", "home")

    assert check_site_links.find_broken(tmp_path) == {}


def test_external_and_fragment_links_are_ignored(tmp_path: Path) -> None:
    write_page(
        tmp_path,
        "guide/install",
        '<a href="https://example.com/x">ext</a>'
        '<a href="//cdn.example.com/y">proto-relative</a>'
        '<a href="mailto:someone@example.com">mail</a>'
        '<a href="#section">anchor</a>',
    )

    assert check_site_links.find_broken(tmp_path) == {}


def test_fragment_is_stripped_before_resolving(tmp_path: Path) -> None:
    write_page(tmp_path, "guide/install", '<a href="/mdd/guide/safety/#recovery">R</a>')
    write_page(tmp_path, "guide/safety", "ok")

    assert check_site_links.find_broken(tmp_path) == {}


def test_link_outside_the_deploy_base_is_caught(tmp_path: Path) -> None:
    """A root-relative link missing the base 404s on a project site."""
    write_page(tmp_path, "guide/install", '<a href="/guide/safety/">Safety</a>')
    write_page(tmp_path, "guide/safety", "ok")

    assert "/guide/safety/" in check_site_links.find_broken(tmp_path)


def test_multiple_sources_are_collected_for_one_broken_target(tmp_path: Path) -> None:
    write_page(tmp_path, "a", '<a href="/mdd/gone/">x</a>')
    write_page(tmp_path, "b", '<a href="/mdd/gone/">x</a>')

    broken = check_site_links.find_broken(tmp_path)
    assert broken["/mdd/gone/"] == {"a/index.html", "b/index.html"}


def test_main_fails_when_no_build_exists(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(check_site_links, "DIST", tmp_path / "absent")
    assert check_site_links.main() == 1
    assert "no build found" in capsys.readouterr().err
