"""Strip export header and insert MDD footer in Confluence round-trip (spec S09 + 017).

Spec S17 adds a body callout that links the published office attachment.
The callout uses the same strip-then-insert pattern as the MDD footer.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlsplit

from mdd.utils.logging import get_logger

log = get_logger(__name__)

_DEFAULT_MIRROR_HOST = "gitlab.example.com"
_SSH_URL_RE = re.compile(r"^git@([^:]+):(.+?)(?:\.git)?$")

# ---------------------------------------------------------------------------
# Export header strip
# ---------------------------------------------------------------------------

# Matches a blockquote block that starts with **Confluence export**
# The blockquote is a run of lines starting with "> " or ">"
# We match it at the very beginning of the body (after optional leading blank lines).
_EXPORT_HEADER_RE = re.compile(
    r"^([ \t]*\n)*"  # optional leading blank lines
    r"((?:>(?:[^\n]*)?\n)+)"  # one or more blockquote lines
    r"\n?",  # optional trailing blank line
    re.MULTILINE,
)


def strip_export_header(body_md: str) -> str:
    """Remove the leading Confluence export callout blockquote.

    The rule:
    - Find the first blockquote at the start of the body (after any blank lines).
    - If its first non-blank quoted line starts with ``**Confluence export**``,
      drop the entire blockquote and the immediately-following blank line.
    - If no such block is present, return unchanged.
    """
    m = _EXPORT_HEADER_RE.match(body_md)
    if m is None:
        return body_md

    block = m.group(2)  # the blockquote itself

    # Check first non-blank line of the blockquote
    first_line = ""
    for raw_line in block.splitlines():
        line = raw_line.lstrip()
        if line.startswith(">"):
            # Strip leading > and optional space
            content = line[1:].lstrip()
            if content:
                first_line = content
                break

    if not first_line.startswith("**Confluence export**"):
        return body_md

    # Drop the matched block (leading blanks + blockquote + trailing blank)
    return body_md[m.end() :]


# ---------------------------------------------------------------------------
# Export-title H1 strip
# ---------------------------------------------------------------------------

# Matches the leading ATX H1 line (allows trailing whitespace, optional closing #s),
# plus any blank lines before and one blank line after.
_TITLE_H1_RE = re.compile(
    r"^([ \t]*\n)*"  # optional leading blank lines
    r"#[ \t]+(?P<title>[^\n]*?)[ \t]*#*[ \t]*\n"  # the H1 line itself
    r"([ \t]*\n)?",  # optional trailing blank line
)


def strip_export_title_h1(body_md: str, title: str) -> str:
    """Remove a leading ATX H1 whose text equals ``title``.

    The export side prepends ``# {title}`` so the markdown file is self-contained
    (the page title is metadata in Confluence, not part of the storage XHTML).
    On update we strip that leading H1 — re-emitting it would duplicate the title.

    If the first non-blank block is not an H1, or its text does not match
    ``title`` (after whitespace stripping), the body is returned unchanged.
    Empty ``title`` is treated as a no-op.
    """
    if not title:
        return body_md

    m = _TITLE_H1_RE.match(body_md)
    if m is None:
        return body_md

    if m.group("title").strip() != title.strip():
        return body_md

    return body_md[m.end() :]


# ---------------------------------------------------------------------------
# MDD footer insert/replace
# ---------------------------------------------------------------------------

_FOOTER_PATTERN = re.compile(
    r"<p><sub><em>MDD markdown version of this page at .*?</em></sub></p>",
    re.DOTALL,
)


def _build_footer(gitlab_url: str) -> str:
    escaped = gitlab_url.replace("&", "&amp;").replace('"', "&quot;")
    return (
        f"<p><sub><em>MDD markdown version of this page at "
        f'<a href="{escaped}">{escaped}</a></em></sub></p>'
    )


def insert_mdd_footer(body_xhtml: str, gitlab_url: str | None) -> str:
    """Insert or replace the MDD footer in storage XHTML.

    If ``gitlab_url`` is ``None``, emit a warning to stderr and return ``body_xhtml``
    unchanged.

    The footer is idempotent: if a prior footer matching
    ``MDD markdown version of this page at`` is present, it is replaced; otherwise
    the footer is appended.
    """
    if gitlab_url is None:
        log.warning("no GitLab remote detected; MDD footer will not be inserted.")
        return body_xhtml

    footer = _build_footer(gitlab_url)

    if _FOOTER_PATTERN.search(body_xhtml):
        return _FOOTER_PATTERN.sub(footer, body_xhtml)

    return body_xhtml + "\n" + footer


# ---------------------------------------------------------------------------
# GitLab URL computation
# ---------------------------------------------------------------------------


def get_gitlab_url(md_path: Path, *, allowed_host: str = _DEFAULT_MIRROR_HOST) -> str | None:  # noqa: PLR0911
    """Compute the GitLab web URL for a markdown file in a Git repository.

    Converts the clone URL to a web URL and appends the relative path:

    ``git@gitlab.example.com:mdd/confluence/SPACE.git``
    →
    ``https://gitlab.example.com/mdd/confluence/SPACE/-/blob/<branch>/<relpath>``

    Returns ``None`` if anything fails (not in a git repo, no remote, wrong host,
    etc.).
    """
    try:
        remote_result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(md_path.parent),
        )
    except FileNotFoundError, subprocess.TimeoutExpired:
        return None

    if remote_result.returncode != 0:
        return None

    remote_url = remote_result.stdout.strip()

    try:
        toplevel_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(md_path.parent),
        )
    except FileNotFoundError, subprocess.TimeoutExpired:
        return None

    if toplevel_result.returncode != 0:
        return None

    repo_root = Path(toplevel_result.stdout.strip())

    try:
        rel_path = md_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None

    # Convert clone URL to web URL — rejects non-allowed hosts
    web_base = clone_url_to_web(remote_url, allowed_host=allowed_host)
    if web_base is None:
        return None

    # Resolve the current branch; fall back to 'main' for detached HEAD
    branch = "main"
    try:
        branch_result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(md_path.parent),
        )
        if branch_result.returncode == 0:
            detected = branch_result.stdout.strip()
            if detected:
                branch = detected
    except FileNotFoundError, subprocess.TimeoutExpired:
        pass  # keep fallback 'main'

    # Percent-encode each path/branch segment so spaces and other URL-unsafe
    # characters in page titles produce a link that browsers and GitLab resolve.
    # quote() with an empty safe set encodes "/" too, so segments are encoded
    # individually and rejoined with literal "/" separators.
    rel_str = "/".join(quote(part, safe="") for part in rel_path.parts)
    branch_str = quote(branch, safe="")
    return f"{web_base}/-/blob/{branch_str}/{rel_str}"


def clone_url_to_web(remote_url: str, *, allowed_host: str = _DEFAULT_MIRROR_HOST) -> str | None:
    """Convert a git clone URL to a web base URL.

    Handles:
    - ``git@host:path/repo.git`` → ``https://host/path/repo``
    - ``https://host/path/repo.git`` → ``https://host/path/repo``
    - ``https://host/path/repo`` → ``https://host/path/repo``

    Returns ``None`` if the remote host does not match *allowed_host*
    (case-insensitive).
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


# ---------------------------------------------------------------------------
# Office-attachment callout (spec S17)
# ---------------------------------------------------------------------------

# Matches the callout paragraph inserted by spec S17, plus an optional following newline.
# The sentinel string "(this attachment is generated from the markdown source)"
# is how we identify our own callout vs any user-written paragraph.
_OFFICE_CALLOUT_PATTERN = re.compile(
    r"<p><sub><em>Download as .*?\(this attachment is generated from the markdown source\)"
    r".*?</em></sub></p>\n?",
    re.DOTALL,
)

_CALLOUT_SENTINEL = "(this attachment is generated from the markdown source)"


def _build_office_callout(links: list[tuple[str, str]]) -> str:
    """Build the office-attachment callout paragraph.

    Args:
        links: List of (url, filename) pairs — one per published format.

    Returns:
        A ``<p><sub><em>…</em></sub></p>`` string.
    """
    parts: list[str] = []
    for url, filename in links:
        safe_url = url.replace("&", "&amp;").replace('"', "&quot;")
        safe_name = filename.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(f'<a href="{safe_url}">{safe_name}</a>')
    downloads = ", ".join(parts)
    return f"<p><sub><em>Download as {downloads} {_CALLOUT_SENTINEL}</em></sub></p>"


def strip_office_callout(body_xhtml: str) -> str:
    """Remove the office-attachment callout from storage XHTML.

    Idempotent: if no callout is present, returns *body_xhtml* unchanged.
    """
    return _OFFICE_CALLOUT_PATTERN.sub("", body_xhtml)


def insert_office_callout(body_xhtml: str, links: list[tuple[str, str]]) -> str:
    """Insert or replace the office-attachment callout in storage XHTML.

    The callout is placed at the very beginning of the body (before all other
    content).  If a prior callout is present (matched by the sentinel string),
    it is replaced; otherwise the callout is prepended.

    Args:
        body_xhtml: Current Confluence storage XHTML.
        links: List of (url, filename) pairs — one per published format.

    Returns:
        Updated storage XHTML.
    """
    callout = _build_office_callout(links)

    if _OFFICE_CALLOUT_PATTERN.search(body_xhtml):
        return _OFFICE_CALLOUT_PATTERN.sub(callout, body_xhtml)

    return callout + "\n" + body_xhtml
