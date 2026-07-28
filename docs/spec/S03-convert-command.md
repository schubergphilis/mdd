# 003 - convert command

**Purpose:** `mdd convert` recursively converts `.docx` files to Markdown (`.docx.md`) using Docling for body content and python-docx for metadata extraction.

**Status:** Implemented (2026-05-07)

Ported from `lsimons-auto spec-019` (md action). See that spec for full algorithm detail.

## Requirements

- `mdd convert <path>` walks `<path>`, writes `<original>.docx.md` in-place
- `--dest-dir <dir>` mirrors source tree into `<dir>`
- Incremental: skip files whose `.md` is newer than the `.docx` (unless `--force`)
- `--dry-run` prints what would be converted without writing
- `--file <path>` converts a single file regardless of extension
- Progress printed per file: `[N/M] Converting: <relpath>`
- Non-zero exit if any conversion fails; continues and reports all failures

## Design Approach

- Registered in `src/mdd/commands/convert.py` via the
  `register(subparsers, parents)` convention defined in
  [S35](S35-argparse-cli-parsing.md); the pre-S35 `cmd_convert(args)` shape
  has been superseded.
- `extract_title`, `extract_metadata` use python-docx; `convert_body` uses Docling
- Docling `DocumentConverter` instantiated once per invocation (singleton)
- Atomic write: write to `.md.tmp`, then rename

## Implementation Notes

- **Dependencies:** `docling>=2`, `python-docx>=1`

## House-template metadata output format

- Multi-person fields (Participants, Invitees, Absent): nested bullet list
- Single-value meeting fields (Location): `- **Key:** Value`
- Document-meta fields (For, Date, Author, Status): `- Key: Value` (no bold)

## Post-processing (in order)

1. `html.unescape()`
2. Strip Word-generated TOC
3. Strip empty/artifact headings
4. Strip boilerplate sections (Meeting Logistics)
5. Strip boilerplate lines (JIRA board bullet)
