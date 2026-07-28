"""Tests for mdd.markdown.ir.confluence_uris — synthetic URI round-trip."""

from __future__ import annotations

from mdd.ir.document import Document
from mdd.ir.nodes import ConfluenceImage, ConfluenceLink, Paragraph
from mdd.markdown.ir import parse_markdown, render_markdown
from mdd.markdown.ir.confluence_uris import (
    parse_confluence_image_uri,
    parse_confluence_link_uri,
    parse_confluence_uri,
    render_confluence_uri,
)

# ---------------------------------------------------------------------------
# parse_confluence_uri
# ---------------------------------------------------------------------------


class TestParseConfluenceUri:
    def test_page_simple(self) -> None:
        # ``confluence-page:<Space>/<Title>`` is the markdown-first convenience
        # form; the parser hoists ``<Space>`` into ``space_key``.
        node = parse_confluence_uri("confluence-page:MDD/Home")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "page"
        assert node.target == "Home"
        assert node.space_key == "MDD"

    def test_page_with_anchor_suffix(self) -> None:
        node = parse_confluence_uri("confluence-page:MDD/Home#intro")
        assert isinstance(node, ConfluenceLink)
        assert node.target == "Home"
        assert node.space_key == "MDD"
        assert node.attributes.get("ac:anchor") == "intro"

    def test_page_no_space_prefix(self) -> None:
        node = parse_confluence_uri("confluence-page:Home")
        assert isinstance(node, ConfluenceLink)
        assert node.target == "Home"
        assert not node.space_key

    def test_page_with_extras(self) -> None:
        node = parse_confluence_uri("confluence-page:Home;space-key=MDD;anchor=intro")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "page"
        assert node.target == "Home"
        assert node.space_key == "MDD"
        assert node.attributes.get("ac:anchor") == "intro"

    def test_attachment_link(self) -> None:
        # confluence-attachment: as a link target → ConfluenceLink(attachment).
        node = parse_confluence_link_uri("confluence-attachment:file.pdf")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "attachment"
        assert node.target == "file.pdf"

    def test_blogpost(self) -> None:
        node = parse_confluence_uri("confluence-blogpost:MDD/My%20Post")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "blogpost"
        assert node.target == "My Post"
        assert node.space_key == "MDD"

    def test_user(self) -> None:
        node = parse_confluence_uri("confluence-user:abc123")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "user"
        assert node.target == "abc123"

    def test_anchor(self) -> None:
        node = parse_confluence_uri("confluence-anchor:section1")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "anchor"
        assert node.target == "section1"

    def test_shortcut(self) -> None:
        node = parse_confluence_uri("confluence-shortcut:MDD/Target")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "shortcut"
        assert node.target == "MDD/Target"

    def test_attachment_image(self) -> None:
        # Generic parse_confluence_uri for confluence-attachment returns ConfluenceImage.
        # For link context use parse_confluence_link_uri; for image use parse_confluence_image_uri.
        node = parse_confluence_uri("confluence-attachment:diagram.png")
        assert isinstance(node, ConfluenceImage)
        assert node.source_kind == "attachment"
        assert node.source == "diagram.png"

    def test_attachment_as_link(self) -> None:
        # Context-specific: link context → ConfluenceLink.
        node = parse_confluence_link_uri("confluence-attachment:diagram.png")
        assert isinstance(node, ConfluenceLink)
        assert node.target_kind == "attachment"

    def test_attachment_as_image(self) -> None:
        # Context-specific: image context → ConfluenceImage.
        node = parse_confluence_image_uri("confluence-attachment:diagram.png")
        assert isinstance(node, ConfluenceImage)
        assert node.source_kind == "attachment"

    def test_image_url(self) -> None:
        node = parse_confluence_uri("confluence-image-url:https://example.com/img.png")
        assert isinstance(node, ConfluenceImage)
        assert node.source_kind == "url"
        assert node.source == "https://example.com/img.png"

    def test_returns_none_for_regular_uri(self) -> None:
        assert parse_confluence_uri("https://example.com") is None

    def test_returns_none_for_no_scheme(self) -> None:
        assert parse_confluence_uri("just-a-string") is None

    def test_returns_none_for_empty(self) -> None:
        assert parse_confluence_uri("") is None


# ---------------------------------------------------------------------------
# render_confluence_uri
# ---------------------------------------------------------------------------


class TestRenderConfluenceUri:
    def test_link_page(self) -> None:
        node = ConfluenceLink(
            target_kind="page",
            target="Home",
            space_key="MDD",
        )
        uri = render_confluence_uri(node)
        assert uri.startswith("confluence-page:")
        assert "Home" in uri
        assert "space-key=MDD" in uri

    def test_link_url_passthrough(self) -> None:
        node = ConfluenceLink(
            target_kind="url",
            target="https://example.com",
        )
        uri = render_confluence_uri(node)
        assert uri == "https://example.com"

    def test_link_user(self) -> None:
        node = ConfluenceLink(target_kind="user", target="abc123")
        uri = render_confluence_uri(node)
        assert uri == "confluence-user:abc123"

    def test_image_attachment(self) -> None:
        node = ConfluenceImage(source_kind="attachment", source="file.png")
        uri = render_confluence_uri(node)
        assert uri == "confluence-attachment:file.png"

    def test_image_url(self) -> None:
        node = ConfluenceImage(source_kind="url", source="https://example.com/img.png")
        uri = render_confluence_uri(node)
        assert uri.startswith("confluence-image-url:")


# ---------------------------------------------------------------------------
# Focused round-trip test from the spec
# ---------------------------------------------------------------------------


def test_confluence_link_roundtrips_through_markdown() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="page",
                        target="Home",
                        space_key="MDD",
                        attributes={"ac:anchor": "intro"},
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    link = parsed.children[0].inlines[0]  # type: ignore[union-attr]
    assert isinstance(link, ConfluenceLink)
    assert link.target_kind == "page"
    assert link.target == "Home"
    assert link.space_key == "MDD"
    assert link.attributes.get("ac:anchor") == "intro"


def test_confluence_attachment_image_roundtrips() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceImage(
                        source_kind="attachment",
                        source="diagram.png",
                        attributes={"ac:width": "400", "ac:align": "center"},
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    assert "confluence-attachment:diagram.png" in md
    parsed = parse_markdown(md)
    img = parsed.children[0].inlines[0]  # type: ignore[union-attr]
    assert isinstance(img, ConfluenceImage)
    assert img.source_kind == "attachment"
    assert img.source == "diagram.png"
    assert img.attributes.get("ac:width") == "400"
    assert img.attributes.get("ac:align") == "center"


def test_confluence_link_blogpost_roundtrips() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="blogpost",
                        target="My Post",
                        space_key="MDD",
                        body_tokens=[],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    link = parsed.children[0].inlines[0]  # type: ignore[union-attr]
    assert isinstance(link, ConfluenceLink)
    assert link.target_kind == "blogpost"
    assert link.target == "My Post"


def test_confluence_image_url_roundtrips() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[ConfluenceImage(source_kind="url", source="https://example.com/img.png")]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    img = parsed.children[0].inlines[0]  # type: ignore[union-attr]
    assert isinstance(img, ConfluenceImage)
    assert img.source_kind == "url"
    assert img.source == "https://example.com/img.png"


def test_bare_user_mention_roundtrips_without_link_body() -> None:
    """Bare ``<ri:user>`` (no ``<ac:link-body>``) must survive the markdown leg.

    The storage writer emits ``<ac:link-body>`` whenever ``body_tokens`` is
    non-empty. If the markdown writer fills in the account id as link text,
    the markdown reader returns a populated ``body_tokens`` and a spurious
    ``<ac:link-body>`` ends up in the round-tripped storage. See issue #85.
    """
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="user",
                        target="557058:abc-def",
                        body_tokens=[],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    link = parsed.children[0].inlines[0]  # type: ignore[union-attr]
    assert isinstance(link, ConfluenceLink)
    assert link.target_kind == "user"
    assert link.target == "557058:abc-def"
    assert link.body_tokens == [], (
        "bare user mention must round-trip with empty body_tokens "
        "so the storage writer does not inject <ac:link-body>"
    )


def test_user_mention_with_display_name_preserves_link_body() -> None:
    """A user mention with a real display name must keep its ``body_tokens``."""
    from mdd.ir.nodes import Text

    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="user",
                        target="557058:abc-def",
                        body_tokens=[Text("Leo Simons")],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    link = parsed.children[0].inlines[0]  # type: ignore[union-attr]
    assert isinstance(link, ConfluenceLink)
    assert link.target == "557058:abc-def"
    body = link.body_tokens
    assert len(body) == 1
    assert isinstance(body[0], Text)
    assert body[0].content == "Leo Simons"


def test_confluence_link_with_spaces_in_target() -> None:
    """Targets with spaces survive percent-encoding round-trip."""
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="page",
                        target="My Page Title",
                        body_tokens=[],
                    )
                ]
            )
        ]
    )
    md = render_markdown(doc)
    parsed = parse_markdown(md)
    link = parsed.children[0].inlines[0]  # type: ignore[union-attr]
    assert isinstance(link, ConfluenceLink)
    assert link.target == "My Page Title"
