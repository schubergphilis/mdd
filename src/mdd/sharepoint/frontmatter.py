"""frontmatter.py — SharePoint-specific frontmatter writer (spec S10, extended by 018).

Spec S18 adds the ``sharepoint.sync`` sub-block::

    sharepoint:
      sync:
        office_sha256_at_sync: 9f86d081...
        md_sha256_at_sync:     e3b0c442...
        last_sync:             2026-05-08T10:30:00+00:00
        converter:             docling-docx
        converter_version:     "2.4.0"
        update_office:         false
"""

import os
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path


def write_frontmatter(  # noqa: PLR0913
    path: Path,
    site: str,
    repo: str,
    source_path: str,
    source_mtime: str,
    exported_at: str,
    converter: str,
    body: str,
    *,
    sync: dict[str, Any] | None = None,
) -> None:
    """Write a Markdown file with SharePoint YAML frontmatter and export callout.

    Atomically writes to ``path`` (via a ``.tmp`` + rename).

    The frontmatter block::

        ---
        sharepoint:
          site: <site>
          repo: <repo>
          source_path: <source_path>
          source_mtime: <source_mtime>
          exported_at: <exported_at>
          converter: <converter>
        ---

    Followed by an export callout::

        > **SharePoint export**
        >
        > This page was exported from `<site>/<source_path>` on
        > <YYYY-MM-DD>. The master copy lives in SharePoint via OneDrive.
    """
    sp_block: dict[str, Any] = {
        "site": site,
        "repo": repo,
        "source_path": source_path,
        "source_mtime": source_mtime,
        "exported_at": exported_at,
        "converter": converter,
    }
    if sync is not None:
        sp_block["sync"] = sync

    frontmatter: dict[str, Any] = {"sharepoint": sp_block}

    fm_str = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )

    export_date = exported_at[:10]  # YYYY-MM-DD
    callout = (
        f"> **SharePoint export**\n"
        f">\n"
        f"> This page was exported from `{site}/{source_path}` on\n"
        f"> {export_date}. The master copy lives in SharePoint via OneDrive.\n"
    )

    content = f"---\n{fm_str}---\n{callout}\n{body}"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)  # noqa: PTH105
