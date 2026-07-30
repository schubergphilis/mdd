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
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit

# The two blob-path conventions we know of. GitLab (and Gitea's `/src/branch/`
# aside, most self-hosted forges) puts `/-/` before `blob`; GitHub does not.
GITLAB_BLOB_INFIX = "/-/blob/"
GITHUB_BLOB_INFIX = "/blob/"

_SSH_URL_RE = re.compile(r"^git@([^:]+):(.+)$")


@dataclass(frozen=True)
class CloneUrlParts:
    """A git clone URL taken apart, host-agnostically.

    ``host`` is the lower-cased hostname without any port; ``port`` carries
    the port when the URL had one (never for the ``git@host:path`` form,
    which cannot express one). ``path`` is the repository path with any
    leading slash and ``.git`` suffix removed, and ``namespace`` / ``repo``
    are that path split at the last ``/`` — ``namespace`` is the owner or
    group path and is empty for a repo sitting at the root.
    """

    host: str
    path: str
    namespace: str
    repo: str
    port: int | None = None


def split_clone_url(remote_url: str) -> CloneUrlParts | None:
    """Split a git clone URL into its components, or ``None`` if unrecognised.

    Handles the two forms git remotes are written in practice:

    - ``git@host:namespace/repo.git`` (scp-like)
    - ``https://host/namespace/repo.git`` (and ``http://``, and without the
      ``.git`` suffix)

    ``ssh://git@host:22/namespace/repo.git`` is deliberately not recognised;
    no caller has needed it and guessing at the browse host for an explicit
    ssh port would be wrong.

    Backends use this to answer questions the browse URL cannot: whether a
    work-tree's remote is theirs (``guard_remote``), and what owner and repo
    name to build a forge API path from.
    """
    url = remote_url.strip()

    ssh_match = _SSH_URL_RE.match(url)
    if ssh_match:
        return _parts(ssh_match.group(1), ssh_match.group(2), None)

    if url.startswith(("https://", "http://")):
        parsed = urlsplit(url)
        if not parsed.hostname:
            return None
        return _parts(parsed.hostname, parsed.path, parsed.port)

    return None


def _parts(host: str, raw_path: str, port: int | None) -> CloneUrlParts | None:
    path = raw_path.strip("/").removesuffix(".git")
    if not path:
        return None
    namespace, _, repo = path.rpartition("/")
    return CloneUrlParts(host=host.lower(), path=path, namespace=namespace, repo=repo, port=port)


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
    parts = split_clone_url(remote_url)
    if parts is None or parts.host != allowed_host.strip().lower():
        return None
    port = f":{parts.port}" if parts.port else ""
    return f"https://{parts.host}{port}/{parts.path}"


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
