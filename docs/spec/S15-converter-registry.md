# 015 - Converter registry

**Purpose:** Promote the implicit extension-dispatch logic in `mdd convert` into an explicit, importable registry under `src/mdd/converters/`.

**Status:** Implemented (2026-05-08)

## Introduction

This spec refactors the existing internal surface — no new user-facing command. The registry unblocks attachment conversion in Confluence sync ([S16](S16-confluence-attachment-conversion.md)), SVG rasterization ([S24](S24-svg-rasterization.md)), and SharePoint sync ([S18](S18-sharepoint-sync.md)) — all of which need to call the same "convert this file to its markdown form" logic from outside the `convert` command.

Originates from research note R02 (attachments).

## Requirements

- Define a `Converter` protocol with `extensions: tuple[str, ...]`,
  `output_suffix: str`, and `convert(src, *, dest=None) -> ConvertResult`.
- Define `ConvertResult` carrying `output_path`, `attachments_dir`,
  `metadata` (frontmatter dict), and `warnings`.
- Maintain a module-level dict `CONVERTERS: dict[str, Converter]`
  keyed by lowercased extension (including leading dot).
- Public helper `converter_for(path: Path) -> Converter | None`
  returns the converter for the path's extension, or `None`.
- `mdd convert` ([S03](S03-convert-command.md)) is refactored to
  call `converter_for(path).convert(...)` instead of dispatching on
  extension internally.
- Behaviour and output of `mdd convert` is unchanged after the
  refactor — same files in, same files out, same exit codes.

**Reverse converters** (markdown → office) are also part of the
registry shape, but populated only when their target specs land:

- `ReverseConverter` protocol with `target_extension: str` and
  `render(md_path, *, dest) -> RenderResult`.
- `REVERSE_CONVERTERS: dict[str, ReverseConverter]` keyed by target
  extension.

Implementations land in [S17](S17-confluence-office-publishing.md)
(Quarto-based `.md → .docx`/`.pptx`); none in this spec.

## Design Approach

- `extensions` is a tuple of `.lowercase` extensions including the
  leading dot. Multiple are allowed (e.g. an HTML converter could
  claim `(".html", ".htm")`).
- `output_suffix` is the suffix appended to the *full* source name
  (e.g. `".md"` so `Foo.docx → Foo.docx.md`). For converters that
  produce a different terminal extension (e.g. `.svg → .svg.png`),
  the suffix encodes the full doubled form.
- `convert(src)` writes its output and returns metadata; it does not
  return content. Callers use `ConvertResult.output_path` to find the
  result.
- `attachments_dir` on the result points at any directory the
  converter populated with embedded media (or `None`).
- `metadata` is the dict that becomes YAML frontmatter on the output;
  the converter writes it itself, but returns it for callers who want
  to merge / inspect. `warnings` are human-readable strings; no
  severity levels.
- `CONVERTERS` is a plain dict, populated by each converter module
  registering itself. `converter_for(path)` does
  `CONVERTERS.get(path.suffix.lower())`. Returns `None` for unknown
  types so callers can decide how to handle them (skip, copy through,
  error). Lookup is case-insensitive on the file's extension.
- Existing `.docx` conversion logic moves out of
  `src/mdd/commands/convert.py` into `src/mdd/converters/docx.py`
  (Docling + python-docx). The command becomes a thin walker that
  calls `converter_for(path).convert(...)` and manages incremental
  skip / `--force` / `--dry-run` / progress output.
- The CLI surface of `mdd convert` is unchanged. Imports of internal
  symbols from `mdd.commands.convert` may break for out-of-tree
  callers; none are known.

## Related upstream specs

- [003-convert-command](S03-convert-command.md) — the command being refactored
- [016-confluence-attachment-conversion](S16-confluence-attachment-conversion.md) — consumer of the registry
- [017-confluence-office-publishing](S17-confluence-office-publishing.md) — populates reverse converters
- [018-sharepoint-sync](S18-sharepoint-sync.md) — consumer of the registry
- [024-svg-rasterization](S24-svg-rasterization.md) — consumer of the registry

## Out of scope

- Adding new converters (each gets its own spec).
- A general-purpose plugin protocol for third-party converters.
  Internal registry only — adding `.xlsx` is editing one file in
  `src/mdd/converters/`.
- Async or streaming converter contracts. All converters are
  synchronous and operate on filesystem paths.
