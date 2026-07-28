#!/usr/bin/env python3
"""Refresh the captured ground-truth snapshots for the corpus.

For every fixture in ``fixtures/`` and ``corpus/`` that carries a
``confluence.page_id`` in YAML frontmatter, fetches:

- the canonical Confluence storage body  -> ``_snapshots/<page_id>/storage.xhtml``
- Confluence's rendered ``export_view``   -> ``_snapshots/<page_id>/export_view.html``
- page metadata + attachment manifest    -> ``_snapshots/<page_id>/metadata.json``

These snapshots are the offline ground truth that round-trip
experiments (research note 008 and onward) compare against. The
refresh is deliberately manual: drift between Confluence and the
captured snapshots tells us when an API shape changes, and
auto-refreshing would hide that signal.

Requires the mdd Python package to be importable (i.e. run via
``uv run`` from inside the mdd repo, or with the mdd venv active).

Usage:
    python scripts/refresh-corpus.py                  # refresh all
    python scripts/refresh-corpus.py --dry-run        # report only
    python scripts/refresh-corpus.py <page_id> ...    # only these
    python scripts/refresh-corpus.py --config <file>  # override creds config

The default config is ``<corpus-root>/configs/confluence.yaml``. On
machines that don't have a personal PAT for the test instance (e.g.
shared bot hosts), pass ``--config ~/.config/mdd/confluence.yaml``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.config import load as load_config

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("fixtures", "corpus")
SNAPSHOTS_DIR = REPO_ROOT / "_snapshots"


def parse_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    parsed = yaml.safe_load(m.group(1))
    return parsed if isinstance(parsed, dict) else {}


def collect_pages(only: set[str]) -> list[tuple[Path, str]]:
    """Return [(markdown_path, page_id)] for every fixture with a page_id."""
    pages: list[tuple[Path, str]] = []
    for sub in SCAN_DIRS:
        root = REPO_ROOT / sub
        if not root.exists():
            continue
        for md in sorted(root.rglob("*.md")):
            fm = parse_frontmatter(md)
            conf = fm.get("confluence")
            if not isinstance(conf, dict):
                continue
            page_id = conf.get("page_id")
            if not isinstance(page_id, str) or not page_id:
                continue
            if only and page_id not in only:
                continue
            pages.append((md, page_id))
    return pages


def make_client(config_path: Path) -> ConfluenceClient:
    """Build a Confluence client from the given config file."""
    cfg = load_config(config_path)
    token = cfg.api_token
    return ConfluenceClient(cfg.url, cfg.username, lambda: token)


def _extract_body(page: dict[str, Any], fmt: str) -> str:
    body_raw: Any = page.get("body")
    if not isinstance(body_raw, dict):
        return ""
    fmt_raw: Any = body_raw.get(fmt)
    if not isinstance(fmt_raw, dict):
        return ""
    val: Any = fmt_raw.get("value")
    return val if isinstance(val, str) else ""


def fetch_storage(client: ConfluenceClient, page_id: str) -> dict[str, Any]:
    return client.get(
        f"/wiki/api/v2/pages/{page_id}",
        params={
            "body-format": "storage",
            "include-labels": "true",
            "include-version": "true",
        },
    )


def fetch_export_view(client: ConfluenceClient, page_id: str) -> dict[str, Any]:
    return client.get(
        f"/wiki/api/v2/pages/{page_id}",
        params={"body-format": "export_view"},
    )


def build_metadata(
    storage_page: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Distil the metadata we care about for snapshot determinism."""

    def _get_str(d: dict[str, Any], key: str) -> str | None:
        v = d.get(key)
        return v if isinstance(v, str) else None

    version_raw: Any = storage_page.get("version")
    version: dict[str, Any] = {}
    if isinstance(version_raw, dict):
        version = {
            "number": version_raw.get("number"),
            "message": version_raw.get("message"),
            "createdAt": version_raw.get("createdAt"),
            "authorId": version_raw.get("authorId"),
        }

    labels: list[str] = []
    labels_raw: Any = storage_page.get("labels")
    if isinstance(labels_raw, dict):
        results_raw: Any = labels_raw.get("results")
        if isinstance(results_raw, list):
            for label in results_raw:
                if isinstance(label, dict):
                    name = label.get("name")
                    if isinstance(name, str):
                        labels.append(name)

    attachment_manifest: list[dict[str, Any]] = []
    for att in attachments:
        attachment_manifest.append(
            {
                "id": att.get("id"),
                "title": att.get("title"),
                "mediaType": (att.get("metadata") or {}).get("mediaType")
                if isinstance(att.get("metadata"), dict)
                else None,
                "fileSize": att.get("fileSize") or (att.get("extensions") or {}).get("fileSize"),
                "version": (att.get("version") or {}).get("number")
                if isinstance(att.get("version"), dict)
                else None,
            }
        )

    return {
        "id": _get_str(storage_page, "id"),
        "title": _get_str(storage_page, "title"),
        "status": _get_str(storage_page, "status"),
        "spaceId": _get_str(storage_page, "spaceId"),
        "parentId": _get_str(storage_page, "parentId"),
        "parentType": _get_str(storage_page, "parentType"),
        "authorId": _get_str(storage_page, "authorId"),
        "createdAt": _get_str(storage_page, "createdAt"),
        "version": version,
        "labels": labels,
        "attachments": attachment_manifest,
    }


def write_snapshot(
    page_id: str,
    storage_xhtml: str,
    export_view_html: str,
    metadata: dict[str, Any],
) -> Path:
    out = SNAPSHOTS_DIR / page_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "storage.xhtml").write_text(storage_xhtml, encoding="utf-8")
    (out / "export_view.html").write_text(export_view_html, encoding="utf-8")
    (out / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "page_ids",
        nargs="*",
        help="optional list of page_ids to refresh (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="report only, no fetch")
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "confluence.yaml",
        help="path to confluence config (default: <corpus-root>/configs/confluence.yaml)",
    )
    args = parser.parse_args()

    only = {pid for pid in args.page_ids if pid}
    pages = collect_pages(only)
    if not pages:
        if only:
            print(f"No fixtures matched page_ids {sorted(only)!r}", file=sys.stderr)
        else:
            print("No fixtures with confluence.page_id frontmatter found", file=sys.stderr)
        return 1

    print(f"Found {len(pages)} fixture(s) with page_id")
    if args.dry_run:
        for md, page_id in pages:
            rel = md.relative_to(REPO_ROOT)
            print(f"DRY    {page_id}  ({rel})")
        return 0

    client = make_client(args.config)

    failed = 0
    refreshed = 0
    for md, page_id in pages:
        rel = md.relative_to(REPO_ROOT)
        try:
            storage_page = fetch_storage(client, page_id)
            export_page = fetch_export_view(client, page_id)
            attachments = client.get_attachment_list(page_id)
        except ConfluenceError as exc:
            print(f"FAIL   {page_id}  ({rel}): {exc}", file=sys.stderr)
            failed += 1
            continue

        storage_xhtml = _extract_body(storage_page, "storage")
        export_view_html = _extract_body(export_page, "export_view")
        metadata = build_metadata(storage_page, attachments)

        out = write_snapshot(page_id, storage_xhtml, export_view_html, metadata)
        print(f"OK     {page_id}  -> {out.relative_to(REPO_ROOT)}/  ({rel})")
        refreshed += 1

    print()
    print(f"Refreshed: {refreshed}")
    print(f"Failed:    {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
