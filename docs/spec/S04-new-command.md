# 004 - new / new-pptx / new-docx commands

**Purpose:** Scaffold new Quarto projects from bundled templates.

**Status:** Implemented (2026-05-07)

## Requirements

- `mdd new-pptx <dir>` creates a Quarto PowerPoint project
- `mdd new-pptx --compact <dir>` does the same against the compact reference
  template (18 / 16 / 14 / 12 pt body text instead of 28 / 24 / 20 / 18 pt)
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
- `simple-presentation-compact.{qmd,pptx}` — PowerPoint output, compact scale
- `simple-document.{qmd,docx}` — Word output
- `combined-document.qmd` — both outputs from one source
- `render.sh.template` — shell script to render and export PDF

## Compact presentation template

The default slide master runs a 28 / 24 / 20 / 18 pt body scale, which
overflows on dense slides (a table plus a few bullets). Rather than shrink the
default and reflow every existing deck, `--compact` selects a second bundled
reference template at 18 / 16 / 14 / 12 pt. The default stays pixel-stable.

- `simple-presentation-compact.pptx` is byte-identical to
  `simple-presentation.pptx` apart from nine `sz` attributes in
  `ppt/slideMasters/slideMaster1.xml`'s `<p:bodyStyle>`: levels 1-4 become
  `1800` / `1600` / `1400` / `1200`, and levels 5-9 follow level 4 at `1200`
  (the default already pins 5-9 to level 4). The `4400` title in
  `<p:titleStyle>`, the `1800` `<p:otherStyle>` default, the `1200`
  date/footer/slide-number placeholders, the `1000` disclaimer textbox and
  every `ppt/slideLayouts/*.xml` override are untouched.
- `scripts/derive-compact-pptx.py` regenerates the binary from the default
  (`--check` asserts the committed copy is up to date), so the change stays
  reviewable instead of arriving as an opaque blob. It rezips in the original
  entry order with the original compression, `[Content_Types].xml` first,
  because a naively rebuilt archive triggers PowerPoint's repair dialog.
- Selection is front-matter only: the scaffolded `.qmd` sets
  `reference-doc: simple-presentation-compact.pptx` and `create_quarto_project`
  symlinks that name into the project. No converter change is needed —
  `mdd.converters.quarto` only passes `--reference-doc` on the
  [S17](S17-confluence-office-publishing.md) publish path, which uses its own
  `templates/quarto/reference.pptx`.
- `mdd new` (both outputs) and `mdd new-docx` keep a single template each; the
  compact variant is a presentation-only concern.
