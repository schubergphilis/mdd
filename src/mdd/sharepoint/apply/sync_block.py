"""Read/update the ``sharepoint.sync`` block in a markdown file's frontmatter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import yaml

from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter

from .io import atomic_write_text

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def update_sync_block_in_md(
    md_path: Path,
    *,
    office_sha256: str,
    md_sha256: str,
    converter_version: str,
    converter: str,
    update_office: bool,
) -> None:
    """Update (or insert) the ``sharepoint.sync`` sub-block in *md_path*'s frontmatter.

    If the file already has a ``sharepoint:`` key the sync block is merged in;
    otherwise a new ``sharepoint:`` block is prepended.

    ``update_office`` controls whether subsequent md edits are rendered back
    to the office file. Set to ``True`` for md-authoritative pairs (rendered
    via Quarto), ``False`` for office-authoritative pairs (the conservative
    default).
    """
    text = md_path.read_text(encoding="utf-8", errors="replace")
    new_sync: dict[str, Any] = {
        "office_sha256_at_sync": office_sha256,
        "md_sha256_at_sync": md_sha256,
        "last_sync": _now_utc_iso(),
        "converter": converter,
        "converter_version": converter_version,
        "update_office": update_office,
    }

    updated = _inject_sync_block(text, new_sync)
    atomic_write_text(md_path, updated)


def _inject_sync_block(text: str, new_sync: dict[str, Any]) -> str:
    """Return *text* with the ``sharepoint.sync`` block updated or inserted."""
    split = split_frontmatter(text)
    if split is None:
        # No frontmatter, or unclosed frontmatter — prepend a minimal sharepoint block
        fm = yaml.safe_dump(
            {"sharepoint": {"sync": new_sync}},
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        return f"---\n{fm}---\n{text}"

    fm_block, body_after = split

    mapping = parse_yaml_mapping(fm_block)
    fm_dict: dict[str, Any] = dict(mapping) if mapping is not None else {}

    # Upsert sharepoint.sync, preserving any other sharepoint:* fields.
    sp_raw = fm_dict.get("sharepoint")
    sp_dict: dict[str, Any] = (
        dict(cast("Mapping[str, Any]", sp_raw)) if isinstance(sp_raw, dict) else {}
    )
    sp_dict["sync"] = new_sync
    fm_dict["sharepoint"] = sp_dict

    merged = yaml.safe_dump(
        fm_dict,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{merged}---\n{body_after}"
