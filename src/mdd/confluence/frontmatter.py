"""Read and write YAML frontmatter in Markdown files.

The ``confluence:`` block also carries the ``publish_office`` and
``publish_office_state`` fields:

  confluence:
    publish_office: docx            # or pptx, or [docx, pptx]
    publish_office_state:
      docx:
        source_sha256: <hex>
        template_sha256: <hex>
        quarto_version: "1.6.0"
        attachment_filename: My-Page.docx
        attachment_sha256: <hex>
        attachment_version: 4
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def read(path: Path) -> tuple[dict[str, Any], str]:
    """Parse a Markdown file and return (frontmatter_dict, body_without_frontmatter).

    Returns ({}, full_content) if there is no frontmatter fence.
    """
    content = path.read_text(encoding="utf-8")

    if not content.startswith(("---\n", "---\r\n")):
        return {}, content

    # Find closing ---
    rest = content[4:]  # skip opening ---\n
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        # Try end-of-file fence
        if rest.endswith("\n---"):
            end_idx = len(rest) - 4
        else:
            return {}, content

    yaml_block = rest[:end_idx]
    body = rest[end_idx + 5 :]  # skip \n---\n

    try:
        parsed: Any = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return {}, content

    if not isinstance(parsed, dict):
        return {}, content

    result: dict[str, Any] = dict(parsed.items())  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]  # raw dict[str, Any] read helper — callers convert to typed models
    return result, body


def write(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    """Atomically write a Markdown file with YAML frontmatter.

    Uses a .tmp file + os.fsync + rename for atomicity.
    Frontmatter is serialized with sort_keys=False, block style.

    The .tmp file is always cleaned up on failure so it cannot become an
    orphan that confuses glob-based tooling.
    """
    fm_str = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    content = f"---\n{fm_str}---\n{body}"

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)  # noqa: PTH105
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
