"""Which local files a push may upload as page attachments.

Only files inside the page's own ``<stem>-attachments/`` folder are upload
sources. Anything a page body references elsewhere in the mirror (another
page's markdown, another page's attachments, local configuration, a
hand-placed image beside the ``.md``) is skipped with a warning, whatever
part of the Confluence storage the reference came from.
"""

from __future__ import annotations

import sys
import types
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.attachments import sync_attachments_for_update
from mdd.confluence.ir import parse_confluence_storage
from mdd.confluence.mermaid import render_mermaid_fences
from mdd.converters.protocol import ConvertResult
from mdd.markdown.ir import render_markdown

if TYPE_CHECKING:
    from pathlib import Path

_LOGGER = "mdd.confluence.attachments.update"

# Confluence storage whose markdown export references a file outside the
# page's attachments folder.
_OUT_OF_SCOPE_STORAGE: dict[str, str] = {
    "img src to sibling page markdown": '<p>x <img src="Sibling/Secret.md"/></p>',
    "image attachment in sibling attachments folder": (
        '<p><ac:image><ri:attachment ri:filename="Sibling-attachments/secret.pdf"/></ac:image></p>'
    ),
    "attachment link to local configuration": (
        "<p><ac:link>"
        '<ri:attachment ri:filename="configs/confluence.yaml"/>'
        "<ac:plain-text-link-body><![CDATA[t]]></ac:plain-text-link-body>"
        "</ac:link></p>"
    ),
    "image inside raw inline html": "<p>See <sub>![x](Sibling/Secret.md)</sub></p>",
    "image syntax in a macro title parameter": (
        '<ac:structured-macro ac:name="expand">'
        '<ac:parameter ac:name="title">t ![x](Sibling/Secret.md)</ac:parameter>'
        "<ac:rich-text-body><p>b</p></ac:rich-text-body>"
        "</ac:structured-macro>"
    ),
    "image alt text with an escaped bracket": (
        '<p><img src="https://x/a.png" alt="](Sibling/Secret.md) ![y"/></p>'
    ),
}


def _make_client() -> MagicMock:
    client = MagicMock()
    client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}
    return client


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    """A mirror directory holding the page ``Page.md`` and its neighbours."""
    _write(tmp_path / "Page.md", b"# Page\n")
    _write(tmp_path / "Page-attachments" / "ok.png", b"\x89PNG ok")
    _write(tmp_path / "Sibling.md", b"# Sibling\n")
    _write(tmp_path / "Sibling" / "Secret.md", b"restricted page body")
    _write(tmp_path / "Sibling-attachments" / "secret.pdf", b"%PDF restricted")
    _write(tmp_path / "configs" / "confluence.yaml", b"api_token: literal")
    _write(tmp_path / "beside.png", b"\x89PNG beside")
    return tmp_path


def _sync(client: MagicMock, body_md: str, mirror: Path) -> list[str]:
    manifest, _ = sync_attachments_for_update(
        client,
        "123",
        body_md,
        mirror,
        [],
        attachments_dir=mirror / "Page-attachments",
    )
    return [e.filename for e in manifest]


class TestOutOfScopeReferencesAreNotUploaded:
    @pytest.mark.parametrize(
        "storage", list(_OUT_OF_SCOPE_STORAGE.values()), ids=list(_OUT_OF_SCOPE_STORAGE)
    )
    def test_exported_reference_is_not_uploaded(
        self, mirror: Path, storage: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        body_md = render_markdown(parse_confluence_storage(storage))
        client = _make_client()

        with caplog.at_level("WARNING", logger=_LOGGER):
            filenames = _sync(client, body_md, mirror)

        client.upload_attachment.assert_not_called()
        assert filenames == []
        assert "skipping attachment reference" in caplog.text
        assert "Page-attachments/" in caplog.text

    @pytest.mark.parametrize(
        "src",
        [
            "Sibling.md",
            "Sibling/Secret.md",
            "Sibling-attachments/secret.pdf",
            "configs/confluence.yaml",
            "beside.png",
            "Page-attachments/../beside.png",
        ],
    )
    def test_path_outside_attachments_folder_is_skipped(
        self, mirror: Path, src: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _make_client()

        with caplog.at_level("WARNING", logger=_LOGGER):
            filenames = _sync(client, f"![x]({src})", mirror)

        client.upload_attachment.assert_not_called()
        assert filenames == []
        assert repr(src) in caplog.text
        assert "move the file into Page-attachments/" in caplog.text

    @pytest.mark.parametrize(
        "src", [".", "Page-attachments", "Page-attachments/", "sub", "confluence-attachment:sub"]
    )
    def test_directory_reference_is_skipped_and_sync_continues(
        self, mirror: Path, src: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        (mirror / "Page-attachments" / "sub").mkdir()
        client = _make_client()

        with caplog.at_level("WARNING", logger=_LOGGER):
            filenames = _sync(client, f"![d]({src})\n\n![x](ok.png)", mirror)

        client.upload_attachment.assert_called_once_with(
            "123", (mirror / "Page-attachments" / "ok.png").resolve()
        )
        assert filenames == ["ok.png"]
        assert any(r.levelname == "WARNING" for r in caplog.records)

    def test_attachment_link_outside_folder_is_skipped(self, mirror: Path) -> None:
        client = _make_client()

        _sync(client, "[cfg](confluence-attachment:configs/confluence.yaml)", mirror)

        client.upload_attachment.assert_not_called()

    def test_symlinked_attachments_folder_is_not_followed(self, tmp_path: Path) -> None:
        elsewhere = tmp_path / "elsewhere"
        _write(elsewhere / "ok.png", b"\x89PNG elsewhere")
        page_dir = tmp_path / "space"
        page_dir.mkdir()
        (page_dir / "Page-attachments").symlink_to(elsewhere, target_is_directory=True)
        client = _make_client()

        _sync(client, "![x](ok.png)", page_dir)

        client.upload_attachment.assert_not_called()

    def test_symlink_inside_folder_pointing_out_is_skipped(self, mirror: Path) -> None:
        link = mirror / "Page-attachments" / "link.png"
        link.symlink_to(mirror / "beside.png")
        client = _make_client()

        _sync(client, "![x](link.png)", mirror)

        client.upload_attachment.assert_not_called()


class TestInScopeReferencesStillUpload:
    def test_bare_name_resolves_in_attachments_folder(self, mirror: Path) -> None:
        client = _make_client()

        filenames = _sync(client, "![x](ok.png)", mirror)

        client.upload_attachment.assert_called_once_with(
            "123", (mirror / "Page-attachments" / "ok.png").resolve()
        )
        assert filenames == ["ok.png"]

    def test_attachments_folder_prefixed_path_uploads(self, mirror: Path) -> None:
        """The ``<stem>-attachments/x.png`` form the office converters write."""
        client = _make_client()

        filenames = _sync(client, "![x](Page-attachments/ok.png)", mirror)

        client.upload_attachment.assert_called_once()
        assert filenames == ["ok.png"]

    def test_confluence_attachment_uri_uploads(self, mirror: Path) -> None:
        client = _make_client()

        filenames = _sync(client, "![x](confluence-attachment:ok.png)", mirror)

        client.upload_attachment.assert_called_once()
        assert filenames == ["ok.png"]

    def test_mixed_body_uploads_only_the_in_scope_file(self, mirror: Path) -> None:
        client = _make_client()

        filenames = _sync(client, "![a](ok.png)\n\n![b](Sibling/Secret.md)\n", mirror)

        client.upload_attachment.assert_called_once()
        assert filenames == ["ok.png"]

    def test_mermaid_output_uploads(self, tmp_path: Path) -> None:
        md_path = tmp_path / "My Page.md"
        _write(md_path, b"")
        module = types.ModuleType("mermaidx")

        def render(source: str, backend: str | None = None, **_: Any) -> Any:  # pyright: ignore[reportUnusedParameter]
            diagram = MagicMock()
            diagram.svg.return_value = '<svg xmlns="http://www.w3.org/2000/svg"/>'
            return diagram

        module.render = render  # pyright: ignore[reportAttributeAccessIssue]

        def fake_convert(src: Path) -> ConvertResult:
            png = _write(src.with_name(src.name + ".png"), b"\x89PNG")
            return ConvertResult(output_path=png, attachments_dir=None, metadata={}, warnings=[])

        converter = MagicMock()
        converter.convert.side_effect = fake_convert
        client = _make_client()
        with (
            patch.dict(sys.modules, {"mermaidx": module}),
            patch(
                "mdd.confluence.attachments.svg_publish.SvgToPngConverter",
                return_value=converter,
            ),
        ):
            body_md = render_mermaid_fences("```mermaid\ngraph TD\n  A --> B\n```\n", md_path)
            manifest, _ = sync_attachments_for_update(
                client,
                "123",
                body_md,
                tmp_path,
                [],
                attachments_dir=tmp_path / "My Page-attachments",
            )

        uploaded = sorted(c.args[1].name for c in client.upload_attachment.call_args_list)
        assert len(uploaded) == 2
        assert uploaded[0].startswith("mermaid-")
        assert uploaded[0].endswith(".svg")
        assert uploaded[1] == uploaded[0] + ".png"
        assert len(manifest) == 2
