# 033 - IR roundtrip testing and benchmarks

**Purpose:** Define the test surface and performance gates the IR and its converters must pass before promotion to default for `mdd confluence`.

**Status:** Implemented (2026-05-13)

## Introduction

This spec defines the round-trip flavours (R1, R2, R3), CI gates, benchmark thresholds, and promotion criteria that the IR ([S28](S28-document-ir-foundation.md)) and its converters ([S29](S29-confluence-ir-conversion.md), [S30](S30-markdown-ir-conversion.md)) must satisfy before the `--ir pure-python` opt-in can become the default for `mdd confluence`.

## Requirements

- Three distinct round-trip flavours (R1, R2, R3) must each be gated separately in CI.
- R1 (Storage → IR → Storage): byte-perfect in preserving mode; M1 ≥ 0.995 per fixture in normalising mode.
- R2 (Markdown → IR → Markdown): structural IR equality in normalising mode; byte-equality in preserving mode for fixtures that opt in.
- R3 (Storage → IR → Markdown → IR → Storage): byte-perfect in preserving mode for unmodified content; M1 ≥ 0.995, M2 ≥ 0.97, M3 = 1.0, M4 = 1.0 in normalising mode with per-fixture floor M1 ≥ 0.95.
- CI must fail on any R1/R2/R3 gate miss, any coverage gap per [S32](S32-ir-test-corpus-expansion.md), and any unexpected `FallbackEmitted` event.
- Benchmark gates: full-corpus R3 ≤ 200ms, median per-fixture R3 ≤ 5ms, 95th-percentile per-fixture R3 ≤ 20ms.
- Promotion criteria must be met before the IR becomes the default for `mdd confluence`.

## Design Approach

- The R1/R2/R3 round-trip suite lives under `tests/ir/` and runs against the vendored corpus at `tests/corpus/`.
- Add `mise run ir-roundtrip`, `mise run ir-roundtrip-quick`, `mise run ir-roundtrip-bench`, and `mise run ir-coverage` tasks.
- Wire `ir-roundtrip` (full flavour suite) and `ir-coverage` into `mise run ci`.
- R1/R3 byte-perfect gate runs only against `_snapshots/` tier fixtures; `--live` tier remains manual until a green-CI baseline exists.
- Benchmarks run the harness three times and take the median per fixture to reduce noise; skipped in `--quick` mode.
- Per-fixture failure produces a side-by-side HTML diff under `build/ir-diffs/<fixture>.html`.
- Tests are parametrised over every applicable fixture; corpus is vendored under `tests/corpus/` and always present.

## Implementation Notes

- Test files live under `tests/ir/` (see layout below).
- `conftest.py` returns the hardcoded corpus root at `tests/corpus/`. Vendored as ordinary repo content; CI sees it like any other test fixture.
- New build outputs: `build/ir-coverage.json`, `build/ir-benchmarks.json`, `build/ir-roundtrip.html`; CI uploads them as artifacts.
- Promotion to default is a one-line config change; legacy converters can then be removed in the following release per [S29](S29-confluence-ir-conversion.md) "Backwards compatibility".
- If benchmark gates flake, raise the ceiling — do not disable the gate.

## Roundtrip flavours

Three distinct round-trips, each gated separately because each
catches a different class of regression:

### R1 — Storage → IR → Storage (Confluence-only)

```
storage_xhtml → parse_confluence_storage → render_confluence_storage → storage_xhtml'
```

Gate: in preserving mode (with `reattach` from a cached IR),
`storage_xhtml' == storage_xhtml` byte-for-byte. In normalising
mode, M1 ≥ 0.995 per fixture.

This is the production push leg. Byte-perfect round-trip on
untouched content is what makes the merge engine safe.

### R2 — Markdown → IR → Markdown (markdown-only)

```
markdown → parse_markdown → render_markdown → markdown'
```

Gate: `parse_markdown(markdown') == parse_markdown(markdown)`
(structural equality on the IR). Byte-equality of `markdown'`
to `markdown` is not required in normalising mode (the writer
canonicalises spacing) but IS required in preserving mode for
fixtures that opt in.

This catches CommonMark / GFM corner cases that don't involve
Confluence at all. Runs against the markdown-first fixtures from
[S32](S32-ir-test-corpus-expansion.md).

### R3 — Storage → IR → Markdown → IR → Storage (full bidirectional)

```
storage → parse_confluence_storage → IR_a
       → render_markdown → markdown
       → parse_markdown → IR_b
       → reattach(IR_b, cached=IR_a)
       → render_confluence_storage → storage'
```

Gate (preserving mode): `storage' == storage` byte-for-byte for
unmodified content. This is the round-trip the sync loop performs
when the user did not edit the markdown between pulls and pushes
— the most important guarantee in the system.

**Reattach is load-bearing in production, not just in tests.**
`mdd confluence update-page` already fetches the remote storage (for
the managed-page check and the diff display); it MUST re-use that
storage as the cached `IR_a` when rendering the local markdown back
to XHTML. Without the reattach step, every round-trip strips
identity attributes from layout / section / cell / macro / paragraph
nodes because the markdown leg intentionally does not carry them
(see [S29 §"Identity and round-trip guarantee"](S29-confluence-ir-conversion.md)
and [S30 §"Block-level inline shape"](S30-markdown-ir-conversion.md)).
The integration test
`tests/confluence/test_update.py::TestRoundTripReattach::test_unedited_export_is_a_no_op_push`
guards this — it mirrors the production `update_page` call shape
(no direct `reattach` access from the test) and asserts no PUT is
issued for an unedited export.

Gate (normalising mode): M1 ≥ 0.995, M2 ≥ 0.97, M3 = 1.0 (every
Confluence identity key — `ac:local-id`, `ac:macro-id`,
`ac:schema-version` — present on IR_a survives to the rendered
storage via reattach's "fresh wins, cached fills" graft of
`attributes`), M4 = 1.0 (every block has provenance), per-fixture
floor M1 ≥ 0.95 on every metric.

#### Documented carve-outs

- **Empty paragraphs with identity.** Markdown has no syntax for
  an empty paragraph carrying a `local-id` anchor, and we
  intentionally do not invent one. See [S30](S30-markdown-ir-conversion.md)
  §"Empty paragraphs with identity". The R3 gate is read
  modulo trailing empty-anchor paragraphs that have no visible
  content; corpus fixtures that exhibit the shape must be
  cleaned at the source (push corrected storage + refresh
  snapshot) rather than expecting the markdown leg to carry
  them.
- **Backslash escapes (`\*`, `\_`, …).** The markdown reader
  strips the backslash per CommonMark; storage holds the
  literal character. Restoring the backslash on the markdown
  write path is deferred (it needs a context-sensitive
  re-escape policy). Fixtures exercising this are xfailed
  on R3 preserving.
- **Inline `<kbd>`/`<samp>` raw HTML.** Allowlist gap in the
  markdown reader's raw-HTML handling — see [S32](S32-ir-test-corpus-expansion.md)
  §"Fallback fixtures".

## CI integration

A new mise task wires the harness into CI:

```bash
mise run ir-roundtrip            # all three flavours, default thresholds
mise run ir-roundtrip --quick    # R2 only, no benchmarks (under 5s)
mise run ir-roundtrip --bench    # adds benchmark gates (below)
mise run ir-coverage             # corpus coverage matrix (S32 gate)
```

`mise run ci` (the existing aggregate) gains `ir-roundtrip` (full
flavour suite) and `ir-coverage`. CI fails on:

1. Any of R1 / R2 / R3 missing the per-mode thresholds above.
2. Coverage gaps per [S32](S32-ir-test-corpus-expansion.md)
   (any IR node class / fallback path / CommonMark construct
   with zero fixtures).
3. Any `FallbackEmitted` event raised against a fixture not
   tagged `fallback: true` in its frontmatter. (Fallbacks are
   expected on `fallback/` fixtures; unexpected anywhere else.)

The R1 / R3 byte-perfect gate runs only against fixtures in the
captured `_snapshots/` tier. The `--live` tier (re-fetch from
markdown.atlassian.net) stays a manual operation until we have a
green-CI baseline to diff against.

## Benchmark gates

The harness already records wall-clock timing per direction per
fixture. Promote it to a gated metric:

| Gate | Threshold | Rationale |
|---|---|---|
| Full-corpus R3 round-trip (preserving) | ≤ 200ms | Baseline measured 31ms normalising / ~50ms preserving on local hardware; 200ms is a generous ceiling that catches regressions without flaking on slow CI runners. |
| Median per-fixture R3 round-trip | ≤ 5ms | Catches a pathological per-fixture regression even when the aggregate stays green. |
| 95th-percentile per-fixture R3 | ≤ 20ms | Longest baseline fixture was 3.6ms; 20ms is a 5× headroom. |

**Design goal (not a hard gate):** the IR JSON sidecar should
stay within ~10× the source markdown size on large fixtures so
`Origin.raw_bytes` blow-up (see
[S31](S31-ir-normalization-and-whitespace.md) §"`Origin.raw_bytes`
size cap") gets noticed. This was previously a hard gate
(`test_sidecar_size_ratio`) but the test was dropped: structural
overhead in the IR's `{"type": "Heading", ...}` shape dominates
on small fixtures (200-byte pages produce ~30× sidecars), and the
gate couldn't be made meaningful without restricting it to large
fixtures the corpus doesn't yet contain. Reviewers should still
eyeball sidecar sizes for new fixtures during corpus expansion.

Benchmark mode runs the harness three times and takes the median
(per fixture) of the three runs, then aggregates. This kills most
of the noise; the gates are calibrated against the spread we've
observed so they should not flake on normal CI hardware. If they
do flake, the right response is to raise the ceiling — not to
disable the gate.

Benchmarks are skipped in `--quick` mode. They run in the full
CI suite once per commit. They do not block local `mise run ci`
by default (they add ~10s), but a CI-only `--bench` flag opts
in.

## Test layout

```
tests/ir/
  test_node_equality.py         # frozen-dataclass invariants
  test_json_roundtrip.py        # to_json/from_json (S28)
  test_reattach.py              # identity.reattach (S28)
  test_fallback_contract.py     # RawBlock/RawInline (S28)
  test_normalize_passes.py      # each pass in isolation (S31)
  test_origin_preservation.py   # whitespace mode (S31)
  test_r1_storage_roundtrip.py  # R1 flavour
  test_r2_markdown_roundtrip.py # R2 flavour
  test_r3_full_roundtrip.py     # R3 flavour
  test_corpus_coverage.py       # S32 coverage gate
  test_benchmarks.py            # benchmark gates (R3 timings)
  conftest.py                   # corpus loader; fixture parametrisation
```

`test_r{1,2,3}_*.py` are parametrised over every applicable
fixture. Per-fixture failure produces a per-fixture diff (the
HTML side-by-side diff from the harness, dumped to
`build/ir-diffs/<fixture>.html`) for easy debugging.

`conftest.py` returns the hardcoded corpus root at
`tests/corpus/`. The corpus is vendored as ordinary repo content
so the suite runs identically on every checkout (dev machines,
CI runners, bot VM).

## Reporting

The harness's existing markdown / HTML reporters stay. New
outputs:

- `build/ir-coverage.json` — corpus coverage matrix (per
  [S32](S32-ir-test-corpus-expansion.md)).
- `build/ir-benchmarks.json` — per-fixture / aggregate timings.
- `build/ir-roundtrip.html` — full R1 / R2 / R3 report with
  side-by-side diffs per fixture.

CI uploads `build/ir-*.{json,html}` as artifacts. The dashboard
(if/when one exists for mdd) consumes the JSON; the HTML report
is the human-readable artefact for debugging.

## Promotion criteria

The IR moves from `--ir pure-python` opt-in to the default for
`mdd confluence` once:

1. All R1 / R2 / R3 gates green for two consecutive weeks.
2. Coverage gate green (zero shapes / constructs / fallback paths
   without a fixture).
3. Benchmark gates green for two consecutive weeks (no flake-
   driven raises in that window).
4. At least one whole-space sync run (`mdd confluence sync-space
   MDD`) round-trips clean under `--ir pure-python` against the
   live `markdown.atlassian.net` tenant.
5. A two-week A/B against the legacy path on a real space turns
   up zero unexpected diffs.

The default flip is a one-line config change at that point. The
legacy converters can then be removed in the following release
(per [S29](S29-confluence-ir-conversion.md) "Backwards
compatibility").

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [028-document-ir-foundation](S28-document-ir-foundation.md) — IR node types and identity model
- [029-confluence-ir-conversion](S29-confluence-ir-conversion.md) — Confluence storage ↔ IR converters
- [030-markdown-ir-conversion](S30-markdown-ir-conversion.md) — Markdown ↔ IR converters
- [031-ir-normalization-and-whitespace](S31-ir-normalization-and-whitespace.md) — normalisation passes and whitespace modes
- [032-ir-test-corpus-expansion](S32-ir-test-corpus-expansion.md) — corpus this runs against
