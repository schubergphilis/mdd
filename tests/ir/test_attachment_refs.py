"""Tests for ``mdd.confluence.ir.collect_attachment_refs``."""

from __future__ import annotations

from mdd.confluence.ir import (
    AttachmentRef,
    collect_attachment_refs,
    parse_confluence_storage,
)
from mdd.ir.document import Document
from mdd.ir.nodes import (
    ConfluenceImage,
    ConfluenceLink,
    Paragraph,
    Text,
)


def test_collect_picks_up_image_attachment() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceImage(source_kind="attachment", source="foo.png"),
                ]
            )
        ]
    )
    assert collect_attachment_refs(doc) == [AttachmentRef(filename="foo.png")]


def test_collect_picks_up_link_attachment() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceLink(
                        target_kind="attachment",
                        target="brief.pdf",
                        body_tokens=[Text(content="brief")],
                    ),
                ]
            )
        ]
    )
    assert collect_attachment_refs(doc) == [AttachmentRef(filename="brief.pdf")]


def test_collect_ignores_url_sources() -> None:
    doc = Document(
        children=[
            Paragraph(
                inlines=[
                    ConfluenceImage(source_kind="url", source="https://example/x.png"),
                    ConfluenceLink(
                        target_kind="url",
                        target="https://example/",
                        body_tokens=[Text(content="x")],
                    ),
                ]
            )
        ]
    )
    assert collect_attachment_refs(doc) == []


def test_collect_from_storage_xhtml() -> None:
    storage = (
        '<ac:image xmlns:ac="http://atlassian.com/content"'
        ' xmlns:ri="http://atlassian.com/repository/confluence/1.0">'
        '<ri:attachment ri:filename="diagram.svg"/>'
        "</ac:image>"
    )
    doc = parse_confluence_storage(storage)
    assert collect_attachment_refs(doc) == [AttachmentRef(filename="diagram.svg")]
