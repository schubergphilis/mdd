# S36: Module structure and file-size shape

**Purpose:** Convert each `src/mdd/` file that exceeds ~500 lines into a cohesive sub-package, and document the file-shape heuristic that keeps modules reviewable as the codebase grows.

**Status:** Implemented (2026-05-16)

## Introduction

[S34](S34-code-quality-gates.md) enforces per-function structural
metrics (cyclomatic complexity, statement count, branch count, argument
count). Those gates push large monolithic functions into many smaller
ones — but they say nothing about *where* the smaller functions live.
The result is that an S34 refactor pass often grows the host file: it
trades one monster function for several small ones plus their helpers.

S36 is the companion gate: when a file crosses the readability ceiling,
split it into a package whose sub-modules group functions by topic.
This keeps file length a useful proxy for reviewability without
introducing a brittle machine-checked cap.

## Requirements

- Files in `src/mdd/` should be ≤300 lines as a target, with 500 as a
  soft ceiling. Files above the ceiling either split per this spec or
  carry an inline `# S36-exception: <reason>` comment near the top.
- Sub-packages follow the file-becomes-package pattern described in
  [Design Approach](#design-approach): a thin `__init__.py` exposing
  the public API, and sibling modules grouped by topic.
- Symbol names are free to change in a split PR if a cleaner name
  emerges. There is no public-API compatibility constraint pre-1.0.
- No re-export shims, alias modules, or `# moved to ...` markers
  outlive a single split PR. Callers are updated in the same change.
- No file-length lint rule is introduced. File length stays a
  heuristic; per-function metrics from S34 remain the
  machine-checked surface.
- Test files are split alongside their target module's package (in
  separate PRs but as part of the same rollout).

## Design Approach

### File length is a heuristic, not a gate

Target ≤300 lines per file. Above 500, split or carve out an
exception. Below ~50, prefer inlining into a sibling — a file that
small rarely earns its own import boundary.

Reasons a file may legitimately stay >500:

- **Dense dispatch tables** where splitting would scatter a coverage
  matrix across files (e.g. a tag-to-handler map for an XML element
  set).
- **A single class with mutually-coupled methods** where extracting
  helpers would require exposing private state via parameters.
- **Generated code** (not currently present in `src/mdd/`).

If a file qualifies, mark it with:

```python
# S36-exception: <one-line reason>
```

near the top. The comment is the documentation; no central registry.

### File becomes package

```
mdd/x.py  →  mdd/x/
    __init__.py            # public surface: entry points + class exports
    <topic_a>.py
    <topic_b>.py
    ...
```

`__init__.py` is **thin**: the public entry points and any dominant
public class live here, plus imports from sibling modules. It is not a
re-export bag for everything the old module exposed. Callers import
non-public helpers from the new sub-module directly, not from the
package root.

When a single public class dominates the file (the `ConfluenceClient`
case), the class lives in `__init__.py`; its module-level helpers move
to siblings.

### Naming

- Sub-package directories use the original file's name without suffix.
  `sync.py` → `sync/`, not `syncing/` or `sync_pkg/`.
- Sub-module file names are lowercase nouns describing the topic.
  `pull.py`, not `pulling.py`; `entities.py`, not
  `entity_handling.py`.
- Private-helper module names do not need an underscore prefix — the
  package boundary is the encapsulation surface.

### Target shapes

The eleven files >500 lines on `main` and their target package shapes.
Detailed symbol-by-symbol assignments and PR sequencing live in the
implementation plan; this section fixes the *topic boundaries*.

`confluence/sync.py` (1184) → `confluence/sync/` with sub-modules for:
desired-state queries, local-edit detection, office-publish flow,
rename/move/archive application, pull, push, deletion application,
finalize (commit / refresh metadata / push the mirror), and event
classification. `__init__.py` exposes `sync_space`, `SyncOptions`,
`SyncSummary`.

`confluence/ir/writer.py` (1023) → `confluence/ir/writer/` with
sub-modules for: entities and text preservation, block renderers, code
blocks, tables, layouts, inline renderers, link rendering, and macro
rendering. `__init__.py` exposes `render_confluence_storage`.

`markdown/ir/reader.py` (808) → `markdown/ir/reader/` with sub-modules
for: blocks, listings, tables, layouts, inlines, and macros.
`__init__.py` exposes `parse_markdown`.

`confluence/client.py` (800) → `confluence/client/` with `__init__.py`
holding the `ConfluenceClient` class, and sibling modules for: HTTP
logging helpers, retry/backoff helpers, path validation, and the
`ConfluenceError` exception.

`sharepoint/apply.py` (683) → `sharepoint/apply/` with sub-modules
for: apply actions, sync-block injection, file I/O, conversion, git
commit, and dry-run reporting. `__init__.py` exposes `PairResult`,
`SyncRunSummary`, and the `apply_*` entry points.

`confluence/attachments.py` (597) → `confluence/attachments/` with
sub-modules for: sync-all-attachments flow, per-page download flow,
incremental update flow, and reference scanning. `__init__.py` exposes
`AttachmentCollisionError`, the manifest/summary dataclasses, and the
public entry points.

`confluence/managed.py` (596) → `confluence/managed/` with sub-modules
for: configuration loading, page classification, and managed-page
headers/warnings. `__init__.py` exposes the public configuration and
classification API.

`markdown/ir/writer.py` (595) → `markdown/ir/writer/` with sub-modules
for: blocks, tables, inlines, and escape helpers. `__init__.py`
exposes `render_markdown`.

`confluence/ir/elements.py` (594) → `confluence/ir/elements/` with
sub-modules for: block elements, list elements, table elements, and
inline elements. `__init__.py` exposes `is_block_tag` and
`read_blocks_from_container`.

`ir/normalize.py` (560) → `ir/normalize/` with sub-modules for: the
map/filter scaffolding, whitespace passes, list passes, entity
decoding, callout extraction, and attribute passes. `__init__.py`
exposes the public `normalise` composition entry point.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [S34](S34-code-quality-gates.md) — per-function structural gates
  whose refactor pass drives the file-length growth this spec
  addresses.
- [S35](S35-argparse-cli-parsing.md) — independently rewrote
  `commands/confluence.py`; that rewrite brought it under the ceiling
  (651 → 435 lines), so this spec no longer covers it.

## Open questions

1. Should a follow-on `mise run lint-file-shape` advisory list files
   above the ceiling lacking an `# S36-exception:` marker? Not for
   now — review is sufficient. Revisit if regressions reappear after
   the S36 wave lands.
2. (Resolved) Sub-modules under ~50 lines are inlined into a sibling
   rather than kept as their own file.

## Out of scope

- File-length lint rules. File length stays a heuristic; per-function
  gates are the machine-checked surface.
- Cognitive-complexity tooling (complexipy / lizard). Orthogonal to
  module structure.
- Architectural import-graph enforcement (`tach`, `import-linter`).
  The `src/mdd/` layout is already reasonably layered; formalising
  boundaries is a separate decision.
- Splitting `ConfluenceClient` itself. The class moves into
  `confluence/client/__init__.py` intact; an internal split of the
  class by responsibility is a follow-up if its length is still a
  problem after the helpers have moved out.
