# S37: Complexipy Cognitive Complexity

**Purpose:** Add cognitive-complexity as a second structural gate alongside ruff's McCabe, using `complexipy` with a snapshot watermark so new code is held to the threshold while existing offenders are grandfathered at their current scores.

**Status:** Implemented (2026-05-18)

## Introduction

[S34](S34-code-quality-gates.md) enabled ruff's McCabe cyclomatic-complexity rule (`C90`, threshold 10) and the PLR09xx size/branch/arg rules, but explicitly deferred cognitive-complexity tooling as open question 1: *"Should `complexipy` (cognitive complexity) be adopted as a follow-on once the McCabe-driven refactor pass has reduced the top-six offenders? Out of scope for this spec; would be a future S35-or-later."*

This spec resolves that question with *yes*, and pins down how. The S34 McCabe refactor pass has landed; the top-six offenders identified there are no longer in the top tier. The next gap in the gate is the readability-focused metric — nesting penalties, control-flow structure — that McCabe is structurally unable to measure (McCabe is purely branch-count; nested branches and flat branches cost the same).

**Cognitive complexity** as defined by SonarSource (and implemented by `complexipy`) adds nesting penalties: a branch inside three nested `if`s costs more than the same branch at function top-level. This catches the "deeply nested decision tree" pattern that McCabe misses.

`complexipy` (v5.4.1 as of 2026-05-05) is a Rust-implemented cognitive-complexity scanner with a `--snapshot-create`/snapshot watermark mechanism that fits the S34 grandfathering pattern: snapshot the current state, then any function whose complexity increases above its baseline fails the gate. New functions are held to the threshold.

## Requirements

### Tool and version

- `complexipy >= 5.4.1` is added to the `dev` dependency group in `pyproject.toml`.
- Invoked via the `complexipy` console script (uvx-installed). The package is not directly executable as `python -m complexipy` — there is no `__main__`.

### Threshold

- `max-complexity-allowed = 15` — the upstream default. Aligns with SonarSource's published reference threshold. Tighter than ruff's McCabe of 10 *in absolute number*, but cognitive complexity scores higher than McCabe for the same code because of nesting penalties, so the two thresholds gate roughly the same shape of function.
- This is the *threshold for new code*. Grandfathered functions retain their snapshot watermark; see below.

### Grandfathering: snapshot watermark

`complexipy` does not support per-function `# noqa` suppression (unlike ruff). Grandfathering is done with a snapshot file at the repo root:

- `complexipy-snapshot.json` is generated with `complexipy --snapshot-create src/mdd` and committed.
- On subsequent runs (without `--snapshot-create`), `complexipy` compares each function's complexity to its watermark in the snapshot. A function passes if its current complexity is `<= max(snapshot_complexity, max-complexity-allowed)`.
- A function whose complexity *grows above its snapshot watermark* fails CI. New functions are held to `max-complexity-allowed = 15`.

This is the equivalent of S34's `# noqa: PLR0915`-on-the-def-line convention, but file-scoped rather than line-scoped. The trade-off: less visible at the call site (a reviewer scanning a diff doesn't see the watermark inline), but more accurate (the exact baseline complexity is stored, not just "this function is grandfathered at some level").

When a refactor drops a function below the gate, its snapshot entry is removed; the snapshot file shrinks over time. Regenerating the snapshot (`mise run complexipy-snapshot`) drops the watermark for any function now under threshold.

### Exclusions

```toml
[tool.complexipy]
paths = ["src/mdd"]
max-complexity-allowed = 15
exclude = ["tests/**", "scripts/**", "src/mdd/templates/**"]
```

- `tests/**` — test functions legitimately have repetitive branchy structure (parametrised expectations, mock setup). The S34 rationale for excluding `tests/**` from ARG* applies here too.
- `scripts/**` — one-off operational scripts, not production code. Already excluded from basedpyright.
- `src/mdd/templates/**` — bundled Quarto templates; not Python source.

### Cache directory

`complexipy` writes a `.complexipy_cache/` directory in CWD on every run. This MUST be `.gitignore`d. The snapshot file `complexipy-snapshot.json` MUST be committed.

### CI integration

- A `[tasks.complexipy]` task is added to `.mise.toml` that runs `uv run complexipy src/mdd`.
- `[tasks.ci]` gains `complexipy` in its `depends` list, so every CI pipeline picks it up automatically through `mise run ci` — the workflow YAML only ever invokes mise tasks.
- No new job in either CI YAML; no new cache key; no new image.

### Snapshot regeneration task

- A `[tasks.complexipy-snapshot]` task runs `uv run complexipy --snapshot-create src/mdd`. This is the **only** way the snapshot file should be regenerated. Manual edits to `complexipy-snapshot.json` are forbidden.

## Design Approach

**Complexipy over a second ruff plugin.** Ruff does not implement cognitive complexity and there is no public roadmap to do so as of mid-2026. The closest ruff-compatible option (a hypothetical Sonar-style plugin) does not exist. Complexipy is the established tool in the cognitive-complexity-for-Python space and is implemented in Rust with negligible runtime overhead on a repo this size (sub-second on `src/mdd`).

**Threshold 15, not 10.** Cognitive complexity scores higher than McCabe on the same function because nesting compounds. Using 10 (the McCabe threshold from S34) would gate too aggressively — the survey at threshold 10 produced 135 violations vs. 75 at threshold 15. 15 is the upstream default, matches SonarSource's reference, and gives the same shape of gate as ruff's McCabe ≤ 10 in practice.

**Snapshot watermark over `# noqa`.** Complexipy has no per-function suppression syntax. The snapshot mechanism is the supported grandfathering primitive. The file is small (~12 KB at baseline, JSON), reviewable in PR diffs, and shrinks as refactors land. Per-function `# noqa: CXP` would require a fork of complexipy and is rejected on maintenance grounds.

**Separate `mise run complexipy` task, not bundled into `mise run lint`.** `lint` is ruff-only by convention (S34 invariant: "Ruff is the single static-analysis surface"). Putting complexipy under `lint` would muddy that invariant. A dedicated task surfaces complexipy failures as a distinct CI step and keeps the two tools cleanly separable if a future decision swaps one out.

**No CI YAML changes.** The CI pipelines only invoke `mise run ci`. Adding `complexipy` to the `ci` task's `depends` list propagates to every pipeline without YAML edits, which is the property that arrangement exists to give.

**`src/mdd` as the only analysed path.** Limiting to `src/mdd` (instead of `.`) avoids accidentally scanning `.venv/`, `build/`, `docs/`, or vendored content. Matches the basedpyright `include = ["src", "tests"]` pattern; `tests/` is excluded specifically per the rationale above.

## Implementation Notes

Rollout in a single PR (no staged rollout needed; the snapshot mechanism is self-grandfathering):

1. Add `complexipy>=5.4.1` to `[dependency-groups].dev` in `pyproject.toml`.
2. Add `[tool.complexipy]` config block with `paths`, `max-complexity-allowed`, `exclude`.
3. Run `uv lock` to update the lockfile.
4. Run `uv run complexipy --snapshot-create src/mdd` from the repo root to create `complexipy-snapshot.json`.
5. Add `.complexipy_cache/` to `.gitignore`.
6. Add `[tasks.complexipy]` and `[tasks.complexipy-snapshot]` to `.mise.toml`.
7. Add `complexipy` to `[tasks.ci].depends`.
8. Verify `mise run ci` passes locally.
9. Commit `complexipy-snapshot.json` along with the config + task changes.

### Snapshot file size

The initial snapshot is ~12 KB / ~640 lines of JSON listing all functions with complexity > 0 (sorted by path). It will grow with the codebase but shrink as refactors land. No size threshold gate is needed — the file is text-diffable, and large deltas show up clearly in PR diffs.

### Reviewer guidance for snapshot changes

When `complexipy-snapshot.json` changes in a PR:

- **New entry added** — a refactor or new function introduced complexity. Reviewer should ask: is the new complexity necessary? Can the function be split?
- **Existing entry's `complexity` value increased** — a function got more complex. This should rarely happen; CI would have failed unless `--snapshot-create` was re-run, which should only happen via `mise run complexipy-snapshot` in a deliberate refactor PR.
- **Existing entry removed** — refactor landed; complexity dropped below threshold. Good.

`mise run complexipy-snapshot` MUST NOT be run as a routine "make CI green" reflex. Regenerating to raise watermarks defeats the gate. Snapshot regeneration is for deliberate refactor PRs that drop watermarks downward.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- CI is the gate that enforces this spec: pipelines invoke `mise run ci` and inherit the new dependency automatically.
- [S34](S34-code-quality-gates.md) — this spec resolves S34's open question 1; structural and cognitive complexity together form the complete complexity gate.
- [S36](S36-module-structure.md) — file-length is heuristic-only; per-function gates are the machine-checked surface. Complexipy adds the cognitive-complexity layer to that surface.

## Open questions

1. Should `complexipy-snapshot.json` regeneration be gated by a CI check that the regenerating PR also lowers some watermarks (i.e. cannot be net-upward)? Deferred — reviewer guidance is enough for now, and tooling for the check does not exist.
2. Should the threshold be tightened from 15 → 10 once the highest-watermark functions have been refactored? Likely yes; revisit when the snapshot file has fewer than ~20 entries.
3. Should `--check-script` be enabled to also gate module-level (script) cognitive complexity? Deferred — module-level code is generally short in this codebase; revisit if module-level branching grows.

## Out of scope

- Refactoring existing high-complexity functions. Each refactor is a separate PR; this spec only adds the gate and snapshot.
- Replacing ruff's McCabe with complexipy. Both are kept; McCabe catches branch-count growth, complexipy catches nesting growth.
- Cognitive-complexity tooling other than complexipy (`cognitive_complexity` Python package, SonarQube). Considered and rejected: `cognitive_complexity` is unmaintained since 2022; SonarQube was explicitly rejected in S34 on hosting-overhead grounds.
- Per-PR delta gating via `complexipy --diff main --ratchet`. The snapshot watermark is a superset of this in practice and avoids the complication of teaching CI which ref to diff against.
- IDE integration. The complexipy VS Code extension exists; adoption is per-developer, not project-level.
