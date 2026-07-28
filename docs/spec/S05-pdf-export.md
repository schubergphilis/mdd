# 005 - pdf / pdf-pptx / pdf-docx commands

**Purpose:** Export Office files to PDF via AppleScript (macOS only).

**Status:** Implemented (2026-05-07)

## Requirements

- `mdd pdf-pptx [dir]` finds PPTX files needing export, uses PowerPoint via AppleScript
- `mdd pdf-docx [dir]` finds DOCX files needing export, uses Word via AppleScript
- `mdd pdf [dir]` runs both
- Staleness: only export if PDF missing or source is newer than PDF
- Excludes symlinks and files in `templates/` directory
- Double-extension output: `file.pptx.pdf`, `file.docx.pdf`
- Defaults to current directory if no `[dir]` argument

## Design Approach

- Commands in `src/mdd/commands/pdf*.py`; shared helpers in `src/mdd/utils/pdf_export.py`
- AppleScript invoked via `subprocess.run(['osascript', '-e', script])`
- macOS only — fails gracefully on other platforms (osascript not found)

## Implementation Notes

Ported from `quarto4sbp` (`cmd_pdf`, `cmd_pdf_pptx`, `cmd_pdf_docx`). The
`cmd_*(args)` entrypoint shape was superseded by
[S35](S35-argparse-cli-parsing.md)'s `register(subparsers, parents)` convention;
the three modules now expose `register()` and `_run_*` handlers in
`src/mdd/commands/pdf*.py`.
