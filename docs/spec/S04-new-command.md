# 004 - new / new-pptx / new-docx commands

**Purpose:** Scaffold new Quarto projects from bundled templates.

**Status:** Implemented (2026-05-07)

## Requirements

- `mdd new-pptx <dir>` creates a Quarto PowerPoint project
- `mdd new-docx <dir>` creates a Quarto Word project
- `mdd new <dir>` creates a project with both outputs
- Each creates: `<dir>/<dir>.qmd`, `<dir>/render.sh`, symlink(s) to reference template(s)
- Error if no directory name given or name starts with `-`

## Design Approach

- Commands in `src/mdd/commands/new*.py`; shared logic in `src/mdd/utils/scaffolding.py`
- Templates bundled at `src/mdd/templates/` — resolved relative to `__file__`
- `create_quarto_project()` is the shared helper
- `{{TITLE}}` in QMD templates is replaced with the base directory name
- `{{FILE_NAME}}` in render.sh.template is replaced with the base directory name

## Implementation Notes

Ported from `quarto4sbp` (`cmd_new`, `cmd_new_pptx`, `cmd_new_docx`). The
`cmd_*(args)` entrypoint shape was superseded by
[S35](S35-argparse-cli-parsing.md)'s `register(subparsers, parents)` convention;
the three modules now expose `register()` and `_run_*` handlers in
`src/mdd/commands/new*.py`.

## Template files

- `simple-presentation.{qmd,pptx}` — PowerPoint output
- `simple-document.{qmd,docx}` — Word output
- `combined-document.qmd` — both outputs from one source
- `render.sh.template` — shell script to render and export PDF
