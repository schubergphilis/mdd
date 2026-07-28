---
name: mdd-review-skill
description: |
  How to invoke `mdd ai review` for cross-page content quality checks;
  how to summarise findings for the user without acting on them automatically.
---

## When to use

Trigger this skill when the user asks to:

- Find duplicate or near-duplicate pages in a markdown mirror
- Identify pages with contradictory or inconsistent factual claims
- Find stale pages that have been superseded by newer content
- Run a general content quality audit on a mirror directory

## When NOT to use

- The user wants the agent to automatically fix the issues found; review
  produces a report only — acting on findings requires explicit user direction.
- The mirror directory is very large (thousands of pages) and the user has not
  set a tight `--top-k` or `--similarity` threshold; warn about potential cost.
- Cross-mirror review (comparing two separate sites) is not yet supported;
  `mdd ai review` is intra-mirror only.

## Common flows

**Check for duplicate pages**:
```
mdd ai review docs/ --duplicates
```

**Check for inconsistencies**:
```
mdd ai review docs/ --inconsistencies
```

**Check for stale content** (pages not updated in over a year):
```
mdd ai review docs/ --stale
mdd ai review docs/ --stale --age 180   # use 180-day threshold instead
```

**Run all checks in one pass** (shares one BM25 index — most efficient):
```
mdd ai review docs/ --all
```

**Custom output path**:
```
mdd ai review docs/ --all --output reports/my-review.md
```

**Summarising findings to the user**:
1. Show the report path produced by `mdd ai review`.
2. Summarise the top findings (highest-overlap pairs, most contradictory pages,
   oldest stale entries).
3. Ask the user which findings they want to act on before making any edits.
4. Never auto-apply fixes — each finding requires a deliberate decision.

**Key flags**:
- `--duplicates` — find pages with substantially overlapping content
- `--inconsistencies` — find pairs with contradictory factual claims
- `--stale` — find pages superseded by newer content
- `--all` — run all three modes (shared BM25 index)
- `--similarity 0.85` — min BM25 score for duplicate shortlist
- `--top-k 5` — BM25 candidates per page
- `--age 365` — age threshold in days for stale detection
- `--output <path>` — write report here instead of `docs/review/`
- `--model MODEL` — override the default model

For full parameter detail: `mdd ai review --help`
