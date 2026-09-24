# 005 - pdf / pdf-pptx / pdf-docx commands

**Purpose:** Export Office files to PDF via AppleScript (macOS only).

**Status:** Implemented (2026-05-07)

## Requirements

- `mdd pdf-pptx [dir]` finds PPTX files needing export, uses PowerPoint via AppleScript
- `mdd pdf-docx [dir]` finds DOCX files needing export, uses Word via AppleScript
- `mdd pdf-docx` updates every table of contents, and best-effort every other
  field, before export, because Word does not evaluate fields on open and a TOC
  would otherwise be empty in the PDF; `mdd pdf-docx --no-update-fields [dir]`
  exports without the update. `mdd pdf` always updates
- `mdd pdf-docx` first closes, unsaved, any copy of the document Word already
  has open, because Word's `open` returns that in-memory copy instead of
  re-reading the file
- The `.docx` is closed without saving, so the field update never changes the
  source or its mtime
- `mdd pdf [dir]` runs both
- Staleness: only export if PDF missing or source is newer than PDF
- Excludes symlinks and files in `templates/` directory
- Skips (with a warning) files whose name contains control characters
- Double-extension output: `file.pptx.pdf`, `file.docx.pdf`
- Defaults to current directory if no `[dir]` argument

## Design Approach

- Commands in `src/mdd/commands/pdf*.py`; shared helpers in `src/mdd/utils/pdf_export.py`
- AppleScript invoked via `subprocess.run(['osascript', '-e', script, '--', src, pdf])`;
  the script is a fixed constant with an `on run argv` handler that reads the
  source and PDF paths as `POSIX file (item N of argv)`, so file names are
  data, never part of the program text. The Word script is assembled from
  fixed fragments by `build_docx_applescript(update_fields=...)`
- Tables of contents are updated through Word's `tables of contents`
  collection, not `fields`: pandoc wraps the TOC field in a content control,
  which `fields` does not enumerate, and iterating `fields` can fail outright
  with error -1708, so the general field pass runs inside `try`
- macOS only — fails gracefully on other platforms (osascript not found)

## Implementation Notes

Ported from `quarto4sbp` (`cmd_pdf`, `cmd_pdf_pptx`, `cmd_pdf_docx`). The
`cmd_*(args)` entrypoint shape was superseded by
[S35](S35-argparse-cli-parsing.md)'s `register(subparsers, parents)` convention;
the three modules now expose `register()` and `_run_*` handlers in
`src/mdd/commands/pdf*.py`.
