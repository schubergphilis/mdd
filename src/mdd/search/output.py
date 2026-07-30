"""Human-readable and JSON output formatters for mdd search.

Ripgrep is invoked with ``--json``; the raw JSON lines are parsed here into
``RgMatch`` objects that are then formatted for display.

Two paths share the same parsing/grouping:

* ``StreamingFormatter`` — consumes rg JSON lines one at a time and writes
  formatted output to a stream as it goes. This is the default search path
  so users see results immediately.
* ``write_output`` / ``format_human`` / ``format_json`` — take the full rg
  output as a single string and emit bulk formatted text. Used by the
  ``--sort`` path which groups matches by file before printing.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from mdd.search.color import NO_COLOR, Color
from mdd.search.filters import frontmatter_line_range, is_frontmatter_line

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from typing import TextIO

    from mdd.search.roots import MirrorRoot


@dataclass(frozen=True)
class Submatch:
    """Character span (Python ``str`` indices) of one rg submatch on a line."""

    start: int
    end: int


@dataclass
class RgMatch:
    """A single line match returned by ripgrep in --json mode."""

    path: Path
    line_number: int
    line_text: str
    submatches: tuple[Submatch, ...] = ()
    # Populated by post-processing
    mirror: MirrorRoot | None = None
    title: str | None = None
    page_id: str | None = None


@dataclass
class FileMatches:
    """All matches within one file, with file-level metadata."""

    path: Path
    mirror: MirrorRoot | None
    title: str | None
    page_id: str | None
    matches: list[RgMatch] = field(default_factory=list)


def _decode_rg_arbitrary_data(value: Any) -> str | None:  # pyright: ignore[reportAny]
    """Decode ripgrep's ArbitraryData scalar into a string, or ``None``.

    Ripgrep's ``--json`` emits string-valued fields (``path``, ``lines.text``)
    either as a bare string or as ``{"text": <str>}`` / ``{"bytes": <b64>}``
    when the value is not valid UTF-8.  We accept the first form and the
    ``text`` / ``bytes`` keys; anything else is treated as missing.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        value_dict: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
        for key in ("text", "bytes"):
            inner: Any = value_dict.get(key)  # pyright: ignore[reportAny]
            if isinstance(inner, str):
                return inner
    return None


def _byte_to_char_offset(encoded: bytes, byte_offset: int) -> int:
    """Convert an rg byte offset to a Python ``str`` char offset.

    rg reports submatch positions in *bytes*; ``RgMatch.line_text`` is a
    decoded Python string indexed in *characters*. On lines with multibyte
    UTF-8 the two coordinate systems disagree — naive use of byte offsets
    would slice the wrong span.
    """
    if byte_offset <= 0:
        return 0
    if byte_offset >= len(encoded):
        return len(encoded.decode("utf-8", errors="replace"))
    return len(encoded[:byte_offset].decode("utf-8", errors="replace"))


def _parse_submatches(line_text: str, raw: Any) -> tuple[Submatch, ...]:  # pyright: ignore[reportAny]
    """Lift rg's ``submatches`` array into ``Submatch`` records with char offsets."""
    if not isinstance(raw, list):
        return ()
    encoded = line_text.encode("utf-8")
    out: list[Submatch] = []
    for sm in raw:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(sm, dict):
            continue
        sm_dict: dict[str, Any] = sm  # pyright: ignore[reportUnknownVariableType]
        byte_start: Any = sm_dict.get("start")  # pyright: ignore[reportAny]
        byte_end: Any = sm_dict.get("end")  # pyright: ignore[reportAny]
        if not (isinstance(byte_start, int) and isinstance(byte_end, int)):
            continue
        out.append(
            Submatch(
                start=_byte_to_char_offset(encoded, byte_start),
                end=_byte_to_char_offset(encoded, byte_end),
            )
        )
    return tuple(out)


def _parse_rg_match_record(data: dict[str, Any]) -> RgMatch | None:
    """Build an ``RgMatch`` from a ripgrep ``match.data`` dict, or ``None``."""
    path_str = _decode_rg_arbitrary_data(data.get("path"))  # pyright: ignore[reportAny]
    if path_str is None:
        return None

    line_number = data.get("line_number")  # pyright: ignore[reportAny]
    if not isinstance(line_number, int):
        return None

    line_text = _decode_rg_arbitrary_data(data.get("lines")) or ""  # pyright: ignore[reportAny]
    line_text = line_text.rstrip("\r\n")
    submatches = _parse_submatches(line_text, data.get("submatches"))  # pyright: ignore[reportAny]
    return RgMatch(
        path=Path(path_str),
        line_number=line_number,
        line_text=line_text,
        submatches=submatches,
    )


def _parse_one_rg_json_line(raw_line: str) -> RgMatch | None:
    """Parse a single rg --json line; return an ``RgMatch`` or ``None``.

    Returns ``None`` for non-match records (``type: begin``/``end``/``summary``),
    blank lines, or malformed JSON.
    """
    stripped = raw_line.strip()
    if not stripped:
        return None
    try:
        obj: Any = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    obj_dict: dict[str, Any] = obj  # pyright: ignore[reportUnknownVariableType]
    if obj_dict.get("type") != "match":  # pyright: ignore[reportAny]
        return None
    data: Any = obj_dict.get("data")  # pyright: ignore[reportAny]
    if not isinstance(data, dict):
        return None
    return _parse_rg_match_record(data)  # pyright: ignore[reportUnknownArgumentType]


def _iter_rg_match_data(output: str) -> Iterator[dict[str, Any]]:
    """Yield the ``data`` dict of each ``type: match`` record in *output*."""
    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            obj: Any = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        obj_dict: dict[str, Any] = obj  # pyright: ignore[reportUnknownVariableType]
        if obj_dict.get("type") != "match":  # pyright: ignore[reportAny]
            continue
        data: Any = obj_dict.get("data")  # pyright: ignore[reportAny]
        if isinstance(data, dict):
            yield data  # pyright: ignore[reportUnknownVariableType]


def _parse_rg_json_lines(output: str) -> list[RgMatch]:
    """Parse ripgrep ``--json`` output into a list of ``RgMatch`` objects."""
    results: list[RgMatch] = []
    for data in _iter_rg_match_data(output):
        match = _parse_rg_match_record(data)
        if match is not None:
            results.append(match)
    return results


def _read_frontmatter_block(path: Path) -> str | None:
    """Return the raw YAML text between the leading ``---`` markers, or ``None``."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            if fh.readline().rstrip("\r\n") != "---":
                return None
            lines: list[str] = []
            for _ in range(200):
                line = fh.readline()
                if not line or line.rstrip("\r\n") == "---":
                    break
                lines.append(line)
    except OSError:
        return None
    return "".join(lines)


def _parse_yaml_mapping(yaml_text: str) -> dict[str, Any] | None:
    """Parse *yaml_text* and return it if it is a mapping, else ``None``."""
    try:
        fm: Any = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    return fm  # pyright: ignore[reportUnknownVariableType]


def _extract_page_id(fm: dict[str, Any]) -> str | None:
    """Return ``page_id`` from top-level or nested under ``confluence.page_id``."""
    top: Any = fm.get("page_id")  # pyright: ignore[reportAny]
    if top is not None:
        return str(top)  # pyright: ignore[reportAny]
    conf: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if isinstance(conf, dict):
        conf_dict: dict[str, Any] = conf  # pyright: ignore[reportUnknownVariableType]
        nested: Any = conf_dict.get("page_id")  # pyright: ignore[reportAny]
        if nested is not None:
            return str(nested)  # pyright: ignore[reportAny]
    return None


def _scan_body_for_h1(lines: Iterable[str]) -> str | None:
    """Return the first ATX H1 (``# ...``) text in *lines*, skipping frontmatter."""
    iterator = iter(lines)
    first = next(iterator, None)
    if first is None:
        return None
    body_iter: Iterable[str]
    if first.rstrip("\r\n") == "---":
        body_iter = _iter_after_frontmatter(iterator)
    else:
        body_iter = _chain_one(first, iterator)
    for raw in body_iter:
        line = raw.rstrip("\r\n")
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _iter_after_frontmatter(it: Iterator[str]) -> Iterator[str]:
    """Yield lines from *it* that come after the closing ``---`` of a YAML block."""
    for raw in it:
        if raw.rstrip("\r\n") == "---":
            yield from it
            return


def _chain_one(first: str, rest: Iterator[str]) -> Iterator[str]:
    """Yield *first*, then the remaining items from *rest*."""
    yield first
    yield from rest


def _find_first_h1(path: Path) -> str | None:
    """Scan *path* for the first ATX H1 (``# ...``) in the body, or ``None``.

    Skips a leading YAML frontmatter block (``---`` … ``---``) so the H1
    must live in the body. Returns ``None`` on read errors, empty files,
    or files without an H1.

    Matches the title-derivation logic in
    ``mdd.confluence.state._derive_title`` / ``mdd.confluence.update._extract_title``:
    Confluence sync deliberately does not put ``title:`` in frontmatter and
    instead encodes the page title as the first H1 in the body.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return _scan_body_for_h1(fh)
    except OSError:
        return None


def _read_frontmatter(path: Path) -> tuple[str | None, str | None]:
    """Return (title, page_id) extracted from YAML frontmatter, or (None, None).

    When frontmatter is missing or has no ``title:`` key, falls back to the
    first ATX H1 of the body (Confluence-sync convention — see
    ``_find_first_h1``).
    """
    yaml_text = _read_frontmatter_block(path)
    if yaml_text is None:
        return _find_first_h1(path), None
    fm = _parse_yaml_mapping(yaml_text)
    if fm is None:
        return _find_first_h1(path), None
    title_raw: Any = fm.get("title")  # pyright: ignore[reportAny]
    title = str(title_raw) if title_raw is not None else _find_first_h1(path)  # pyright: ignore[reportAny]
    return title, _extract_page_id(fm)


def _find_mirror(path: Path, roots: list[MirrorRoot]) -> MirrorRoot | None:
    """Return the mirror root that contains *path*, or ``None``."""
    for root in roots:
        try:
            path.relative_to(root.path)
        except ValueError:
            continue
        return root
    return None


def _relative_display_path(path: Path, mirror: MirrorRoot | None) -> str:
    """Return a display path like ``confluence/ENGINEERING/Onboarding/New Hire.md``."""
    if mirror is not None:
        try:
            rel = path.relative_to(mirror.path)
            return f"{mirror.mirror_name}/{rel}"
        except ValueError:
            pass
    return str(path)


def _format_file_header_lines(fm: FileMatches, color: Color) -> list[str]:
    """Return the header block (display path + optional title) for one file."""
    display_path = _relative_display_path(fm.path, fm.mirror)
    header = color.path(display_path)
    if fm.page_id:
        header += "  " + color.meta(f"(page {fm.page_id})")
    lines = [header]
    if fm.title:
        lines.append(f"{color.meta('  Title:')} {fm.title}")
    return lines


_MAX_LINE_DISPLAY_LEN = 500
_ELLIPSIS = "…"


def _truncate_line(
    text: str, subs: tuple[Submatch, ...], max_len: int = _MAX_LINE_DISPLAY_LEN
) -> tuple[str, tuple[Submatch, ...]]:
    """Truncate *text* to *max_len* chars, keeping the match span roughly centered.

    Returns the (possibly truncated) text and submatches whose offsets have
    been adjusted to point into the new string. Adds ``…`` at either end
    where content was elided. No-op when the line already fits.
    """
    if len(text) <= max_len:
        return text, subs
    if not subs:
        return text[: max_len - 1] + _ELLIPSIS, ()

    span_start = subs[0].start
    span_end = subs[-1].end
    span_len = span_end - span_start

    if span_len >= max_len:
        win_start = span_start
        win_end = min(span_start + max_len, len(text))
    else:
        pad = (max_len - span_len) // 2
        win_start = max(0, span_start - pad)
        win_end = win_start + max_len
        if win_end > len(text):
            win_end = len(text)
            win_start = max(0, win_end - max_len)

    prefix = _ELLIPSIS if win_start > 0 else ""
    suffix = _ELLIPSIS if win_end < len(text) else ""
    body = text[win_start:win_end]
    new_text = prefix + body + suffix

    shift = len(prefix) - win_start
    body_lo = len(prefix)
    body_hi = body_lo + (win_end - win_start)
    new_subs: list[Submatch] = []
    for sm in subs:
        new_s = sm.start + shift
        new_e = sm.end + shift
        if new_e <= body_lo or new_s >= body_hi:
            continue
        new_subs.append(Submatch(start=max(new_s, body_lo), end=min(new_e, body_hi)))
    return new_text, tuple(new_subs)


def _highlight_match_text(text: str, subs: tuple[Submatch, ...], color: Color) -> str:
    """Wrap each submatch span in ANSI codes; pass through when color disabled."""
    if not color.enabled or not subs:
        return text
    parts: list[str] = []
    pos = 0
    for sm in subs:
        if sm.start < pos or sm.end < sm.start:
            continue  # overlapping or malformed span — skip
        parts.append(text[pos : sm.start])
        parts.append(color.match(text[sm.start : sm.end]))
        pos = sm.end
    parts.append(text[pos:])
    return "".join(parts)


def _format_match_line(match: RgMatch, color: Color) -> str:
    """Return the single ``  Lnn:  text`` line for one match."""
    label = color.line_number(f"L{match.line_number}")
    text, subs = _truncate_line(match.line_text, match.submatches)
    body = _highlight_match_text(text, subs, color)
    return f"  {label}:  {body}"


def _build_match_json_record(
    match: RgMatch,
    fm: FileMatches,
) -> dict[str, Any]:
    """Build the JSON record for one match (no serialization)."""
    display_path = _relative_display_path(match.path, fm.mirror)
    record: dict[str, Any] = {
        "path": str(match.path),
        "mirror": fm.mirror.mirror_name if fm.mirror else None,
        "line": match.line_number,
        "snippet": match.line_text,
    }
    if fm.title is not None:
        record["title"] = fm.title
    if fm.page_id is not None:
        record["page_id"] = fm.page_id
    record["display_path"] = display_path
    return record


def _group_matches(
    raw_matches: list[RgMatch],
    roots: list[MirrorRoot],
    *,
    include_frontmatter: bool,
) -> list[FileMatches]:
    """Group raw ripgrep matches by file, attach metadata, filter frontmatter."""
    file_map: dict[Path, FileMatches] = {}

    for match in raw_matches:
        abs_path = match.path
        mirror = _find_mirror(abs_path, roots)

        if abs_path not in file_map:
            title, page_id = _read_frontmatter(abs_path)
            file_map[abs_path] = FileMatches(
                path=abs_path,
                mirror=mirror,
                title=title,
                page_id=page_id,
            )

        fm_entry = file_map[abs_path]

        if not include_frontmatter:
            fm_range = frontmatter_line_range(abs_path)
            if is_frontmatter_line(match.line_number, fm_range):
                continue

        match.mirror = mirror
        match.title = fm_entry.title
        match.page_id = fm_entry.page_id
        fm_entry.matches.append(match)

    return [fm for fm in file_map.values() if fm.matches]


def _render_human_groups(groups: list[FileMatches], color: Color) -> str:
    """Render grouped matches as the human-readable format."""
    lines: list[str] = []
    for group in groups:
        lines.extend(_format_file_header_lines(group, color))
        lines.append("")  # blank line between header block and match lines
        for m in group.matches:
            lines.append(_format_match_line(m, color))  # noqa: PERF401
        lines.append("")  # blank line between files
    return "\n".join(lines)


def _render_json_groups(groups: list[FileMatches]) -> str:
    """Render grouped matches as one JSON record per match (newline-delimited)."""
    records: list[str] = []
    for group in groups:
        for m in group.matches:
            record = _build_match_json_record(m, group)
            records.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(records)


def format_human(
    raw_output: str,
    roots: list[MirrorRoot],
    *,
    include_frontmatter: bool = False,
    color: Color = NO_COLOR,
) -> str:
    """Format ripgrep JSON output as human-readable grouped text."""
    raw_matches = _parse_rg_json_lines(raw_output)
    if not raw_matches:
        return ""
    groups = _group_matches(raw_matches, roots, include_frontmatter=include_frontmatter)
    if not groups:
        return ""
    return _render_human_groups(groups, color)


def format_json(
    raw_output: str,
    roots: list[MirrorRoot],
    *,
    include_frontmatter: bool = False,
) -> str:
    """Format ripgrep JSON output as one JSON record per match (newline-delimited)."""
    raw_matches = _parse_rg_json_lines(raw_output)
    if not raw_matches:
        return ""
    groups = _group_matches(raw_matches, roots, include_frontmatter=include_frontmatter)
    return _render_json_groups(groups)


def write_output(  # noqa: PLR0913
    raw_output: str,
    roots: list[MirrorRoot],
    *,
    json_mode: bool = False,
    include_frontmatter: bool = False,
    stream: TextIO | None = None,
    total_limit: int | None = None,
    color: Color = NO_COLOR,
) -> int:
    """Write formatted search output to *stream* (defaults to stdout).

    When *total_limit* is set, only the first *total_limit* matches across all
    files are emitted (file order preserved as rg produced them).

    Returns the number of matches written.
    """
    if stream is None:
        stream = sys.stdout

    raw_matches = _parse_rg_json_lines(raw_output)
    if not raw_matches:
        return 0
    groups = _group_matches(raw_matches, roots, include_frontmatter=include_frontmatter)
    if total_limit is not None:
        groups = _truncate_groups(groups, total_limit)
    if not groups:
        return 0

    text = _render_json_groups(groups) if json_mode else _render_human_groups(groups, color)
    if not text:
        return 0
    print(text, file=stream, end="")
    return sum(len(g.matches) for g in groups)


def _truncate_groups(groups: list[FileMatches], total_limit: int) -> list[FileMatches]:
    """Truncate *groups* in place so the total match count is at most *total_limit*."""
    remaining = total_limit
    kept: list[FileMatches] = []
    for g in groups:
        if remaining <= 0:
            break
        if len(g.matches) > remaining:
            g.matches = g.matches[:remaining]
        kept.append(g)
        remaining -= len(g.matches)
    return kept


class StreamingFormatter:
    """Consume rg JSON lines one at a time, emit formatted output as we go.

    The same instance handles both human and JSON output via *json_mode*.
    Per-file metadata (title, page_id, frontmatter range) is cached so each
    file is read at most once.

    ``consume`` returns ``False`` once *total_limit* matches have been written;
    the caller should stop driving rg and terminate the process.
    """

    def __init__(
        self,
        roots: list[MirrorRoot],
        *,
        json_mode: bool,
        include_frontmatter: bool,
        total_limit: int,
        stream: TextIO,
        color: Color = NO_COLOR,
    ) -> None:
        self.roots = roots
        self.json_mode = json_mode
        self.include_frontmatter = include_frontmatter
        self.total_limit = total_limit
        self.stream = stream
        # JSON output is machine-consumed; ANSI codes would corrupt it.
        self.color = NO_COLOR if json_mode else color
        self.count = 0
        self._files: dict[Path, FileMatches] = {}
        self._fm_ranges: dict[Path, tuple[int, int] | None] = {}
        self._last_emitted_path: Path | None = None

    def consume(self, rg_line: str) -> bool:
        """Process one rg JSON line; return False once total limit is reached."""
        if self.count >= self.total_limit:
            return False
        match = _parse_one_rg_json_line(rg_line)
        if match is None:
            return True
        if not self._should_keep(match):
            return True
        fm_entry = self._file_entry(match.path)
        match.mirror = fm_entry.mirror
        match.title = fm_entry.title
        match.page_id = fm_entry.page_id
        self._emit(match, fm_entry)
        self.count += 1
        return self.count < self.total_limit

    def _should_keep(self, match: RgMatch) -> bool:
        """Return True if the match passes the frontmatter filter."""
        if self.include_frontmatter:
            return True
        fm_range = self._fm_range_for(match.path)
        return not is_frontmatter_line(match.line_number, fm_range)

    def _fm_range_for(self, path: Path) -> tuple[int, int] | None:
        if path not in self._fm_ranges:
            self._fm_ranges[path] = frontmatter_line_range(path)
        return self._fm_ranges[path]

    def _file_entry(self, path: Path) -> FileMatches:
        if path not in self._files:
            mirror = _find_mirror(path, self.roots)
            title, page_id = _read_frontmatter(path)
            self._files[path] = FileMatches(
                path=path,
                mirror=mirror,
                title=title,
                page_id=page_id,
            )
        return self._files[path]

    def _emit(self, match: RgMatch, fm_entry: FileMatches) -> None:
        if self.json_mode:
            record = _build_match_json_record(match, fm_entry)
            print(json.dumps(record, ensure_ascii=False), file=self.stream, flush=True)
            return
        if self._last_emitted_path != match.path:
            if self._last_emitted_path is not None:
                print(file=self.stream)
            for header_line in _format_file_header_lines(fm_entry, self.color):
                print(header_line, file=self.stream)
            print(file=self.stream)
            self._last_emitted_path = match.path
        print(_format_match_line(match, self.color), file=self.stream, flush=True)
