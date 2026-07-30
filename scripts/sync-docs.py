"""sync-docs: copy docs/**.md into site/src/content/docs/, adding the
Starlight frontmatter the source files do not carry, and rewriting
repo-relative links so they resolve on the built site (or on GitHub, for
files the site does not publish).

Source -> destination mapping:

    docs/guide/NN-slug.md        -> site/src/content/docs/guide/slug.md
    docs/articles/*.md           -> site/src/content/docs/articles/*.md
    docs/reference/**/*.md       -> site/src/content/docs/reference/**/*.md
    docs/spec/*.md                -> site/src/content/docs/spec/*.md
    docs/research/*.md            -> site/src/content/docs/research/*.md
    docs/design-record/*.md       -> site/src/content/docs/design-record/*.md
    <repo-root governance file>  -> site/src/content/docs/get-involved/<name>.md

A source file named `index.md` publishes at its section's own root slug
(`docs/design-record/index.md` -> `/mdd/design-record/`) instead of a
`.../index/` segment. The get-involved section is not a directory glob: its
sources are the fixed list in `GET_INVOLVED_FILES`, read from the repository
root and left there — synced, not moved. `LICENSE` in that list is plain
text, not Markdown; it is wrapped in a fenced block rather than parsed.

Each destination directory is deleted before it is repopulated, so a file
removed from `docs/` does not linger in the synced output. `docs/reference/`
and `docs/articles/` may not exist yet; an absent or empty source directory
is not an error.

Frontmatter is derived per file: `title` from the first level-1 heading
(which is then removed from the body, since Starlight renders `title` as the
page's own heading), and `description` from the `**Purpose:**` line (spec
files) or the first paragraph of body text (everything else). Guide pages
get a `sidebar.order` from their filename's numeric prefix. Spec and
research pages are demoted: `pagefind: false`, a `sidebar.label` that is
just the document's id (`S06`, `R14`, `000`), and a `banner` marking them as
a design record rather than user documentation. Every page also gets an
`editUrl` pointing at its real source file — the synced path Starlight sees
is not that file (a numeric prefix is stripped, or the file lives at the
repository root rather than under `docs/`), so only this script can supply
a working "edit this page" link.

Every relative link is resolved against the linking file's directory. A
link to a file this script publishes becomes a site-absolute URL; a link to
a file that exists but is not published (README.md, source code, tests, ...)
becomes a GitHub blob URL; a link to a file that does not exist anywhere is
reported to stderr and makes the run fail. Absolute URLs, `mailto:` links and
bare `#fragment` links are left alone. Links inside fenced or indented code
blocks, and inside inline code spans, are never rewritten.

For every synced page that is not part of the demoted design record, a raw
Markdown twin — the same link-rewritten body, without frontmatter, with its
heading restored — is written to `site/public/<slug>.md`, so the deployed
site can serve a page's Markdown directly to a client that fetches it.

Run with no arguments: `uv run python scripts/sync-docs.py`.
"""

from __future__ import annotations

import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

GITHUB_BLOB_BASE = "https://github.com/schubergphilis/mdd/blob/main"
# Deliberately a separate constant from GITHUB_BLOB_BASE, not derived from
# it: "blob" (used for links out to non-published files) and "edit" (used
# for each page's own editUrl) are different GitHub paths, and conflating
# them would be a subtle bug the next person to touch this would not expect.
GITHUB_EDIT_BASE = "https://github.com/schubergphilis/mdd/edit/main"
SITE_BASE = "/mdd"

DEMOTED_KINDS = {"spec", "research"}
# Pages that carry a `sidebar.order`. Guide pages derive it from a filename
# prefix; get-involved pages get it from their fixed position in
# GET_INVOLVED_FILES. Either way, `build_sidebar` just reads `page.order`.
NUMBERED_KINDS = {"guide", "get-involved"}
ID_LABEL_KINDS = {"spec", "research"}

GET_INVOLVED_FILES: tuple[tuple[str, str, int], ...] = (
    ("CONTRIBUTING.md", "contributing", 1),
    ("CODE_OF_CONDUCT.md", "code-of-conduct", 2),
    ("SECURITY.md", "security", 3),
    ("LICENSE", "license", 4),
)

# The new-spec scaffold, not a spec itself. Its `[NNN-<dep>](<dep>.md)` line
# is a placeholder for a future author to fill in, not a real link, so it is
# excluded rather than published or treated as a broken link.
EXCLUDED_SOURCES = frozenset({("spec", "spec-template.md")})

MAX_DESCRIPTION_LENGTH = 155

DEMOTION_BANNER = (
    "This document describes intent at the time it was written. It is part "
    "of the design record, not user documentation, and may not reflect the "
    "current behaviour of the code."
)

NUMERIC_PREFIX_RE = re.compile(r"^(\d+)-(.+)$")
DOC_ID_RE = re.compile(r"^([A-Za-z]*\d+)")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)
H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$")
PURPOSE_RE = re.compile(r"^\*\*Purpose:\*\*\s*(.+)$", re.MULTILINE)
INLINE_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
REF_DEF_RE = re.compile(r"^(\s{0,3}\[[^\]]+\]:\s*)(\S+)(.*)$")
FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})")
LIST_MARKER_RE = re.compile(r"^([-*+]|\d+[.)])\s")
CODE_SPAN_RE = re.compile(r"(`+)((?:(?!\1).)+?)\1", re.DOTALL)
INLINE_LINK_TEXT_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3})(?!\s)(.+?)(?<!\s)\1")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


@dataclass(frozen=True)
class Section:
    """One source-tree -> destination-tree mapping."""

    kind: str
    source: Path
    dest: Path
    recursive: bool


@dataclass(frozen=True)
class Page:
    """A single Markdown file discovered under one `Section`."""

    kind: str
    source: Path
    slug: str
    dest: Path
    twin: Path | None
    order: int | None
    doc_id: str | None


@dataclass(frozen=True)
class RenderResult:
    """The rendered output for one `Page`, plus any violations found in it."""

    content: str
    twin: str | None
    violations: list[str]


def build_sections(docs_dir: Path, content_dir: Path) -> tuple[Section, ...]:
    return (
        Section("guide", docs_dir / "guide", content_dir / "guide", recursive=False),
        Section("articles", docs_dir / "articles", content_dir / "articles", recursive=False),
        Section("reference", docs_dir / "reference", content_dir / "reference", recursive=True),
        Section("spec", docs_dir / "spec", content_dir / "spec", recursive=False),
        Section("research", docs_dir / "research", content_dir / "research", recursive=False),
        Section(
            "design-record",
            docs_dir / "design-record",
            content_dir / "design-record",
            recursive=False,
        ),
    )


@dataclass(frozen=True)
class NamedFileSection:
    """A section whose sources are an explicit, ordered list of files at
    fixed repository paths, rather than a directory glob — governance
    documents that live at the repository root and stay there.
    """

    kind: str
    dest: Path
    files: tuple[tuple[Path, str, int], ...]  # (source, slug name, sidebar order)


def build_named_file_sections(repo_root: Path, content_dir: Path) -> tuple[NamedFileSection, ...]:
    return (
        NamedFileSection(
            "get-involved",
            content_dir / "get-involved",
            tuple(
                (repo_root / filename, name, order) for filename, name, order in GET_INVOLVED_FILES
            ),
        ),
    )


def _clean_destination(kind: str, dest: Path, public_dir: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    if kind not in DEMOTED_KINDS:
        twin_dir = public_dir / kind
        if twin_dir.exists():
            shutil.rmtree(twin_dir)


def clean_destinations(
    sections: tuple[Section, ...],
    named_sections: tuple[NamedFileSection, ...],
    public_dir: Path,
) -> None:
    for section in sections:
        _clean_destination(section.kind, section.dest, public_dir)
    for named_section in named_sections:
        _clean_destination(named_section.kind, named_section.dest, public_dir)


def strip_numeric_prefix(name: str) -> tuple[str, int | None]:
    match = NUMERIC_PREFIX_RE.match(name)
    if match is None:
        return name, None
    return match.group(2), int(match.group(1))


def derive_doc_id(stem: str) -> str | None:
    match = DOC_ID_RE.match(stem)
    return match.group(1) if match else None


def build_page(section: Section, path: Path, public_dir: Path) -> Page:
    rel_no_ext = path.relative_to(section.source).with_suffix("")
    parts = list(rel_no_ext.parts)
    order: int | None = None
    if section.kind in NUMBERED_KINDS:
        parts[-1], order = strip_numeric_prefix(parts[-1])
    rel_stem = Path(*parts)
    dest = section.dest / rel_stem.with_suffix(".md")

    # `index.md` is the section's own root page, not a page named "index"
    # nested under it, so the emitted URL drops the filename rather than
    # adding a literal `.../index/` segment. This applies at any depth (a
    # future `docs/reference/cli/index.md` gets the same treatment), and the
    # destination filename above is untouched — Starlight derives a root
    # page from a file named `index.md`, so only the URL we emit needs this.
    is_index = parts[-1].lower() == "index"
    slug_parts = parts[:-1] if is_index else parts
    # Starlight lowercases the slug it derives from a filename, so a page
    # written as `S07-data-protection.md` is served at `.../s07-data-protection/`.
    # URLs built here must match, or every link to a spec or research note is a
    # 404. The destination filename keeps its original case.
    url_stem = "/".join(part.lower() for part in slug_parts)
    slug = f"{section.kind}/{url_stem}" if url_stem else section.kind

    twin = None
    if section.kind not in DEMOTED_KINDS:
        if is_index:
            twin_rel = f"{url_stem}/index.md" if url_stem else "index.md"
        else:
            twin_rel = f"{url_stem}.md"
        twin = public_dir / section.kind / twin_rel
    doc_id = derive_doc_id(path.stem) if section.kind in ID_LABEL_KINDS else None
    return Page(section.kind, path, slug, dest, twin, order, doc_id)


def discover_named_file_section(section: NamedFileSection, public_dir: Path) -> list[Page]:
    pages: list[Page] = []
    for source, name, order in section.files:
        if not source.is_file():
            continue
        slug = f"{section.kind}/{name}"
        dest = section.dest / f"{name}.md"
        twin = None
        if section.kind not in DEMOTED_KINDS:
            twin = public_dir / section.kind / f"{name}.md"
        pages.append(Page(section.kind, source, slug, dest, twin, order, None))
    return pages


def discover_section(section: Section, public_dir: Path) -> list[Page]:
    if not section.source.is_dir():
        return []
    pattern = "**/*.md" if section.recursive else "*.md"
    return [
        build_page(section, path, public_dir)
        for path in sorted(section.source.glob(pattern))
        if (section.kind, path.name) not in EXCLUDED_SOURCES
    ]


def discover_pages(
    sections: tuple[Section, ...],
    named_sections: tuple[NamedFileSection, ...],
    public_dir: Path,
) -> list[Page]:
    pages: list[Page] = []
    for section in sections:
        pages.extend(discover_section(section, public_dir))
    for named_section in named_sections:
        pages.extend(discover_named_file_section(named_section, public_dir))
    return pages


def strip_inline_markdown(text: str) -> str:
    text = INLINE_LINK_TEXT_RE.sub(r"\1", text)
    text = CODE_SPAN_RE.sub(r"\2", text)
    text = EMPHASIS_RE.sub(r"\2", text)
    return text.strip()


def truncate_at_sentence(text: str, limit: int = MAX_DESCRIPTION_LENGTH) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    boundary = max(truncated.rfind(". "), truncated.rfind("! "), truncated.rfind("? "))
    if boundary > 0:
        return truncated[: boundary + 1].strip()
    last_space = truncated.rfind(" ")
    head = truncated[:last_space] if last_space > 0 else truncated
    return head.rstrip() + "…"


def extract_purpose(body: str) -> str | None:
    match = PURPOSE_RE.search(body)
    if match is None:
        return None
    return strip_inline_markdown(match.group(1))


def extract_first_paragraph(body: str) -> str | None:
    paragraph: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            if paragraph:
                break
            continue
        paragraph.append(stripped)
    if not paragraph:
        return None
    return strip_inline_markdown(" ".join(paragraph))


def derive_description(kind: str, body: str) -> str | None:
    text = extract_purpose(body) if kind == "spec" else None
    if text is None:
        text = extract_first_paragraph(body)
    if not text:
        return None
    return truncate_at_sentence(text)


def extract_title(body: str) -> tuple[str | None, str, int]:
    """Pull out the first level-1 heading and drop it (and a following blank
    line) from the body. Also returns how many lines were consumed, so a
    caller can keep reporting line numbers against the original file.
    """
    lines = body.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = H1_RE.match(line.strip("\n"))
        if match is None:
            return None, body, 0
        title = strip_inline_markdown(match.group(1))
        consumed = index + 1
        remainder = lines[index + 1 :]
        if remainder and not remainder[0].strip():
            remainder = remainder[1:]
            consumed += 1
        return title, "".join(remainder), consumed
    return None, body, 0


def split_frontmatter(raw: str) -> tuple[dict[str, object], str, int]:
    match = FRONTMATTER_RE.match(raw)
    if match is None:
        return {}, raw, 0
    data = yaml.safe_load(match.group(1)) or {}
    consumed = match.group(0).count("\n")
    return data, raw[match.end() :], consumed


def build_sidebar(page: Page) -> dict[str, object] | None:
    if page.kind in NUMBERED_KINDS and page.order is not None:
        return {"order": page.order}
    if page.kind in ID_LABEL_KINDS and page.doc_id is not None:
        return {"label": page.doc_id}
    return None


def build_edit_url(source: Path, repo_root: Path) -> str:
    """The GitHub "edit this page" URL for a page's real source file.

    Starlight's own `editLink.baseUrl` appends the page's path *within the
    content collection* (e.g. `guide/install.md`), not its real source (e.g.
    `docs/guide/01-install.md`) — the two differ by a numeric prefix for
    guide pages, and are unrelated paths entirely for get-involved pages,
    which live at the repository root. Only this script knows the mapping,
    so it emits a per-page `editUrl` override rather than leaving Starlight
    to guess from the synced path.
    """
    rel = source.relative_to(repo_root)
    return f"{GITHUB_EDIT_BASE}/{rel.as_posix()}"


def build_frontmatter(
    page: Page, title: str, body: str, existing: dict[str, object], edit_url: str
) -> dict[str, object]:
    derived: dict[str, object] = {"title": title}
    description = derive_description(page.kind, body)
    if description is not None:
        derived["description"] = description
    sidebar = build_sidebar(page)
    if sidebar is not None:
        derived["sidebar"] = sidebar
    if page.kind in DEMOTED_KINDS:
        derived["pagefind"] = False
        derived["banner"] = {"content": DEMOTION_BANNER}
    derived["editUrl"] = edit_url
    return {**existing, **derived}


def classify_url(url: str) -> str:
    if url.startswith("#"):
        return "fragment"
    if url.startswith("mailto:"):
        return "mailto"
    if SCHEME_RE.match(url) or url.startswith("//"):
        return "absolute"
    return "relative"


def split_url_title(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    match = re.match(r'^(\S+)(\s+".*")?$', raw)
    if match is None:
        return raw, ""
    return match.group(1), match.group(2) or ""


def rewrite_url(
    url: str, source: Path, lineno: int, site_paths: dict[Path, str], repo_root: Path
) -> tuple[str, str | None]:
    if classify_url(url) != "relative":
        return url, None
    path_part, _, fragment = url.partition("#")
    fragment_suffix = f"#{fragment}" if fragment else ""
    if not path_part:
        return url, None
    resolved = (source.parent / path_part).resolve()
    slug = site_paths.get(resolved)
    if slug is not None:
        return f"{SITE_BASE}/{slug}/{fragment_suffix}", None
    if resolved.exists():
        try:
            rel = resolved.relative_to(repo_root)
        except ValueError:
            return url, f"{source}:{lineno}: link escapes the repository: {url}"
        return f"{GITHUB_BLOB_BASE}/{rel.as_posix()}{fragment_suffix}", None
    return url, f"{source}:{lineno}: broken link: {url}"


def mask_code_spans(content: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def stash(match: re.Match[str]) -> str:
        spans.append(match.group(0))
        return f"{len(spans) - 1}"

    return CODE_SPAN_RE.sub(stash, content), spans


def unmask_code_spans(content: str, spans: list[str]) -> str:
    for index, original in enumerate(spans):
        content = content.replace(f"{index}", original)
    return content


def _rewrite_reference_definitions(
    text: str, source: Path, start_line: int, site_paths: dict[Path, str], repo_root: Path
) -> tuple[str, list[str]]:
    """Reference-style definitions (`[label]: url`) are anchored to one
    physical line each, unlike inline links, so these are rewritten per line
    before the block is treated as a single unit for the rest.
    """
    violations: list[str] = []
    rewritten: list[str] = []
    for offset, line in enumerate(text.splitlines(keepends=True)):
        content = line.splitlines()[0] if line.splitlines() else ""
        match = REF_DEF_RE.match(content)
        if match is None:
            rewritten.append(line)
            continue
        prefix, url, rest = match.groups()
        new_url, violation = rewrite_url(url, source, start_line + offset, site_paths, repo_root)
        if violation:
            violations.append(violation)
        rewritten.append(line.replace(content, f"{prefix}{new_url}{rest}", 1))
    return "".join(rewritten), violations


def rewrite_block(
    text: str, source: Path, start_line: int, site_paths: dict[Path, str], repo_root: Path
) -> tuple[str, list[str]]:
    """Rewrite every link in one contiguous run of non-code lines, treated as
    a single unit so a link that wraps across a line break is still caught —
    processing line by line would silently pass a wrapped link straight
    through, unrewritten and unreported.
    """
    text, violations = _rewrite_reference_definitions(
        text, source, start_line, site_paths, repo_root
    )
    masked, spans = mask_code_spans(text)

    def replace(match: re.Match[str]) -> str:
        link_text, raw_url = match.group(1), match.group(2)
        url, title = split_url_title(raw_url)
        match_line = start_line + masked.count("\n", 0, match.start())
        new_url, violation = rewrite_url(url, source, match_line, site_paths, repo_root)
        if violation:
            violations.append(violation)
        return f"[{link_text}]({new_url}{title})"

    rewritten = INLINE_LINK_RE.sub(replace, masked)
    return unmask_code_spans(rewritten, spans), violations


def _fence_close(line: str, fence_char: str, fence_len: int) -> bool:
    pattern = rf"^\s{{0,3}}{re.escape(fence_char)}{{{fence_len},}}\s*$"
    return re.match(pattern, line) is not None


def _fence_open(content: str) -> re.Match[str] | None:
    """Match a genuine opening code fence, as distinct from a run of
    backticks used as an inline code-span delimiter in running prose (for
    example, four backticks wrapping literal text that itself contains
    triple backticks). CommonMark's rule: a backtick fence's info string may
    not itself contain a backtick, since that would be ambiguous with a code
    span; a tilde fence has no such restriction.
    """
    match = FENCE_RE.match(content)
    if match is None:
        return None
    if match.group(2)[0] == "`" and "`" in content[match.end() :]:
        return None
    return match


@dataclass
class _FenceState:
    char: str = ""
    length: int = 0


def _classify_line(content: str, fence: _FenceState, list_active: bool) -> tuple[bool, bool]:
    """Return (is_passthrough, new_list_active) for one physical line.

    A passthrough line — fenced code, a fence delimiter, an indented code
    line, or blank — is emitted unchanged and never joins a link-rewriting
    block. Everything else is prose and gets grouped into a block by the
    caller.
    """
    if fence.char:
        if _fence_close(content, fence.char, fence.length):
            fence.char, fence.length = "", 0
        return True, list_active
    fence_match = _fence_open(content)
    if fence_match is not None:
        fence.char, fence.length = fence_match.group(2)[0], len(fence_match.group(2))
        return True, list_active
    if not content.strip():
        return True, list_active
    stripped = content.lstrip(" ")
    indent = len(content) - len(stripped)
    if LIST_MARKER_RE.match(stripped) and indent <= 3:
        list_active = True
    elif indent < 4:
        list_active = False
    return indent >= 4 and not list_active, list_active


def rewrite_links_in_body(
    body: str, source: Path, site_paths: dict[Path, str], repo_root: Path, start_line: int = 1
) -> tuple[str, list[str]]:
    violations: list[str] = []
    out_parts: list[str] = []
    fence = _FenceState()
    list_active = False
    prose_lines: list[str] = []
    prose_start = start_line

    def flush_prose() -> None:
        if not prose_lines:
            return
        block_text = "".join(prose_lines)
        new_text, block_violations = rewrite_block(
            block_text, source, prose_start, site_paths, repo_root
        )
        out_parts.append(new_text)
        violations.extend(block_violations)
        prose_lines.clear()

    for lineno, line in enumerate(body.splitlines(keepends=True), start=start_line):
        content = line.splitlines()[0] if line.splitlines() else ""
        passthrough, list_active = _classify_line(content, fence, list_active)
        if passthrough:
            flush_prose()
            out_parts.append(line)
            continue
        if not prose_lines:
            prose_start = lineno
        prose_lines.append(line)

    flush_prose()
    return "".join(out_parts), violations


def render_license_page(page: Page, repo_root: Path) -> RenderResult:
    """`LICENSE` is the verbatim Apache-2.0 text, not Markdown: it has no
    heading, and letting it flow through paragraph/list handling would
    mangle its formatting. It is read here at sync time, rather than copied
    into `docs/`, so the published copy cannot drift from the file it
    mirrors. Wrapping it in a fenced block keeps it byte-for-byte; the title
    is given explicitly since there is no heading to derive one from.

    It gets a real `editUrl`, the same as every other page, rather than
    `editUrl: false`: it points at an actual file, and "edit" landing on the
    Apache text is harmless and honest.
    """
    title = "License"
    license_text = page.source.read_text(encoding="utf-8")
    body = (
        "`mdd` is licensed under the Apache License 2.0. This page mirrors the "
        f"[`LICENSE`]({GITHUB_BLOB_BASE}/LICENSE) file at the repository root.\n\n"
        f"```text\n{license_text}```\n"
    )
    edit_url = build_edit_url(page.source, repo_root)
    frontmatter = build_frontmatter(page, title, body, {}, edit_url)
    dumped = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    content = f"---\n{dumped}---\n\n{body}"
    twin = f"# {title}\n\n{body}" if page.twin is not None else None
    return RenderResult(content, twin, [])


def render_page(page: Page, site_paths: dict[Path, str], repo_root: Path) -> RenderResult:
    if page.kind == "get-involved" and page.source.name == "LICENSE":
        return render_license_page(page, repo_root)
    raw = page.source.read_text(encoding="utf-8")
    existing_fm, stripped, fm_lines = split_frontmatter(raw)
    title, body, title_lines = extract_title(stripped)
    if title is None:
        return RenderResult(
            "", None, [f"{page.source}: missing a level-1 heading to use as the title"]
        )
    start_line = fm_lines + title_lines + 1
    body, violations = rewrite_links_in_body(body, page.source, site_paths, repo_root, start_line)
    edit_url = build_edit_url(page.source, repo_root)
    frontmatter = build_frontmatter(page, title, body, existing_fm, edit_url)
    dumped = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    content = f"---\n{dumped}---\n\n{body}"
    twin = f"# {title}\n\n{body}" if page.twin is not None else None
    return RenderResult(content, twin, violations)


def write_page(page: Page, result: RenderResult) -> None:
    page.dest.parent.mkdir(parents=True, exist_ok=True)
    page.dest.write_text(result.content, encoding="utf-8")
    if page.twin is not None and result.twin is not None:
        page.twin.parent.mkdir(parents=True, exist_ok=True)
        page.twin.write_text(result.twin, encoding="utf-8")


def run(repo_root: Path) -> int:
    docs_dir = repo_root / "docs"
    content_dir = repo_root / "site" / "src" / "content" / "docs"
    public_dir = repo_root / "site" / "public"
    sections = build_sections(docs_dir, content_dir)
    named_sections = build_named_file_sections(repo_root, content_dir)
    clean_destinations(sections, named_sections, public_dir)
    pages = discover_pages(sections, named_sections, public_dir)
    site_paths = {page.source: page.slug for page in pages}
    violations: list[str] = []
    for page in pages:
        result = render_page(page, site_paths, repo_root)
        violations.extend(result.violations)
        if result.content:
            write_page(page, result)
    for violation in violations:
        print(violation, file=sys.stderr)
    return 1 if violations else 0


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    return run(repo_root)


if __name__ == "__main__":
    sys.exit(main())
