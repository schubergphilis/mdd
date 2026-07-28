"""Tests for ``mdd.confluence.version.check_version_drift`` (spec S27)."""

from __future__ import annotations

import pytest

from mdd.confluence.version import VersionDriftError, check_version_drift, format_message


class TestCheckVersionDrift:
    def test_raises_when_remote_ahead(self) -> None:
        with pytest.raises(VersionDriftError) as excinfo:
            check_version_drift(local_version=3, remote_version=5)
        assert excinfo.value.local_version == 3
        assert excinfo.value.remote_version == 5

    def test_noop_when_versions_match(self) -> None:
        # Must NOT raise — equal versions are fine; the user has the
        # latest copy already.
        check_version_drift(local_version=4, remote_version=4)

    def test_noop_when_local_ahead(self) -> None:
        # Local somehow ahead of remote (e.g. a sync that hasn't run yet)
        # is not a drift the helper rejects — caller decides what to do.
        check_version_drift(local_version=5, remote_version=4)

    def test_noop_when_local_version_missing(self) -> None:
        # Treating ``None`` as a no-op lets callers do their own
        # "missing local version" error message before getting here.
        check_version_drift(local_version=None, remote_version=99)


class TestVersionDriftError:
    def test_message_mentions_both_versions(self) -> None:
        exc = VersionDriftError(local_version=2, remote_version=7)
        msg = str(exc)
        assert "2" in msg
        assert "7" in msg
        assert "remote version 7" in msg
        assert "local version 2" in msg

    def test_format_message_matches_legacy_update_page_wording(self) -> None:
        # The wording is the same one update_page printed before the
        # helper was extracted; keep it stable so user-facing output
        # doesn't drift between releases.
        msg = format_message(local_version=2, remote_version=7)
        assert "Conflict: remote version 7 is newer than local version 2" in msg
        assert "Re-export the page" in msg
