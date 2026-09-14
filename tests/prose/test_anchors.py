"""Tests for the anchor resolver and the GitHub slugging rule."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mdd.prose.anchors import AnchorIndex, anchors_of, internal_links, run, slug
from mdd.prose.classify import Classified, classify
from mdd.prose.config import ProseConfig
from mdd.prose.rules import RULES, Severity

if TYPE_CHECKING:
    from pathlib import Path


def ok(text: str) -> Classified:
    result = classify(text)
    assert isinstance(result, Classified)
    return result


def config() -> ProseConfig:
    return ProseConfig(severities={rule.rule: rule.default for rule in RULES.values()})


def test_slug_lowercases_and_hyphenates() -> None:
    assert slug("Hello World") == "hello-world"


def test_slug_keeps_each_space_as_one_hyphen() -> None:
    assert slug("foo — bar") == "foo--bar"


def test_slug_strips_inline_markup_but_keeps_its_text() -> None:
    assert slug("`code` and *emph*") == "code-and-emph"
    assert slug("see [the docs](a/b.md)") == "see-the-docs"


def test_slug_drops_punctuation() -> None:
    assert slug("What's new? (v2)") == "whats-new-v2"


def test_collision_numbering_is_document_order() -> None:
    doc = ok("# Same\n\n## Same\n\n### Same\n")
    assert [a.slug for a in anchors_of(doc)] == ["same", "same-1", "same-2"]


def test_explicit_id_overrides_the_slug() -> None:
    doc = ok("# A heading {#custom}\n")
    assert [a.slug for a in anchors_of(doc)] == ["custom"]


def test_setext_heading_anchor() -> None:
    doc = ok("Title Here\n==========\n")
    assert [a.slug for a in anchors_of(doc)] == ["title-here"]


def test_external_links_are_not_collected() -> None:
    doc = ok("[a](https://x.test) [b](mailto:a@b.test) [c](local.md)\n")
    assert [link.target for link in internal_links(doc)] == ["local.md"]


def test_links_inside_code_blocks_are_not_collected() -> None:
    doc = ok("```\n[a](missing.md)\n```\n")
    assert internal_links(doc) == ()


def test_percent_encoded_fragment_is_decoded() -> None:
    doc = ok("[a](#a%20b)\n")
    assert internal_links(doc)[0].fragment == "a b"


def test_same_file_anchor_resolves(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text("# The Title\n\n[link](#the-title)\n", encoding="utf-8")
    assert run(target, ok(target.read_text()), config(), AnchorIndex()) == []


def test_missing_anchor_reports_a_suggestion(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    _ = target.write_text("# The Title\n\n[link](#the-titel)\n", encoding="utf-8")
    findings = run(target, ok(target.read_text()), config(), AnchorIndex())
    assert [f.rule for f in findings] == ["missing-anchor"]
    assert "did you mean 'the-title'?" in findings[0].message


def test_missing_file_is_reported(tmp_path: Path) -> None:
    source = tmp_path / "a.md"
    _ = source.write_text("[link](nope.md)\n", encoding="utf-8")
    findings = run(source, ok(source.read_text()), config(), AnchorIndex())
    assert [f.rule for f in findings] == ["missing-file"]


def test_cross_file_anchor_resolves(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    _ = (tmp_path / "sub" / "b.md").write_text("## Deep Heading\n", encoding="utf-8")
    source = tmp_path / "a.md"
    _ = source.write_text("[link](sub/b.md#deep-heading)\n", encoding="utf-8")
    assert run(source, ok(source.read_text()), config(), AnchorIndex()) == []


def test_cross_file_anchor_missing(tmp_path: Path) -> None:
    _ = (tmp_path / "b.md").write_text("## Deep Heading\n", encoding="utf-8")
    source = tmp_path / "a.md"
    _ = source.write_text("[link](b.md#shallow)\n", encoding="utf-8")
    findings = run(source, ok(source.read_text()), config(), AnchorIndex())
    assert [f.rule for f in findings] == ["missing-anchor"]
    assert "no heading in b.md" in findings[0].message


def test_link_to_a_file_without_an_anchor_only_checks_existence(tmp_path: Path) -> None:
    _ = (tmp_path / "b.md").write_text("no headings here\n", encoding="utf-8")
    source = tmp_path / "a.md"
    _ = source.write_text("[link](b.md)\n", encoding="utf-8")
    assert run(source, ok(source.read_text()), config(), AnchorIndex()) == []


def test_unparseable_target_is_not_reported(tmp_path: Path) -> None:
    _ = (tmp_path / "b.md").write_text("```\nunclosed\n", encoding="utf-8")
    source = tmp_path / "a.md"
    _ = source.write_text("[link](b.md#anything)\n", encoding="utf-8")
    assert run(source, ok(source.read_text()), config(), AnchorIndex()) == []


def test_duplicate_heading_is_an_ambiguous_anchor_warning(tmp_path: Path) -> None:
    source = tmp_path / "a.md"
    _ = source.write_text("# Same\n\n# Same\n", encoding="utf-8")
    findings = run(source, ok(source.read_text()), config(), AnchorIndex())
    assert [f.rule for f in findings] == ["ambiguous-anchor"]
    assert findings[0].severity is Severity.WARNING
    assert findings[0].line == 3


def test_index_caches_by_resolved_path(tmp_path: Path) -> None:
    target = tmp_path / "b.md"
    _ = target.write_text("# One\n", encoding="utf-8")
    index = AnchorIndex()
    first = index.anchors(target)
    _ = target.write_text("# Two\n", encoding="utf-8")
    assert index.anchors(target) == first


def test_index_returns_none_for_an_unreadable_file(tmp_path: Path) -> None:
    assert AnchorIndex().anchors(tmp_path / "absent.md") is None
