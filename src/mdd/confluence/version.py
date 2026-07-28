"""Version-drift detection between local frontmatter and Confluence (spec S27).

Both ``mdd.confluence.update.update_page`` and the S27 mutate orchestrators
(``rename-page`` / ``move-page`` / ``archive-page`` / ``unarchive-page``)
need to refuse pushing to Confluence when the remote ``version.number`` is
ahead of the local frontmatter ``version``.  The check is extracted here so
both call sites share one definition and one error message.
"""

from __future__ import annotations


class VersionDriftError(Exception):
    """Raised when the remote Confluence version is ahead of the local copy.

    Carries both numbers so callers can format their own user-facing
    message; :func:`format_message` produces the canonical wording.
    """

    def __init__(self, local_version: int, remote_version: int) -> None:
        super().__init__(format_message(local_version, remote_version))
        self.local_version = local_version
        self.remote_version = remote_version


def format_message(local_version: int, remote_version: int) -> str:
    """Canonical user-facing wording for a version-drift refusal.

    Kept identical to the message ``update_page`` printed before the helper
    was extracted, so output diffs don't change for that call site.
    """
    return (
        f"Conflict: remote version {remote_version} is newer than local version "
        f"{local_version}.\n"
        "Re-export the page to get the latest version, reconcile manually, "
        "then re-run update."
    )


def check_version_drift(
    local_version: int | None,
    remote_version: int,
) -> None:
    """Raise :class:`VersionDriftError` when the remote version is ahead.

    A ``local_version`` of ``None`` is a no-op: the caller is expected to
    have already handled "missing local version" with its own error (the
    pre-flight in ``update_page`` does this — it prints a missing-version
    message and returns 1 before getting here).  Treating ``None`` as
    "skip" keeps this helper trivially callable from the S27 mutate
    orchestrators, which may or may not have a local version depending on
    whether the user already ran a sync.
    """
    if local_version is None:
        return
    if remote_version > local_version:
        raise VersionDriftError(local_version, remote_version)
