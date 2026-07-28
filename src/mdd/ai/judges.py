"""Per-mode LLM judge prompts and JSON response parsing (spec S22).

Each sub-mode has:
  - a *prompt_template* string (loaded from prompts/review-*.md)
  - a *build_user_message* function that formats the document content
  - a *parse_response* function that turns the model's JSON into a typed result
    or None (meaning "no finding")

All parse functions are strict: they return None rather than raise on bad JSON,
since LLM output is inherently unreliable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from mdd.ai.client import Client


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _prompts_dir() -> Path:
    return Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_prompts_dir() / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Finding data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateFinding:
    """A high-overlap pair found by the duplicates judge."""

    path_a: Path
    path_b: Path
    overlap: str  # "high" | "medium" | "low" | "none"
    summary: str
    shared_sections: list[str]
    suggested_action: str


@dataclass(frozen=True)
class InconsistencyFinding:
    """A set of contradictions found between two pages."""

    path_a: Path
    path_b: Path
    contradictions: list[dict[str, str]]  # list of {page_a_quote, page_b_quote, issue}


@dataclass(frozen=True)
class StaleFinding:
    """A page found to be superseded by a newer page."""

    stale_path: Path
    replacement_path: Path
    confidence: str  # "high" | "medium" | "low"
    evidence: str
    last_updated: str  # ISO date string or empty string


@dataclass
class ReviewSummary:
    """Accumulated totals for a review run."""

    pairs_judged: int = 0
    cached_calls: int = 0
    api_calls: int = 0
    errors: int = 0
    duplicates_found: int = 0
    inconsistencies_found: int = 0
    stale_found: int = 0
    findings_by_mode: dict[str, list[object]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Duplicate judge
# ---------------------------------------------------------------------------


def _parse_duplicate_response(
    raw: str,
    path_a: Path,
    path_b: Path,
) -> DuplicateFinding | None:
    """Parse the model's JSON into a DuplicateFinding.

    Returns None on parse error or when overlap is not 'high'.
    """
    data = _load_json_object(raw)
    if data is None:
        return None

    overlap: Any = data.get("overlap", "")  # pyright: ignore[reportAny]
    if not isinstance(overlap, str):
        return None
    if overlap != "high":
        return None

    summary_raw: Any = data.get("summary", "")  # pyright: ignore[reportAny]
    summary: str = str(summary_raw) if summary_raw else ""

    sections_raw: Any = data.get("shared_sections", [])  # pyright: ignore[reportAny]
    shared_sections: list[str] = (
        [str(s) for s in sections_raw]  # pyright: ignore[reportUnknownVariableType,reportAny,reportUnknownArgumentType]
        if isinstance(sections_raw, list)
        else []
    )

    action_raw: Any = data.get("suggested_action", "")  # pyright: ignore[reportAny]
    suggested_action: str = str(action_raw) if action_raw else ""

    return DuplicateFinding(
        path_a=path_a,
        path_b=path_b,
        overlap=overlap,
        summary=summary,
        shared_sections=shared_sections,
        suggested_action=suggested_action,
    )


def judge_duplicate_pair(  # noqa: PLR0913
    path_a: Path,
    body_a: str,
    path_b: Path,
    body_b: str,
    *,
    client: Client,
    hash_a: bytes,
    hash_b: bytes,
    model: str | None = None,
) -> DuplicateFinding | None:
    """Call the LLM to judge whether two pages are duplicates.

    Uses both file hashes as cache_key_extra so reruns on unchanged content
    are free.
    """
    system_prompt = _load_prompt("review-duplicates.md")

    user_message = f"## Page A: {path_a}\n\n{body_a}\n\n## Page B: {path_b}\n\n{body_b}"

    # Cache key: both file hashes + mode tag
    extra = hashlib.sha256(b"duplicates:" + hash_a + b":" + hash_b).digest()

    result = client.chat(
        system=system_prompt,
        user=user_message,
        task="default",
        model=model,
        cache_key_extra=extra,
    )

    return _parse_duplicate_response(result.text, path_a, path_b)


# ---------------------------------------------------------------------------
# Inconsistency judge
# ---------------------------------------------------------------------------


def _parse_inconsistency_response(
    raw: str,
    path_a: Path,
    path_b: Path,
) -> InconsistencyFinding | None:
    """Parse the model's JSON into an InconsistencyFinding.

    Returns None on parse error or when contradictions list is empty.
    """
    data = _load_json_object(raw)
    if data is None:
        return None

    contradictions_raw: Any = data.get("contradictions", [])  # pyright: ignore[reportAny]
    if not isinstance(contradictions_raw, list) or not contradictions_raw:
        return None

    contradictions: list[dict[str, str]] = []
    for item_raw in contradictions_raw:  # pyright: ignore[reportAny,reportUnknownVariableType]
        item: Any = item_raw  # pyright: ignore[reportAny,reportUnknownVariableType]
        if not isinstance(item, dict):
            continue
        item_d = cast("dict[str, Any]", item)
        entry: dict[str, str] = {
            "page_a_quote": str(item_d.get("page_a_quote", "")),  # pyright: ignore[reportAny]
            "page_b_quote": str(item_d.get("page_b_quote", "")),  # pyright: ignore[reportAny]
            "issue": str(item_d.get("issue", "")),  # pyright: ignore[reportAny]
        }
        contradictions.append(entry)

    if not contradictions:
        return None

    return InconsistencyFinding(
        path_a=path_a,
        path_b=path_b,
        contradictions=contradictions,
    )


def judge_inconsistency_pair(  # noqa: PLR0913
    path_a: Path,
    body_a: str,
    path_b: Path,
    body_b: str,
    *,
    client: Client,
    hash_a: bytes,
    hash_b: bytes,
    model: str | None = None,
) -> InconsistencyFinding | None:
    """Call the LLM to find contradictions between two pages."""
    system_prompt = _load_prompt("review-inconsistencies.md")

    user_message = f"## Page A: {path_a}\n\n{body_a}\n\n## Page B: {path_b}\n\n{body_b}"

    extra = hashlib.sha256(b"inconsistencies:" + hash_a + b":" + hash_b).digest()

    result = client.chat(
        system=system_prompt,
        user=user_message,
        task="default",
        model=model,
        cache_key_extra=extra,
    )

    return _parse_inconsistency_response(result.text, path_a, path_b)


# ---------------------------------------------------------------------------
# Stale judge
# ---------------------------------------------------------------------------


def _load_json_object(raw: str) -> dict[str, Any] | None:
    """Parse JSON expecting an object. Returns None on bad JSON, null, or non-dict.

    Treats both the JSON literal ``null`` and the bare string ``"null"`` as None,
    since the stale judge prompt instructs the model to return ``null`` for "no
    finding" and some models stringify that.
    """
    stripped = raw.strip()
    if stripped == "null":
        return None
    try:
        parsed: Any = json.loads(stripped)  # pyright: ignore[reportAny]
    except json.JSONDecodeError, ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return cast("dict[str, Any]", parsed)


def _resolve_replacement_path(candidate: str, newer_paths: list[Path]) -> Path:
    """Pick the Path that best matches ``candidate`` against ``newer_paths``.

    Match priority: exact string equality or basename, then bidirectional suffix
    match (paths may differ in their relative prefix), finally a raw ``Path``
    fallback so the finding still records what the model said.
    """
    for np in newer_paths:
        if str(np) == candidate or np.name == candidate:
            return np
    for np in newer_paths:
        if str(np).endswith(candidate) or candidate.endswith(str(np)):
            return np
    return Path(candidate)


def _parse_stale_response(
    raw: str,
    stale_path: Path,
    newer_paths: list[Path],
    last_updated: str,
) -> StaleFinding | None:
    """Parse the model's JSON into a StaleFinding.

    Returns None on parse error, null response, or low-confidence result.
    """
    data = _load_json_object(raw)
    if data is None:
        return None

    confidence_raw: Any = data.get("confidence", "")  # pyright: ignore[reportAny]
    confidence: str = str(confidence_raw) if confidence_raw else ""
    if confidence != "high":
        return None

    replacement_raw: Any = data.get("replacement")  # pyright: ignore[reportAny]
    if not isinstance(replacement_raw, str) or not replacement_raw:
        return None

    evidence_raw: Any = data.get("evidence", "")  # pyright: ignore[reportAny]
    evidence: str = str(evidence_raw) if evidence_raw else ""

    return StaleFinding(
        stale_path=stale_path,
        replacement_path=_resolve_replacement_path(replacement_raw, newer_paths),
        confidence=confidence,
        evidence=evidence,
        last_updated=last_updated,
    )


def judge_stale_candidate(  # noqa: PLR0913
    stale_path: Path,
    stale_body: str,
    stale_last_updated: str,
    newer_docs: list[tuple[Path, str]],
    *,
    client: Client,
    stale_hash: bytes,
    model: str | None = None,
) -> StaleFinding | None:
    """Call the LLM to check if a stale page has been superseded."""
    system_prompt = _load_prompt("review-stale.md")

    newer_section = "\n\n".join(
        f"### {path} (last updated {_extract_updated(body)})\n{body}" for path, body in newer_docs
    )

    user_message = (
        f"## Stale candidate: {stale_path} (last updated {stale_last_updated})\n"
        f"{stale_body}\n\n"
        f"## Newer candidates:\n{newer_section}"
    )

    # Cache key: stale file hash + hashes of all newer candidates
    newer_hashes = b":".join(hashlib.sha256(body.encode()).digest() for _, body in newer_docs)
    extra = hashlib.sha256(b"stale:" + stale_hash + b":" + newer_hashes).digest()

    result = client.chat(
        system=system_prompt,
        user=user_message,
        task="default",
        model=model,
        cache_key_extra=extra,
    )

    newer_paths = [p for p, _ in newer_docs]
    return _parse_stale_response(result.text, stale_path, newer_paths, stale_last_updated)


def _extract_updated(body: str) -> str:
    """Extract the updated_at date from frontmatter if present, else empty string."""
    fm_match = re.match(r"\A---\n(.*?)\n---\n?", body, re.DOTALL)
    if not fm_match:
        return ""
    fm_text = fm_match.group(1)
    date_match = re.search(r"updated_at:\s*(.+)", fm_text)
    if date_match:
        return date_match.group(1).strip()
    return ""
