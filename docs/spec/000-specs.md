# 000 — Specs

This document is the entry point for the MDD specifications.

Use the `/spec-extension` skill to add new specs.

## Spec index

Run `uv run python scripts/spec-list.py` to recreate this overview:

| # | Title | Purpose | Status |
|---|-------|---------|--------|
| S01 | [Spec-Based Development](S01-spec-based-development.md) | Document new features in structured specs before implementation to ensure consistency and enable design review | Implemented (2026-05-07) |
| S02 | [mdd CLI Tool](S02-mdd-cli-tool.md) | A unified `mdd` CLI dispatcher that routes subcommands to command modules. | Superseded by [S35](S35-argparse-cli-parsing.md) (2026-05-16) |
| S03 | [convert command](S03-convert-command.md) | `mdd convert` recursively converts `.docx` files to Markdown (`.docx.md`) using Docling for body content and python-docx for metadata extraction. | Implemented (2026-05-07) |
| S04 | [new / new-pptx / new-docx commands](S04-new-command.md) | Scaffold new Quarto projects from bundled templates. | Implemented (2026-05-07) |
| S05 | [pdf / pdf-pptx / pdf-docx commands](S05-pdf-export.md) | Export Office files to PDF via AppleScript (macOS only). | Implemented (2026-05-07) |
| S07 | [data protection](S07-data-protection.md) | Two cross-cutting rules that protect the organisation's data and credentials for every command. | Implemented (2026-05-19) |
| S09 | [confluence command](S09-confluence-command.md) | `mdd confluence` adds Confluence Cloud integration for exporting, creating, and updating pages. | Implemented (2026-05-08) |
| S10 | [sharepoint command](S10-sharepoint-command.md) | `mdd sharepoint` mirrors SharePoint sites to Markdown by reading locally synced files (via OneDrive), without ever calling the SharePoint API. | Implemented (2026-05-08) |
| S11 | [convert pptx](S11-convert-pptx.md) | Extend `mdd convert` to handle `.pptx` input, producing `<name>.pptx.md` output for round-trip with Quarto presentation projects. | Implemented (2026-05-08) |
| S14 | [confluence sync command](S14-confluence-sync.md) | `mdd confluence sync` is the primary bidirectional verb for keeping a git mirror repo in lockstep with its Confluence space. | Implemented (2026-05-08) |
| S15 | [Converter registry](S15-converter-registry.md) | Promote the implicit extension-dispatch logic in `mdd convert` into an explicit, importable registry under `src/mdd/converters/`. | Implemented (2026-05-08) |
| S16 | [Confluence attachment conversion (pull-side)](S16-confluence-attachment-conversion.md) | Extend `mdd confluence sync` and `export` so non-image attachments are run through the converter registry, producing markdown siblings. | Implemented (2026-05-08) |
| S17 | [Confluence office publishing (push-side)](S17-confluence-office-publishing.md) | Render opted-in markdown pages to `.docx`/`.pptx` via Quarto and upload them as versioned Confluence attachments. | Implemented (2026-05-09) |
| S18 | [sharepoint sync command](S18-sharepoint-sync.md) | Bidirectional sync between `.md`/`.qmd` and `.docx`/`.pptx` in SharePoint sites mirrored via OneDrive, without office-format diff/merge. | Implemented (2026-05-09) |
| S19 | [search command](S19-search-command.md) | `mdd search "<query>"` is a thin ripgrep wrapper that searches markdown across all configured mirror locations. | Implemented (2026-05-08) |
| S20 | [LiteLLM AI client and caching infrastructure](S20-litellm-ai-client.md) | Establish a shared `mdd.ai` package wrapping a LiteLLM gateway with uniform retry, concurrency, and caching. | Implemented (2026-05-08) |
| S21 | [ai rewrite and ai index commands](S21-ai-rewrite-and-index.md) | Two user-facing AI commands built on the S20 client: `mdd ai rewrite` and `mdd ai index`. | Implemented (2026-05-08) |
| S22 | [ai review command](S22-ai-review-command.md) | `mdd ai review` runs cross-page checks on a mirror's markdown content and produces a structured report listing candidates for human action. | Implemented (2026-05-09) |
| S23 | [Agent skills bundle and skills command](S23-skills-bundle.md) | Bundle Claude Code skills with `mdd` so agents can discover when and how to drive `mdd` reliably. | Implemented (2026-05-09) |
| S24 | [SVG sibling rasterization](S24-svg-rasterization.md) | Keep a high-quality `<name>.svg.png` sibling next to every `.svg` file in a mirror, refreshed automatically when the source changes. | Implemented (2026-05-08) |
| S26 | [Externally-managed Confluence pages](S26-managed-elsewhere.md) | Detect Confluence pages maintained by external automation and block `mdd` pushes; pull/export remains allowed. | Implemented (2026-05-09) |
| S27 | [confluence page rename / move / archive](S27-confluence-page-rename-move-archive.md) | Imperative `mdd` subcommands (`rename`, `move`, `archive`, `unarchive`) that mutate a Confluence page then refresh the local mirror. | Implemented (2026-05-23) |
| S28 | [Document Intermediate Representation (foundation)](S28-document-ir-foundation.md) | Typed, in-process Python IR for documents supporting bidirectional Confluence ↔ markdown sync with identity, provenance, and JSON serialization. | Implemented (2026-05-13) |
| S29 | [Confluence storage XHTML ↔ IR conversion](S29-confluence-ir-conversion.md) | Map Confluence storage XHTML to and from the document IR defined in [S28](S28-document-ir-foundation.md). | Implemented (2026-05-13) |
| S30 | [Markdown ↔ IR conversion](S30-markdown-ir-conversion.md) | Map markdown to and from the document IR, with 100% flavour coverage and a documented fallback policy. | Implemented (2026-05-13) |
| S31 | [IR normalization and whitespace preservation](S31-ir-normalization-and-whitespace.md) | Define normalising and preserving modes for IR converters, where both modes share the same IR but differ in reader metadata and writer behaviour. | Implemented (2026-05-13) |
| S32 | [IR test corpus expansion](S32-ir-test-corpus-expansion.md) | Expand `mdd/test-confluence/MDD` to a complete coverage matrix of every non-deprecated Confluence storage shape and markdown construct. | Implemented (2026-05-13) |
| S33 | [IR roundtrip testing and benchmarks](S33-ir-roundtrip-testing-and-benchmarks.md) | Define the test surface and performance gates the IR and its converters must pass before promotion to default for `mdd confluence`. | Implemented (2026-05-13) |
| S34 | [034 — Code Quality Gates](S34-code-quality-gates.md) | Define the static-analysis rule set, complexity thresholds, and grandfathering policy that `mise run lint` enforces, so future iterations (human and agent) cannot let function size, branchiness, or argument bloat regress unnoticed. | Implemented (2026-05-15) |
| S35 | [Argparse-based CLI parsing](S35-argparse-cli-parsing.md) | Replace the home-grown flag-parsing helpers and `while i < len(args):` loops in `src/mdd/commands/` with `argparse`, deleting the bespoke `_FlagSpec` framework. Amended 2026-05-24 with the typed-Namespace adapter convention (per-handler `Namespace` subclass + `cast`). | Implemented (2026-05-16) |
| S36 | [Module structure and file-size shape](S36-module-structure.md) | Split the eleven `src/mdd/` files >500 lines into cohesive sub-packages so file length stays manageable after the S34 per-function refactors land. | Implemented (2026-05-16) |
| S37 | [Complexipy cognitive complexity](S37-complexipy-cognitive-complexity.md) | Add cognitive-complexity as a second structural gate alongside ruff's McCabe, using `complexipy` with a snapshot watermark for grandfathering. | Implemented (2026-05-18) |
| S38 | [SharePoint test corpus](S38-sharepoint-test-corpus.md) | Vendor a local mirror of the `MDD` SharePoint site as a test corpus alongside the existing Confluence corpus, and reshape `tests/corpus/` to host both. | Implemented (2026-05-20) |
| S39 | [`.mddignore` source-side filtering](S39-mddignore.md) | A `.gitignore`-style file (and matching `--ignore=<path>` flag) that filters source content before download/conversion in `mdd` sync commands, with a single shared matcher consumed by sharepoint/confluence/lucid. | Implemented (2026-05-24) |
| S40 | [Typed frontmatter layer](S40-typed-frontmatter.md) | Replace the ~5 per-module hand-rolled YAML/JSON coercer kits with a single typed pydantic v2 layer (`extra="forbid"`, flexible type coercion), deleting a class of silent-failure bugs in hand-edited frontmatter. | Implemented (2026-05-24) |
| S42 | [Image extraction and optimization](S42-image-extraction-and-optimization.md) | Records the shared `convert/images.py` image-writer policy (content-addressing, TIFF→JPEG, WMF/EMF→PNG, 4k cap) and adds lossless PNG re-optimization on write, keeping the smaller of original/re-encoded bytes. Office-conversion path only; excludes Confluence's byte-exact attachment mirror. | Implemented (2026-05-29) |

## Naming scheme

Spec files use the `SNN-<slug>.md` form (e.g. `S07-data-protection.md`).
Numbers are assigned in order, starting at 1, zero-padded to two digits.
Plans live under `docs/plan/` with a `PNN-` prefix and research notes
under `docs/research/` with an `RNN-` prefix.

## Existence check before adding a new spec

Before writing a new spec, confirm the system or feature does not already exist:

```sh
ls docs/spec/
find src/mdd -maxdepth 2 -type d
```

If a system or feature already exists, amend its existing spec rather than starting a new one.

## How to add a new spec

Use the `/spec-extension` skill. It helps with these steps and more:

1. **Run the existence check** (see above) — search `docs/spec/` and `src/mdd/` before opening a new file.

2. **Scaffold with `mise run new-spec <slug>`**.
   This picks the next free number and writes a scaffolded file:

   ```bash
   mise run new-spec my-feature
   # prints: docs/spec/S34-my-feature.md
   ```

3. **Append a row to the spec index** in this file (above).

4. **Commit** with a `docs(spec):` prefix. Docs-only commits skip `mise run ci`.

## Cross-reference convention

Use **relative links**, not bare spec numbers.

**Do:**
```markdown
See [data protection](S07-data-protection.md) for the blacklist gate.
See [confluence sync](S14-confluence-sync.md) for the reconciliation algorithm.
```

**Don't:**
```markdown
See S07 for the blacklist gate.
See S14 for the reconciliation algorithm.
```

When prose requires a bare number (e.g. in a table row), keep the link: `[S07](S07-data-protection.md)`.

Spec files MUST NOT link to or name-reference `docs/plan/` (PNN) or
`docs/research/` (RNN) artefacts. Plans and research notes are
working / process documents; specs are the durable design record.
Copy any relevant content into the spec instead of linking out.

## Status convention

The `**Status:**` line near the top of each spec uses one of these forms:

- `Draft` — design still in flux.
- `In progress — <short description>` — partial implementation; describe what
  has shipped and what is deferred.
- `Accepted — <short description>` — design accepted but no code (e.g.
- `Implemented (YYYY-MM-DD)` — feature has shipped. The date is the commit
  date of the newest commit that landed the spec's implementation. Do
  not list commit shas, PR numbers, or rollout-plan references in the
  Status line — those belong in commit history. The matching row in the
  index above MUST mirror the same Status string.
- `Superseded by [SNN](SNN-slug.md) (YYYY-MM-DD)` — design has been
  replaced by a later spec. Keep the original file as historic record,
  add a short "Superseded" callout near the top pointing at the
  replacement, and mirror the same Status string in the index above.

`scripts/spec-check.py` enforces the `Implemented (YYYY-MM-DD)` shape. Any
deviation (commit shas, extra prose inside the parens) fails the check.

## Spec Template

Use [spec-template.md](./spec-template.md).
