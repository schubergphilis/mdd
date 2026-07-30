"""AI-powered cross-page review orchestrator.

Runs one or more sub-modes (duplicates, inconsistencies, stale) over a
directory of markdown files, producing a structured report.

Usage::

    from mdd.ai.review import run_review, ReviewConfig

    cfg = ReviewConfig(
        directory=Path("docs/"),
        modes={"duplicates", "stale"},
        top_k=5,
        similarity=0.85,
        age_days=365,
        output_dir=Path("docs/review"),
        model=None,
    )
    report_path = run_review(cfg, client)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml

from mdd.ai.bm25 import Bm25Index
from mdd.ai.judges import (
    DuplicateFinding,
    InconsistencyFinding,
    ReviewSummary,
    StaleFinding,
    judge_duplicate_pair,
    judge_inconsistency_pair,
    judge_stale_candidate,
)
from mdd.ai.reports import choose_report_path, render_report
from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.ai.client import Client

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_AGE_PATTERN = re.compile(
    r"(?:as of|last reviewed|updated)[^\d]*(\d{4}[-/]\d{2}[-/]\d{2})", re.IGNORECASE
)
_DATE_RE = re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b")


@dataclass
class ReviewConfig:
    """Configuration for a single review run."""

    directory: Path
    modes: set[str]  # subset of {"duplicates", "inconsistencies", "stale"}
    top_k: int = 5
    similarity: float = 0.85  # min BM25 score for duplicates shortlist
    age_days: int = 365
    output_dir: Path | None = None  # defaults to <directory>/docs/review
    output_path: Path | None = None  # explicit output override
    model: str | None = None


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------


def _read_frontmatter(content: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file content string."""
    if not (content.startswith(("---\n", "---\r\n"))):
        return {}
    rest = content[4:]
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        if rest.endswith("\n---"):
            end_idx = len(rest) - 4
        else:
            return {}
    fm_text = rest[:end_idx]
    try:
        parsed: Any = yaml.safe_load(fm_text)  # pyright: ignore[reportAny]
        return cast("dict[str, Any]", parsed) if isinstance(parsed, dict) else {}
    except yaml.YAMLError:
        return {}


def _body_without_frontmatter(content: str) -> str:
    """Strip frontmatter from content; return body."""
    if not (content.startswith(("---\n", "---\r\n"))):
        return content
    rest = content[4:]
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        if rest.endswith("\n---"):
            return ""
        return content
    return rest[end_idx + 5 :]


def _file_hash(content: str) -> bytes:
    return hashlib.sha256(content.encode()).digest()


def _load_docs(directory: Path) -> list[tuple[Path, str, dict[str, Any]]]:
    """Walk *directory* and return (path, content, frontmatter) for all .md files.

    Paths are relative to *directory*.
    """
    docs: list[tuple[Path, str, dict[str, Any]]] = []
    for md_file in sorted(directory.rglob("*.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = md_file.relative_to(directory)
        fm = _read_frontmatter(content)
        docs.append((rel, content, fm))
    return docs


# ---------------------------------------------------------------------------
# Stale heuristics
# ---------------------------------------------------------------------------


def _parse_date_str(date_val: Any) -> datetime | None:  # pyright: ignore[reportAny]
    """Try to parse a frontmatter date value to a datetime."""
    if isinstance(date_val, datetime):
        return date_val
    if not isinstance(date_val, str):
        return None
    m = _DATE_RE.search(date_val)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
    except ValueError:
        return None


def _doc_updated_at(content: str, fm: dict[str, Any]) -> datetime | None:
    """Return the best guess at when this document was last updated."""
    for key in ("updated_at", "last_modified", "date"):
        val: Any = fm.get(key)  # pyright: ignore[reportAny]
        if val is not None:
            dt = _parse_date_str(val)
            if dt is not None:
                return dt
    # Fall back to body-text date patterns.
    for m in _AGE_PATTERN.finditer(content):
        dt = _parse_date_str(m.group(1))
        if dt is not None:
            return dt
    return None


def _is_stale(
    content: str,
    fm: dict[str, Any],
    now: datetime,
    age_days: int,
) -> tuple[bool, str]:
    """Return (is_stale, date_str) for a document."""
    dt = _doc_updated_at(content, fm)
    if dt is None:
        return False, ""
    delta = now - dt
    date_str = dt.strftime("%Y-%m-%d")
    if delta.days > age_days:
        return True, date_str
    return False, date_str


# ---------------------------------------------------------------------------
# Sub-mode runners
# ---------------------------------------------------------------------------


def _sync_call_counters(client: Client, summary: ReviewSummary) -> None:
    """Copy the monotonic cached_calls/api_calls counters from `client` into `summary`.

    Same shape used after every judge call in all three review modes. The
    counters are monotonic on the client side, so we just take the maximum.
    """
    if client.summary.cached_calls > summary.cached_calls:
        summary.cached_calls = client.summary.cached_calls
    if client.summary.api_calls > summary.api_calls:
        summary.api_calls = client.summary.api_calls


def _run_duplicates(
    docs: list[tuple[Path, str, dict[str, Any]]],
    index: Bm25Index,
    cfg: ReviewConfig,
    client: Client,
    summary: ReviewSummary,
) -> list[DuplicateFinding]:
    findings: list[DuplicateFinding] = []

    pairs = index.top_k_pairs(cfg.top_k, min_score=cfg.similarity)
    for pair in pairs:
        path_a, path_b = pair.path_a, pair.path_b

        # Look up content
        content_map = {p: (c, fm) for p, c, fm in docs}
        if path_a not in content_map or path_b not in content_map:
            continue
        content_a, _ = content_map[path_a]
        content_b, _ = content_map[path_b]

        body_a = _body_without_frontmatter(content_a)
        body_b = _body_without_frontmatter(content_b)
        hash_a = _file_hash(content_a)
        hash_b = _file_hash(content_b)

        summary.pairs_judged += 1
        try:
            finding = judge_duplicate_pair(
                path_a,
                body_a,
                path_b,
                body_b,
                client=client,
                hash_a=hash_a,
                hash_b=hash_b,
                model=cfg.model,
            )
        except Exception:
            summary.errors += 1
            continue

        # Track cache stats
        _sync_call_counters(client, summary)

        if finding is not None:
            findings.append(finding)
            summary.duplicates_found += 1

    return findings


def _run_inconsistencies(
    docs: list[tuple[Path, str, dict[str, Any]]],
    index: Bm25Index,
    cfg: ReviewConfig,
    client: Client,
    summary: ReviewSummary,
) -> list[InconsistencyFinding]:
    findings: list[InconsistencyFinding] = []

    # Use pairs from the index (same shortlist as duplicates, but with lower threshold)
    pairs = index.top_k_pairs(cfg.top_k, min_score=0.0)
    content_map = {p: (c, fm) for p, c, fm in docs}

    for pair in pairs:
        path_a, path_b = pair.path_a, pair.path_b
        if path_a not in content_map or path_b not in content_map:
            continue
        content_a, _ = content_map[path_a]
        content_b, _ = content_map[path_b]

        body_a = _body_without_frontmatter(content_a)
        body_b = _body_without_frontmatter(content_b)
        hash_a = _file_hash(content_a)
        hash_b = _file_hash(content_b)

        summary.pairs_judged += 1
        try:
            finding = judge_inconsistency_pair(
                path_a,
                body_a,
                path_b,
                body_b,
                client=client,
                hash_a=hash_a,
                hash_b=hash_b,
                model=cfg.model,
            )
        except Exception:
            summary.errors += 1
            continue

        _sync_call_counters(client, summary)

        if finding is not None:
            findings.append(finding)
            summary.inconsistencies_found += 1

    return findings


@dataclass(frozen=True)
class _StaleCandidate:
    """A stale-judge candidate: source path, full file content, formatted date."""

    path: Path
    content: str
    date_str: str


def _partition_by_staleness(
    docs: list[tuple[Path, str, dict[str, Any]]],
    *,
    now: datetime,
    age_days: int,
) -> tuple[list[_StaleCandidate], set[Path]]:
    """Split `docs` into stale candidates and the pool of newer (replacement-eligible) paths.

    Returns ``(candidates, newer_pool)``. ``candidates`` carries the date string
    derived during staleness classification so callers don't need to re-derive
    it; ``newer_pool`` is a set for fast membership checks during BM25
    restriction.
    """
    candidates: list[_StaleCandidate] = []
    newer_pool: set[Path] = set()
    for path, content, fm in docs:
        is_stale_flag, date_str = _is_stale(content, fm, now, age_days)
        if is_stale_flag:
            candidates.append(_StaleCandidate(path=path, content=content, date_str=date_str))
        else:
            newer_pool.add(path)
    return candidates, newer_pool


def _resolve_newer_docs(
    neighbours: list[tuple[Path, float]],
    content_map: dict[Path, tuple[str, dict[str, Any]]],
) -> list[tuple[Path, str]]:
    """Materialise BM25 neighbour paths into `(path, body)` pairs.

    Drops any neighbour not present in `content_map` (defensive — the index is
    built over `docs` so misses should be rare).
    """
    out: list[tuple[Path, str]] = []
    for np, _ in neighbours:
        if np in content_map:
            nc, _ = content_map[np]
            out.append((np, _body_without_frontmatter(nc)))
    return out


def _judge_one_stale_candidate(
    candidate: _StaleCandidate,
    newer_docs: list[tuple[Path, str]],
    *,
    cfg: ReviewConfig,
    client: Client,
    summary: ReviewSummary,
) -> StaleFinding | None:
    """Run the stale-judge for one candidate against its resolved newer docs.

    None means "judge errored / returned no finding". All summary-side
    bookkeeping (pairs_judged / errors / call counters / stale_found) is
    applied here; the caller only appends the returned finding.
    """
    summary.pairs_judged += 1
    try:
        finding = judge_stale_candidate(
            candidate.path,
            _body_without_frontmatter(candidate.content),
            candidate.date_str,
            newer_docs,
            client=client,
            stale_hash=_file_hash(candidate.content),
            model=cfg.model,
        )
    except Exception:
        summary.errors += 1
        return None

    _sync_call_counters(client, summary)
    if finding is not None:
        summary.stale_found += 1
    return finding


def _run_stale(
    docs: list[tuple[Path, str, dict[str, Any]]],
    index: Bm25Index,
    cfg: ReviewConfig,
    client: Client,
    summary: ReviewSummary,
) -> list[StaleFinding]:
    content_map = {p: (c, fm) for p, c, fm in docs}
    candidates, newer_pool = _partition_by_staleness(
        docs, now=datetime.now(tz=UTC), age_days=cfg.age_days
    )

    findings: list[StaleFinding] = []
    for candidate in candidates:
        if not newer_pool:
            break
        neighbours = index.top_k_for(candidate.path, cfg.top_k, restrict_to=newer_pool)
        if not neighbours:
            continue
        newer_docs = _resolve_newer_docs(neighbours, content_map)
        if not newer_docs:
            continue
        finding = _judge_one_stale_candidate(
            candidate, newer_docs, cfg=cfg, client=client, summary=summary
        )
        if finding is not None:
            findings.append(finding)
    return findings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_review(cfg: ReviewConfig, client: Client) -> Path:
    """Run the configured review modes and write a report file.

    Parameters
    ----------
    cfg:
        Review configuration including modes, directory, and output options.
    client:
        AI client instance.

    Returns
    -------
    Path
        The path of the written report file.
    """
    if not cfg.directory.is_dir():
        log.error("not a directory: %s", cfg.directory)
        raise ValueError(f"Not a directory: {cfg.directory}")

    docs = _load_docs(cfg.directory)
    if not docs:
        log.warning("no .md files found in %s", cfg.directory)

    # Build the BM25 index once, shared across all modes.
    doc_pairs: list[tuple[Path, str]] = [(p, _body_without_frontmatter(c)) for p, c, _ in docs]
    index = Bm25Index.build(doc_pairs)

    summary = ReviewSummary()

    duplicates: list[DuplicateFinding] | None = None
    inconsistencies: list[InconsistencyFinding] | None = None
    stale: list[StaleFinding] | None = None

    if "duplicates" in cfg.modes:
        duplicates = _run_duplicates(docs, index, cfg, client, summary)

    if "inconsistencies" in cfg.modes:
        inconsistencies = _run_inconsistencies(docs, index, cfg, client, summary)

    if "stale" in cfg.modes:
        stale = _run_stale(docs, index, cfg, client, summary)

    # Determine scope label
    scope = cfg.directory.name or str(cfg.directory)

    run_date = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    report_md = render_report(
        duplicates=duplicates,
        inconsistencies=inconsistencies,
        stale=stale,
        scope=scope,
        run_date=run_date,
        summary=summary,
    )

    # Determine output path
    if cfg.output_path is not None:
        report_path = cfg.output_path
    else:
        out_dir = cfg.output_dir or (Path.cwd() / "docs" / "review")
        report_path = choose_report_path(out_dir, run_date, scope)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")

    return report_path


def print_run_summary(report_path: Path, summary: ReviewSummary) -> None:
    """Log a one-line run summary."""
    log.info(
        "Review report written to: %s  (pairs=%d, api=%d, cached=%d, errors=%d)",
        report_path,
        summary.pairs_judged,
        summary.api_calls,
        summary.cached_calls,
        summary.errors,
    )
