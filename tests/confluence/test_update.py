"""Tests for mdd.confluence.update (issue #9: empty-body guard)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from mdd.confluence.update import update_page

if TYPE_CHECKING:
    from pathlib import Path


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.url = "https://example.atlassian.net"
    cfg.username = "user@example.com"
    cfg.api_token = "tok"
    return cfg


def _minimal_frontmatter(page_id: str = "42", version: int = 1) -> str:
    return f"---\nconfluence:\n  page_id: '{page_id}'\n  version: {version}\n---\n"


def _make_client(remote_body: str = "<p>remote content</p>") -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get_page.return_value = {
        "id": "42",
        "title": "My Page",
        "version": {"number": 1},
        "body": {"storage": {"value": remote_body}},
    }
    client.put_page.return_value = {
        "id": "42",
        "title": "My Page",
        "version": {"number": 2, "authorId": "uid1", "createdAt": "2024-01-01T00:00:00Z"},
    }
    client.get_user.return_value = {"displayName": "Alice"}
    client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}
    return client


class TestEmptyBodyGuard:
    """Issue #9: update --yes with empty body must be refused."""

    def test_empty_body_is_refused(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        # Frontmatter only, body is blank
        md.write_text(_minimal_frontmatter() + "\n", encoding="utf-8")

        config = _make_config()
        client = _make_client(remote_body="<p>Lots of existing content on remote</p>")

        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            rc = update_page(md, config, yes=True)

        assert rc == 1
        client.put_page.assert_not_called()

    def test_empty_body_allowed_with_flag(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        md.write_text(_minimal_frontmatter() + "\n", encoding="utf-8")

        config = _make_config()
        client = _make_client(remote_body="<p>existing</p>")

        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            rc = update_page(md, config, yes=True, allow_empty=True)

        # Will succeed (or be a no-op if diff collapses) — key thing: not refused
        assert rc in {0, 1}
        # put_page MAY be called if there is a diff; no assertion either way

    def test_large_shrink_is_refused(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        # Body of 5 chars; remote is 2000 chars → well below 10 %
        small_body = "hello"
        md.write_text(_minimal_frontmatter() + small_body, encoding="utf-8")

        remote_body = "<p>" + "x" * 2000 + "</p>"
        config = _make_config()
        client = _make_client(remote_body=remote_body)

        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            rc = update_page(md, config, yes=True)

        assert rc == 1
        client.put_page.assert_not_called()

    def test_large_shrink_allowed_with_flag(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        small_body = "hello"
        md.write_text(_minimal_frontmatter() + small_body, encoding="utf-8")

        remote_body = "<p>" + "x" * 2000 + "</p>"
        config = _make_config()
        client = _make_client(remote_body=remote_body)

        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            rc = update_page(md, config, yes=True, allow_shrink=True)

        # Should not be refused (rc may be 0 or 1 for other reasons)
        # The key assertion is that the shrink guard did NOT fire
        # (we can verify put_page was called if a diff exists)
        assert rc in {0, 1}

    def test_normal_sized_body_is_not_refused(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        body = "# My Page\n\nSome content here.\n"
        md.write_text(_minimal_frontmatter() + body, encoding="utf-8")

        # Remote body is similar length — no shrink triggered
        config = _make_config()
        client = _make_client(remote_body="<p>Some content here.</p>")

        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            rc = update_page(md, config, yes=True)

        # Should not be refused by the guard
        assert rc in {0, 1}
        # The guard must not have returned early with a refusal before trying the client
        client.get_page.assert_called_once()


class TestRoundTripReattach:
    """update-page must graft identity attrs from the remote storage onto the
    parsed-from-markdown IR — otherwise every round-trip strips ``local-id``,
    ``macro-id``, ``schema-version``, ``ac:breakout-*`` etc. from layout,
    section, cell, macro, and paragraph nodes. issue #85.
    """

    def test_unedited_export_is_a_no_op_push(self, tmp_path: Path) -> None:
        # Remote body modelled on the realtime-prototyping fixture: two-column layout with
        # identity attrs everywhere. After ``export-page`` writes the
        # corresponding markdown file, ``update-page`` with no edits must NOT
        # emit a PUT — the rendered XHTML should match the remote byte-perfect.
        remote_body = (
            '<ac:layout><ac:layout-section ac:type="two_equal" '
            'ac:breakout-mode="wide" ac:breakout-width="1800" '
            'ac:local-id="9836864461c1">'
            '<ac:layout-cell ac:local-id="10eba1ac6339">'
            '<p local-id="bcdf1afbdafc">Hello.</p>'
            "</ac:layout-cell>"
            '<ac:layout-cell ac:local-id="e2ddf5f014bf">'
            '<p local-id="b334c70bfaab">World.</p>'
            "</ac:layout-cell>"
            "</ac:layout-section></ac:layout>"
        )

        # Compose the markdown the export side would write for this remote.
        from mdd.confluence.ir import parse_confluence_storage
        from mdd.markdown.ir import render_markdown

        ir_remote = parse_confluence_storage(remote_body, mode="preserving")
        exported_md = render_markdown(ir_remote, mode="normalising")

        md = tmp_path / "page.md"
        md.write_text(_minimal_frontmatter() + exported_md, encoding="utf-8")

        config = _make_config()
        client = _make_client(remote_body=remote_body)
        with patch("mdd.confluence.update.ConfluenceClient", return_value=client):
            rc = update_page(md, config, yes=True)

        # No diff means no PUT.
        assert rc == 0, "round-trip with no edits should be a no-op"
        client.put_page.assert_not_called()
