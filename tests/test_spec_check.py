"""Tests for scripts/spec-check.py link validation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import ModuleType

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "spec-check.py"


def _load_spec_check() -> ModuleType:
    spec = importlib.util.spec_from_file_location("spec_check", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["spec_check"] = module
    spec.loader.exec_module(module)
    return module


_module = _load_spec_check()

link_violations: Callable[[Path, int, str, set[str], set[str]], list[str]] = _module.link_violations  # pyright: ignore[reportAny]
core_spec_names: Callable[[tuple[Path, ...]], set[str]] = _module.core_spec_names  # pyright: ignore[reportAny]
collect_violations: Callable[[Path, set[str], set[str]], list[str]] = _module.collect_violations  # pyright: ignore[reportAny]

SIBLINGS = {"S07-data-protection.md"}
CORE = {"S07-data-protection.md", "S14-confluence-sync.md"}


def _check(line: str) -> list[str]:
    return link_violations(Path("S99-x.md"), 3, line, SIBLINGS, CORE)


def test_valid_sibling_link_passes() -> None:
    assert _check("See [data protection](S07-data-protection.md).") == []
    assert _check("See [data protection](./S07-data-protection.md).") == []


def test_broken_sibling_link_reported() -> None:
    violations = _check("See [gone](S42-gone.md).")
    assert len(violations) == 1
    assert "broken sibling link → S42-gone.md" in violations[0]


def test_valid_core_url_passes() -> None:
    url = "https://github.com/schubergphilis/mdd/blob/main/docs/spec/S14-confluence-sync.md"
    assert _check(f"See [confluence sync]({url}).") == []


def test_core_url_ref_is_not_pinned_to_main() -> None:
    base = "https://github.com/schubergphilis/mdd/blob"
    for ref in ("v0.3.0", "9f1c2ab", "release/0.4"):
        url = f"{base}/{ref}/docs/spec/S14-confluence-sync.md"
        assert _check(f"See [{ref}]({url}).") == [], ref


def test_broken_core_url_reported() -> None:
    url = "https://github.com/schubergphilis/mdd/blob/main/docs/spec/S99-typo.md"
    violations = _check(f"See [typo]({url}).")
    assert len(violations) == 1
    assert "broken core spec link → S99-typo.md" in violations[0]


def test_bare_core_url_is_validated_too() -> None:
    url = "https://github.com/schubergphilis/mdd/blob/main/docs/spec/S99-typo.md"
    assert len(_check(url)) == 1


def test_urls_to_other_repos_are_ignored() -> None:
    assert (
        _check("[wrapper](https://github.com/lsimons/mdd-wrapper/blob/main/docs/spec/S99-x.md)")
        == []
    )


def test_core_names_union_over_reachable_checkouts(tmp_path: Path) -> None:
    local = tmp_path / "docs" / "spec"
    sibling = tmp_path / "core" / "docs" / "spec"
    local.mkdir(parents=True)
    sibling.mkdir(parents=True)
    _ = (local / "S44-open-source-split.md").write_text("", encoding="utf-8")
    _ = (sibling / "S14-confluence-sync.md").write_text("", encoding="utf-8")

    names = core_spec_names((local, sibling, tmp_path / "absent"))

    assert names == {"S44-open-source-split.md", "S14-confluence-sync.md"}


def test_links_inside_code_fences_are_skipped(tmp_path: Path) -> None:
    spec = tmp_path / "S99-x.md"
    _ = spec.write_text(
        "**Status:** Draft\n\n"
        "```markdown\n"
        "[gone](S42-gone.md)\n"
        "[typo](https://github.com/schubergphilis/mdd/blob/main/docs/spec/S99-typo.md)\n"
        "```\n",
        encoding="utf-8",
    )

    assert collect_violations(spec, SIBLINGS, CORE) == []
