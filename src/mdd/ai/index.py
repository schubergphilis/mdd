"""AI-powered directory INDEX.md generator with per-file summary caching.

Usage::

    from mdd.ai.index import index_dir, IndexResult

    result = index_dir(
        directory=Path("docs/"),
        client=client,
        depth="1",    # or "all" for topic clustering
        apply=False,  # print to stdout rather than write INDEX.md
    )
    print(result.status)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml

from mdd.utils.logging import get_logger

if TYPE_CHECKING:
    from mdd.ai.client import Client

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------


def _prompts_dir() -> Path:
    return Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_prompts_dir() / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontmatter helpers (local — avoids circular import with confluence/)
# ---------------------------------------------------------------------------


def _read_frontmatter_and_body(path: Path) -> tuple[dict[str, Any], str]:
    """Parse a Markdown file and return (frontmatter_dict, body_without_frontmatter)."""
    content = path.read_text(encoding="utf-8")
    if not (content.startswith(("---\n", "---\r\n"))):
        return {}, content

    rest = content[4:]
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        if rest.endswith("\n---"):
            end_idx = len(rest) - 4
        else:
            return {}, content

    yaml_block = rest[:end_idx]
    body = rest[end_idx + 5 :]

    try:
        parsed: Any = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return {}, content

    if not isinstance(parsed, dict):
        return {}, content

    result: dict[str, Any] = dict(parsed)  # pyright: ignore[reportUnknownArgumentType]
    return result, body


def _write_frontmatter_and_body(path: Path, fm: dict[str, Any], body: str) -> None:
    """Atomically write *path* with YAML frontmatter and *body*."""
    fm_str = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
    content = f"---\n{fm_str}---\n{body}"
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _body_hash(body: str) -> str:
    return hashlib.sha256(body.encode()).hexdigest()


def _is_managed_file(fm: dict[str, Any]) -> bool:
    """Return True if the frontmatter indicates a managed-elsewhere page.

    Checks ``confluence.managed_by`` stamped during pull-side export.
    """
    conf_raw: Any = fm.get("confluence")  # pyright: ignore[reportAny]
    if not isinstance(conf_raw, dict):
        return False
    conf: dict[str, Any] = conf_raw  # pyright: ignore[reportUnknownVariableType]
    managed_by: Any = conf.get("managed_by")  # pyright: ignore[reportAny]
    return bool(managed_by)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _collect_md_files(directory: Path) -> list[Path]:
    """Walk *directory* recursively, returning .md files excluding INDEX.md."""
    files: list[Path] = []
    for p in sorted(directory.rglob("*.md")):
        if p.name == "INDEX.md":
            continue
        files.append(p)
    return files


# ---------------------------------------------------------------------------
# Per-file summary
# ---------------------------------------------------------------------------


@dataclass
class FileSummary:
    path: Path
    rel_path: str
    summary: str
    cached: bool  # True if the stored frontmatter hash matched
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None


def _cached_summary_for(fm: dict[str, Any], body_hash: str) -> str | None:
    """Return a valid cached summary from frontmatter when the hash matches.

    The cache lives at ``fm["mdd"]["ai"]``. A summary is "valid" when both
    `summary_input_hash` equals `body_hash` and `summary` is a non-empty
    string. Anything else (missing keys, wrong types, stale hash) returns None.
    """
    mdd_section: Any = fm.get("mdd")  # pyright: ignore[reportAny]
    if not isinstance(mdd_section, dict):
        return None
    ai_raw: Any = cast("dict[str, Any]", mdd_section).get("ai")  # pyright: ignore[reportAny]
    if not isinstance(ai_raw, dict):
        return None
    ai_dict: dict[str, Any] = cast("dict[str, Any]", ai_raw)
    stored_hash: Any = ai_dict.get("summary_input_hash")  # pyright: ignore[reportAny]
    stored_summary: Any = ai_dict.get("summary")  # pyright: ignore[reportAny]
    if (
        isinstance(stored_hash, str)
        and stored_hash == body_hash
        and isinstance(stored_summary, str)
        and stored_summary
    ):
        return stored_summary
    return None


def _persist_summary_to_frontmatter(
    path: Path,
    fm: dict[str, Any],
    body: str,
    *,
    summary_text: str,
    body_hash: str,
    summary_model: str,
) -> None:
    """Mutate `fm` to record the fresh summary and write the file atomically.

    Caller is responsible for the managed-page check; this helper unconditionally
    writes. Frontmatter shape: ``fm["mdd"]["ai"] = {summary, summary_input_hash,
    summary_model, summary_at}``.
    """
    if not isinstance(fm.get("mdd"), dict):
        fm["mdd"] = {}
    mdd_dict: dict[str, Any] = cast("dict[str, Any]", fm["mdd"])  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
    if not isinstance(mdd_dict.get("ai"), dict):
        mdd_dict["ai"] = {}
    ai_dict: dict[str, Any] = cast("dict[str, Any]", mdd_dict["ai"])  # pyright: ignore[reportAny,reportUnknownVariableType,reportUnknownMemberType]
    ai_dict["summary"] = summary_text
    ai_dict["summary_input_hash"] = body_hash
    ai_dict["summary_model"] = summary_model
    ai_dict["summary_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        _write_frontmatter_and_body(path, fm, body)
    except OSError:
        log.exception("could not write frontmatter to %s", path)


def _writeback_summary(
    path: Path,
    fm: dict[str, Any],
    body: str,
    *,
    summary_text: str,
    body_hash: str,
    client: Client,
) -> None:
    """Write the fresh summary back into the source frontmatter.

    Managed-elsewhere pages (`confluence.managed_by`) are skipped with a warning;
    only locally-owned files get updated.
    """
    if _is_managed_file(fm):
        log.warning(
            "%s is a managed-elsewhere page; skipping frontmatter write-back.",
            path,
        )
        return
    _persist_summary_to_frontmatter(
        path,
        fm,
        body,
        summary_text=summary_text,
        body_hash=body_hash,
        summary_model=client.model_for_task("summarise", None),
    )


def _get_or_compute_summary(
    path: Path,
    rel_path: str,
    client: Client,
    *,
    model: str | None,
    apply: bool,
) -> FileSummary | None:
    """Return a FileSummary for *path*, using cached frontmatter when valid.

    If *apply* is True and the summary was freshly computed, writes the
    summary back into the source file's frontmatter.

    Returns None on error (logs to stderr).
    """
    try:
        fm, body = _read_frontmatter_and_body(path)
    except OSError:
        log.exception("error reading %s", path)
        return None

    body_hash = _body_hash(body)

    cached = _cached_summary_for(fm, body_hash)
    if cached is not None:
        return FileSummary(path=path, rel_path=rel_path, summary=cached, cached=True)

    try:
        result = client.chat(
            system=_load_prompt("summarise.md"),
            user=body,
            task="summarise",
            model=model,
        )
    except Exception:
        log.exception("error summarising %s", path)
        return None

    summary_text = result.text.strip()

    if apply:
        _writeback_summary(
            path,
            fm,
            body,
            summary_text=summary_text,
            body_hash=body_hash,
            client=client,
        )

    return FileSummary(
        path=path,
        rel_path=rel_path,
        summary=summary_text,
        cached=result.cached,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
    )


# ---------------------------------------------------------------------------
# Topic clustering
# ---------------------------------------------------------------------------


def _cluster_summaries(
    summaries: list[FileSummary],
    client: Client,
    *,
    model: str | None,
) -> list[dict[str, Any]]:
    """Send summaries to the model for clustering.  Returns cluster list.

    Each cluster: {"topic_title": str, "file_paths": [str, ...]}

    Returns a single flat cluster on failure (model or parse error).
    """
    payload = [{"path": s.rel_path, "summary": s.summary} for s in summaries]
    user_text = json.dumps(payload, ensure_ascii=False, indent=2)
    system_prompt = _load_prompt("cluster.md")

    # Build cache key extra: hash of all summaries.
    joined = "\n".join(f"{s.rel_path}\t{s.summary}" for s in summaries)
    joined_hash = hashlib.sha256(joined.encode()).digest()

    try:
        result = client.chat(
            system=system_prompt,
            user=user_text,
            task="default",
            model=model,
            cache_key_extra=joined_hash,
        )
    except Exception:
        log.exception("clustering failed")
        return [{"topic_title": "Pages", "file_paths": [s.rel_path for s in summaries]}]

    raw_text = result.text.strip()
    # Strip markdown fences if the model wrapped the JSON.
    raw_text = re.sub(r"^```[^\n]*\n", "", raw_text)
    raw_text = re.sub(r"\n```$", "", raw_text)

    try:
        clusters: Any = json.loads(raw_text)  # pyright: ignore[reportAny]
    except json.JSONDecodeError:
        log.exception("could not parse cluster response")
        return [{"topic_title": "Pages", "file_paths": [s.rel_path for s in summaries]}]

    if not isinstance(clusters, list):
        return [{"topic_title": "Pages", "file_paths": [s.rel_path for s in summaries]}]

    return cast("list[dict[str, Any]]", clusters)  # pyright: ignore[reportAny]


# ---------------------------------------------------------------------------
# INDEX.md rendering
# ---------------------------------------------------------------------------


def _render_index_header(generated_at: str) -> str:
    """Return the YAML frontmatter + H1 title + auto-generated marker block."""
    fm = {
        "ai_generated": True,
        "generated_by": "mdd ai index",
        "generated_at": generated_at,
    }
    fm_str = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{fm_str}---\n# Index\n*Auto-generated by `mdd ai index`. Re-run to refresh.*\n"


def _render_summary_bullet(rel_path: str, summary: str) -> str:
    """Render a single ``- **[title](path)** — summary`` line."""
    title = _path_to_title(rel_path)
    return f"- **[{title}]({rel_path})** — {summary}\n"


def _render_cluster_section(
    cluster: dict[str, Any],
    summary_map: dict[str, str],
) -> tuple[str, set[str]]:
    """Render one cluster's ``## Topic`` section.

    Returns ``("", set())`` for clusters with no usable file_paths (skipped).
    Otherwise returns the rendered section and the set of paths it claimed.
    """
    file_paths: Any = cluster.get("file_paths", [])  # pyright: ignore[reportAny]
    if not isinstance(file_paths, list) or not file_paths:
        return "", set()
    topic_title: Any = cluster.get("topic_title", "Other")  # pyright: ignore[reportAny]
    parts: list[str] = [f"\n## {topic_title}\n\n"]
    claimed: set[str] = set()
    for fp_raw in file_paths:  # pyright: ignore[reportUnknownVariableType]
        if not isinstance(fp_raw, str):
            continue
        parts.append(_render_summary_bullet(fp_raw, summary_map.get(fp_raw, "")))
        claimed.add(fp_raw)
    return "".join(parts), claimed


def _render_clustered_body(
    summaries: list[FileSummary],
    clusters: list[dict[str, Any]],
) -> str:
    """Render the H2-sectioned body; uncategorised files land in a trailing "Other"."""
    summary_map: dict[str, str] = {s.rel_path: s.summary for s in summaries}
    parts: list[str] = []
    claimed: set[str] = set()
    for cluster in clusters:
        section, section_claimed = _render_cluster_section(cluster, summary_map)
        parts.append(section)
        claimed |= section_claimed

    unclaimed = [s for s in summaries if s.rel_path not in claimed]
    if unclaimed:
        parts.append("\n## Other\n\n")
        parts.extend(_render_summary_bullet(s.rel_path, s.summary) for s in unclaimed)
    return "".join(parts)


def _render_flat_body(summaries: list[FileSummary]) -> str:
    """Render the depth=1 flat bullet list."""
    parts: list[str] = ["\n"]
    parts.extend(_render_summary_bullet(s.rel_path, s.summary) for s in summaries)
    return "".join(parts)


def _render_index(
    summaries: list[FileSummary],
    clusters: list[dict[str, Any]] | None,
    generated_at: str,
) -> str:
    """Render the INDEX.md content.

    *clusters* is None for depth=1 (flat list) or a cluster list for depth=all.
    """
    body = (
        _render_flat_body(summaries)
        if clusters is None
        else _render_clustered_body(summaries, clusters)
    )
    return _render_index_header(generated_at) + body


def _path_to_title(rel_path: str) -> str:
    """Convert a relative path to a display title."""
    stem = Path(rel_path).stem
    # Replace hyphens and underscores with spaces.
    return stem.replace("-", " ").replace("_", " ")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class IndexResult:
    """Result of running mdd ai index on a directory."""

    directory: Path
    status: str  # "ok" | "error"
    files_total: int = 0
    summaries_cached: int = 0
    summaries_computed: int = 0
    errors: int = 0
    index_path: Path | None = None
    index_content: str | None = None  # set when apply=False
    error: str | None = None
    per_file: list[FileSummary | None] = field(default_factory=list)


def index_dir(
    directory: Path,
    client: Client,
    *,
    depth: str = "1",
    apply: bool = False,
    model: str | None = None,
) -> IndexResult:
    """Generate or refresh an INDEX.md for *directory*.

    Parameters
    ----------
    directory:
        The directory to index.
    client:
        An initialised ``mdd.ai.Client`` instance.
    depth:
        ``"1"`` for a flat list, ``"all"`` for topic clustering.
    apply:
        If ``True``, write ``INDEX.md`` and update source-file frontmatter.
        If ``False``, print the proposed INDEX.md to stdout.
    model:
        Override the model selection.

    Returns
    -------
    IndexResult
    """
    if not directory.is_dir():
        return IndexResult(
            directory=directory,
            status="error",
            error=f"Not a directory: {directory}",
        )

    md_files = _collect_md_files(directory)
    if not md_files:
        return IndexResult(
            directory=directory,
            status="ok",
            files_total=0,
            index_content="",
        )

    per_file_results: list[FileSummary | None] = []
    for p in md_files:
        rel = str(p.relative_to(directory))
        fs = _get_or_compute_summary(p, rel, client, model=model, apply=apply)
        per_file_results.append(fs)
        if fs is not None:
            status_label = "cached" if fs.cached else "summarised"
            log.info("  %s: %s", status_label, rel)
        else:
            log.error("  error:     %s", rel)

    valid_summaries: list[FileSummary] = [s for s in per_file_results if s is not None]
    errors = sum(1 for s in per_file_results if s is None)

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    clusters: list[dict[str, Any]] | None = None
    if depth == "all" and valid_summaries:
        clusters = _cluster_summaries(valid_summaries, client, model=model)

    index_content = _render_index(valid_summaries, clusters, generated_at)

    index_path = directory / "INDEX.md"

    if apply:
        tmp = index_path.with_suffix(".md.tmp")
        try:
            tmp.write_text(index_content, encoding="utf-8")
            tmp.replace(index_path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            return IndexResult(
                directory=directory,
                status="error",
                files_total=len(md_files),
                errors=errors,
                error=f"Failed to write INDEX.md: {exc}",
                per_file=per_file_results,
            )
    else:
        # Program output (markdown for piping) — intentionally uses print().
        print(index_content)  # noqa: T201

    return IndexResult(
        directory=directory,
        status="ok",
        files_total=len(md_files),
        summaries_cached=sum(1 for s in valid_summaries if s.cached),
        summaries_computed=sum(1 for s in valid_summaries if not s.cached),
        errors=errors,
        index_path=index_path if apply else None,
        index_content=index_content if not apply else None,
        per_file=per_file_results,
    )


def print_run_summary(result: IndexResult, client: Client) -> None:
    """Log end-of-run summary."""
    log.info(
        "Index summary: %d files, %d summarised, %d cached, %d error(s).",
        result.files_total,
        result.summaries_computed,
        result.summaries_cached,
        result.errors,
    )
    summary = client.summary
    if summary.api_calls > 0:
        tokens = summary.prompt_tokens + summary.completion_tokens
        log.info(
            "  Tokens used: %s (prompt=%s, completion=%s)",
            f"{tokens:,}",
            f"{summary.prompt_tokens:,}",
            f"{summary.completion_tokens:,}",
        )
        if summary.cost_usd > 0:
            log.info("  Estimated cost: $%.4f", summary.cost_usd)
