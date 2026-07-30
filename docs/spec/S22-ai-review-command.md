# 022 - ai review command

**Purpose:** `mdd ai review` runs cross-page checks on a mirror's markdown content and produces a structured report listing candidates for human action.

**Status:** Implemented (2026-05-09)

## Introduction

Three sub-modes (`--duplicates`, `--inconsistencies`, `--stale`) can be run individually or together via `--all`.

The report is itself a markdown file under `docs/review/` (or a
similar configured path). It gets committed by the user as part of
the review workflow; subsequent reports stay in git history.

Originates from research note R03.

## Requirements

- `mdd ai review` must support `--duplicates`, `--inconsistencies`, `--stale`, and `--all` sub-modes
- Each sub-mode follows a two-tier pipeline: cheap BM25 shortlist followed by LLM judge
- `--space` / `--site` / `--source TYPE:ID` scope filter must be supported for all sub-modes
  (the same registered root sources as [S19](S19-search-command.md))
- Default report path: `docs/review/<YYYY-MM-DD>-<scope>.md`; `--output <path>` overrides
- Existing report files must not be overwritten; append a numeric suffix
- Report must be plain markdown with anchors
- `--all` must share the BM25 index across sub-modes (computed once)
- Cache keys must include both file hashes, prompt template hash, model id, mdd version, and sub-mode

## Design Approach

**Two-tier pipeline.** Every sub-mode follows the same shape:

1. **Cheap shortlist** — BM25 over markdown bodies finds the top-K
   candidates per page. No API calls; high-recall pairs that
   *might* matter.
2. **LLM judge** — for each shortlisted pair (or, in stale-mode,
   each stale candidate's shortlist), call the model with a
   sub-mode-specific strict-JSON prompt. Filter to high-signal
   results.

Default `top-k` is 5. `--similarity 0.85` for duplicates only
filters the BM25 shortlist *before* LLM judging.

**BM25.** Uses `rank-bm25`; tokenises on word boundaries,
lowercases, strips frontmatter and code blocks. Index built once
per `--all` invocation, in-memory only. Sub-second for typical
mirror sizes (hundreds to low-thousands of pages).

**Concurrency and caching.** LLM calls go through [spec
020](S20-litellm-ai-client.md)'s client — concurrency cap of 4,
disk cache. Cache keys include both file hashes, prompt template
hash, model id, mdd version, and sub-mode, so reruns on unchanged
content are free.

## Subcommands

```
mdd ai review --duplicates       [--space SPACE] [--similarity 0.85] [--top-k 5]
mdd ai review --inconsistencies  [--space SPACE] [--top-k 5]
mdd ai review --stale            [--space SPACE] [--age 365]
mdd ai review --all              [--space SPACE]
```

`--space` may also be `--site`, or `--source TYPE:ID` for any
registered root source; pluralizable per mirror class.

## `--duplicates`

**Goal:** Find pages that substantially overlap in content.

BM25 shortlist → filter by `--similarity` → ask the model to
classify overlap (`high|medium|low|none`) and suggest an action.
Results with `overlap: high` are rendered as report entries.

**Report output (excerpt):**
```markdown
## Likely duplicates

### `Engineering/Onboarding.md` ↔ `Engineering/New Hire Setup.md`

**Overlap:** high

**Shared sections:** laptop provisioning, IT portal access

**Suggested action:** keep `New Hire Setup.md` as canonical; add a
deprecation note + redirect link from `Onboarding.md`, or merge
sections into the canonical page.
```

## `--inconsistencies`

**Goal:** Find pairs of pages that contradict each other on a
factual claim.

Same BM25 shortlist as duplicates; stricter judge prompt asking
for explicit contradicting quotes. High false-positive rate
(wording differences, version drift) — the output is *triage
material* for humans, not action items.

**Report output (excerpt):**
```markdown
## Possible inconsistencies

### `Process/Deployment.md` and `Platform/Deployment.md`

- **Issue:** disagreement on default rollout strategy.
  - `Process/Deployment.md`: "blue-green is the default."
  - `Platform/Deployment.md`: "canary is the default for production."
- **Resolution suggestion:** confirm with platform team; pick one
  canonical statement and update the other page.
```

## `--stale`

**Goal:** Find pages that look superseded by newer content.

Heuristic shortlist (pages older than `--age` days, or with
old-looking "as of" / "last reviewed" date strings); for each
stale candidate, BM25-shortlist its top-K newer neighbours; ask
the model whether any newer page replaces it.

**Report output (excerpt):**
```markdown
## Stale content

### `Tech/Old Deployment Runbook.md`

- Last updated 2022-03-12 (older than 365 days)
- **Likely superseded by:** `Platform/Deployment.md` (updated 2026-04-08)
- **Evidence:** the new page covers the same six steps with updated
  tooling references.
- **Suggested action:** archive on Confluence (set `status:
  ARCHIVED` per [S14](S14-confluence-sync.md)); add redirect note pointing at the
  newer page.
```

## `--all`

Runs all three sub-modes, sharing the BM25 index across them
(computed once). Output report has three sections.

## Report file

- Default path: `docs/review/<YYYY-MM-DD>-<scope>.md` relative to
  the current directory.
- `--output <path>` overrides.
- Existing files at the target path are not overwritten; a numeric
  suffix is appended.
- Plain markdown with anchors so review tools / agents can cite
  specific findings.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [020-litellm-ai-client](S20-litellm-ai-client.md) — LLM client with concurrency cap and caching
- [021-ai-rewrite-and-index](S21-ai-rewrite-and-index.md) — ai command dispatcher that review extends
- [014-confluence-sync](S14-confluence-sync.md) — Confluence archive status referenced in stale report output

## Out of scope

- Acting on findings automatically. The report is human-reviewed;
  the user (or a follow-up agent invocation) decides what to do.
- Cross-mirror review (e.g. duplicates spanning Confluence and
  SharePoint). Useful but adds complexity; deferred until intra-
  mirror review proves valuable.
- Embedding-based similarity. Deferred per research note R03; revisit
  if BM25 quality limits review usefulness.
- Continuous review (cron job that re-runs on schedule). Spec is
  on-demand only; cron lives outside `mdd`.
