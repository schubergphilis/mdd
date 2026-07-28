"""Browse-URL plumbing for mirror backends (spec S44).

A mirror's *browse* URL — the page a human opens to read a mirrored file — is
provider knowledge, exactly like the clone URL. The host is deployment
specific, and the path shape differs per forge (GitLab
``/-/blob/<branch>/<path>``, GitHub ``/blob/<branch>/<path>``). Backends
therefore answer :meth:`~mdd.mirror.protocol.MirrorBackend.web_url`, and this
module holds the generic git plumbing they share so an implementation is one
call.

Nothing here carries a default host: a backend that cannot name its own host
has no business claiming a remote is its own.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

# The two blob-path conventions we know of. GitLab (and Gitea's `/src/branch/`
# aside, most self-hosted forges) puts `/-/` before `blob`; GitHub does not.
GITLAB_BLOB_INFIX = "/-/blob/"
GITHUB_BLOB_INFIX = "/blob/"

_SSH_URL_RE = re.compile(r"^git@([^:]+):(.+?)(?:\.git)?$")


def clone_url_to_web(remote_url: str, *, allowed_host: str) -> str | None:
    """Convert a git clone URL to a web base URL.

    Handles:
    - ``git@host:path/repo.git`` → ``https://host/path/repo``
    - ``https://host/path/repo.git`` → ``https://host/path/repo``
    - ``https://host/path/repo`` → ``https://host/path/repo``

    Returns ``None`` if the remote host does not match *allowed_host*
    (case-insensitive) — the caller's mirror lives somewhere else, so no URL
    can be claimed for it.
    """
    url = remote_url.strip()

    # SSH form: git@host:path/repo(.git)?
    ssh_match = _SSH_URL_RE.match(url)
    if ssh_match:
        host = ssh_match.group(1).lower()
        if host != allowed_host.lower():
            return None
        path = ssh_match.group(2)
        return f"https://{host}/{path}"

    # HTTPS form
    if url.startswith(("https://", "http://")):
        parsed = urlsplit(url)
        if (parsed.hostname or "").lower() != allowed_host.lower():
            return None
        return url.removesuffix(".git")

    return None


def _git_out(cwd: Path, *args: str) -> str | None:
    """Return stripped stdout of ``git <args>`` run in *cwd*, or ``None`` on any failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(cwd),
        )
    except FileNotFoundError, subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_blob_url(
    path: Path, *, allowed_host: str, blob_infix: str = GITLAB_BLOB_INFIX
) -> str | None:
    """Return the browse URL for *path* inside its git work-tree, or ``None``.

    Reads ``origin`` from the work-tree containing *path* and converts it:

    ``git@gitlab.example.com:mdd/confluence/SPACE.git`` + ``Page.md``
    →
    ``https://gitlab.example.com/mdd/confluence/SPACE/-/blob/<branch>/Page.md``

    Returns ``None`` if anything fails — *path* is not in a git repo, there is
    no ``origin``, or ``origin`` is not on *allowed_host*. Callers treat that
    as "no link available" rather than an error.
    """
    cwd = path.parent
    remote_url = _git_out(cwd, "remote", "get-url", "origin")
    toplevel = _git_out(cwd, "rev-parse", "--show-toplevel")
    if not remote_url or not toplevel:
        return None

    web_base = clone_url_to_web(remote_url, allowed_host=allowed_host)
    if web_base is None:
        return None

    try:
        rel_path = path.resolve().relative_to(Path(toplevel).resolve())
    except ValueError:
        return None

    # Detached HEAD (or a git that cannot answer) falls back to 'main'.
    branch = _git_out(cwd, "symbolic-ref", "--short", "HEAD") or "main"

    # Percent-encode each path/branch segment so spaces and other URL-unsafe
    # characters in page titles produce a link that browsers and the forge
    # resolve. quote() with an empty safe set encodes "/" too, so segments are
    # encoded individually and rejoined with literal "/" separators.
    rel_str = "/".join(quote(part, safe="") for part in rel_path.parts)
    return f"{web_base}{blob_infix}{quote(branch, safe='')}/{rel_str}"
