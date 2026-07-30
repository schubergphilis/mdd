"""Entity-handling regression tests for ``mdd.confluence.ir.reader``.

HTML5 entities (``&rsquo;``, ``&mdash;``, ``&hellip;`` …) inside XML
attribute values must survive the lxml round-trip as Unicode characters
rather than being silently dropped by ``recover=True``. The five
XML-predefined entities continue to pass through inside tags so lxml decodes
them natively.

Companion to the element-text coverage in
``tests/ir/test_origin_preservation.py``.
"""

from __future__ import annotations

import warnings

from mdd.confluence.ir import parse_confluence_storage
from mdd.ir.nodes import ConfluenceLink, Paragraph


def _first_link(storage: str) -> ConfluenceLink:
    doc = parse_confluence_storage(storage)
    p = doc.children[0]
    assert isinstance(p, Paragraph)
    link = p.inlines[0]
    assert isinstance(link, ConfluenceLink)
    return link


class TestAttributeEntityPreservation:
    """``ri:content-title="X&rsquo;s page"`` — entity survives as ``'``."""

    def test_rsquo_in_content_title(self) -> None:
        storage = '<p><ac:link><ri:page ri:content-title="Test&rsquo;s page" /></ac:link></p>'
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            link = _first_link(storage)
        assert link.target_kind == "page"
        assert "’" in link.target, f"expected U+2019 in {link.target!r}"
        assert link.target == "Test’s page"

    def test_mdash_in_content_title(self) -> None:
        storage = '<p><ac:link><ri:page ri:content-title="A&mdash;B" /></ac:link></p>'
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            link = _first_link(storage)
        assert link.target == "A—B"

    def test_hellip_in_content_title(self) -> None:
        storage = '<p><ac:link><ri:page ri:content-title="More&hellip;" /></ac:link></p>'
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            link = _first_link(storage)
        assert link.target == "More…"

    def test_nbsp_in_content_title(self) -> None:
        storage = '<p><ac:link><ri:page ri:content-title="A&nbsp;B" /></ac:link></p>'
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            link = _first_link(storage)
        assert link.target == "A B"

    def test_xml_predefined_entity_in_attribute_still_works(self) -> None:
        # The five XML-predefined entities pass through inside tags so lxml
        # decodes them natively during attribute parsing.
        storage = '<p><ac:link><ri:page ri:content-title="A &amp; B" /></ac:link></p>'
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            link = _first_link(storage)
        assert link.target == "A & B"


class TestElementTextEntityStillWorks:
    """Regression: element-text entity decoding must not regress."""

    def test_hellip_in_element_text(self) -> None:
        doc = parse_confluence_storage("<p>wait&hellip;for it</p>")
        p = doc.children[0]
        assert isinstance(p, Paragraph)
        from mdd.ir.nodes import Text

        text_content = "".join(t.content for t in p.inlines if isinstance(t, Text))
        assert "…" in text_content
