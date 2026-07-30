---
name: refactor-module
description: Refactor one Python module (single file, or one subdirectory) under src/mdd/ using a deterministic-tools-first, LLM-as-judge pattern. Use when the user says "clean up <module>", "refactor <file>", "look at <path> for refactor candidates", or "what's worth changing in <path>". Runs ruff (default and ALL rules), basedpyright, complexipy, and a few greps against the scoped path; lets the LLM judge which findings are worth acting on; applies one transformation at a time with the project's gates between each. Does NOT commit.
---

# Module refactor — deterministic tools first, LLM as judge

The principle: deterministic tools find candidate spots; the LLM judges which are worth changing. Most candidates should be rejected — readability is the only measure, and many lint/complexity hits are already in their clearest form. The value of running the tools is finding the small minority that aren't.

Compound LLM refactors empirically fail more than half the time even with frontier models, so this skill applies one approved transformation at a time with the full project gate suite between each.

## When to use

- "Look at `src/mdd/<module>/<file>.py` for refactor candidates."
- "Clean up `src/mdd/<module>/`."
- "What's worth changing in this file?"
- Triage pass on a module before starting a feature change in it.

## When NOT to use

- **Single high-CC function** → use [`complexipy-refactor`](../complexipy-refactor/SKILL.md) instead; it's tighter for that case.
- **Whole-repo cleanup** ("refactor src/") → too big; pick a module.
- **`tests/**`** — most rules don't apply there or are intentionally relaxed.
- **Active feature branch with uncommitted work** in the module — finish the feature first. Refactor passes should land on top of clean state.

---

## Phase 1 — Scope

Get the path from the user. It must be either:

- A single file under `src/mdd/` (e.g. `src/mdd/confluence/export.py`), OR
- A subdirectory under `src/mdd/` (e.g. `src/mdd/confluence/`).

If the user gives anything broader (the whole repo, multiple modules, `src/`), ask them to narrow before proceeding.

Throughout the rest of this skill, **`$MODULE` stands for the path from this phase** — substitute the actual path when running each command. The Bash tool does not preserve variables across calls.

## Phase 2 — Deterministic findings

Run each command below against `$MODULE`. Collect the output verbatim — do not summarise or filter yet.

```bash
# 1. Lint with rules currently in CI
uv run ruff check $MODULE

# 2. Lint with ALL rules — surfaces categories not yet enabled in CI
uv run ruff check --select ALL $MODULE 2>&1 | head -120

# 3. Type checker
uv run basedpyright $MODULE 2>&1 | head -80

# 4. Cognitive complexity (top entries)
uv run complexipy --ignore-complexity --plain $MODULE 2>&1 | sort -k3 -rn | head -15

# 5. Suppression density (signal of where the type system is in tension)
grep -rnE '# (pyright|noqa|type): ignore' $MODULE | wc -l
grep -rnE '# (pyright|noqa|type): ignore' $MODULE | head -30

# 6. Module size — large files are split candidates (see S36)
if [ -d "$MODULE" ]; then
  find "$MODULE" -name '*.py' -exec wc -l {} + | sort -rn | head -10
else
  wc -l "$MODULE"
fi

# 7. Recent churn (90d) — high-churn files are riskier; low-churn high-CC is safer
git log --since="90 days ago" --pretty=format: --name-only -- "$MODULE" 2>/dev/null | grep -v '^$' | sort | uniq -c | sort -rn | head -10
```

If the module imports from a sibling that operates on the same value types, grep for those imports too — but only **report** the cross-file findings; don't propose changes outside `$MODULE`.

### Known tool quirks

- **ruff `--select ALL`** turns on rule families this project has deliberately not enabled. Read [S34](../../../docs/spec/S34-code-quality-gates.md) before acting on a category: several are listed there as explicitly rejected, and a finding in one of those families is a non-finding.
- **complexipy** scores are cognitive, not cyclomatic — they weight *nesting* heavily. A flat 30-branch dispatch scores lower than a triply-nested 8-branch loop, and that ranking is the right one to trust when deciding what to look at first.
- Ruff's `C901` (McCabe ≥10) and complexipy (≥15) are the two enforced complexity gates. A function under both is not a candidate on complexity grounds alone.

## Phase 3 — Judge

For each finding from phase 2, ask two questions:

1. *Would acting on this make the module measurably clearer to a reader who hasn't seen it before?*
2. *Am I removing a category of bug, or just rearranging characters?*

If neither answer is yes, **reject the finding**. The expected reject rate is high — typically ≥60% of raised candidates won't clear the bar. That is the point of having the LLM judge: most lint and complexity hits are already in their clearest form, and acting on them is lateral motion that costs reviewer time and gives nothing back.

### Transformations to try (each is reversible; revert if the after isn't obviously better)

These are *hypotheses to evaluate per finding*, not commitments to apply:

- Replace anonymous tuples or `dict[str, Any]` blobs with small dataclasses.
- Collapse a chain of helpers that share parameters into methods on a class whose constructor takes those parameters once.
- Convert a free function into a thin wrapper around a class with a single `execute()`-style method — or the inverse, fold a one-method class back into a function.
- Move related free functions onto an existing class as methods (especially when they take the class's `self.x` as their first arg today).
- `@property` / `@cached_property` for derived state read multiple times.
- Structural pattern matching (`match`/`case`) instead of `isinstance` ladders, **only** when the type checker can follow the patterns (literal keys at every level). If pyright will need new `# pyright: ignore` comments on the bound captures, the match form isn't a win.
- Replace tuple returns with named dataclasses, when the tuple has ≥2 elements and is consumed by ≥2 callers.
- Hoist deferred (function-body) imports to the top of the file — unless they break a cycle (check by trying).
- Inline a helper with one caller and no test that exercises it directly.
- Extract a helper for a pattern that genuinely appears in three or more places (coincidental two-site duplication is not duplication).

Some of these are each other's inverse. That's deliberate — the right direction depends on the specific file.

### Anti-patterns (if you find yourself proposing one of these, drop the item)

- Wrapping a single free function in a class with one `execute()` method because "it's tidier." If there's no shared state, it's still a function.
- Adding a `@property` for an attribute set exactly once in `__init__`. Plain attributes are clearer.
- Promoting "threaded I/O" (values mutated in place during one call) to dataclass attributes that look like persistent state, without documenting the lifecycle.
- `match`/`case` when one of the keys is a runtime variable — the typing tax usually exceeds the readability gain.
- Extracting a helper to deduplicate two call sites that use the value for different reasons. Coincidental duplication isn't duplication.
- "Refactor for symmetry" — converting all five similar spots when three benefit because they "should look the same."
- Renaming or reshaping for consistency with a sibling file. Different files solve different problems.

## Phase 4 — Propose, then stop

Output a numbered list of candidates. For each, include all four fields:

- **Finding** — one sentence; cite the tool that surfaced it (e.g. "ruff RUF013", "complexipy CC=18 on `foo()`", "pyright reports 4 ignores on lines 105–115").
- **Proposed transformation** — one sentence; name the specific transformation from the list above.
- **Why this clears the bar** — one sentence answering question 1 or 2 from phase 3. If you can't write this without hand-waving, drop the item.
- **Estimated risk** — low / medium / high. Low = local change, type-checker-safe, test-covered. Medium = touches public API or crosses files. High = changes return types, requires test updates, or relies on subtle invariants.

After the list, **stop**. Wait for the user to approve specific items by number. Do not start editing.

If the judge step rejected every finding, the right output is the phase 2 findings plus a single sentence: *"No findings clear the readability bar; recommend leaving the module as-is."* Stop there.

## Phase 5 — Apply, one approved item at a time

For each item the user approves, in order:

1. Make the change. Keep the diff focused on the one finding — do not let scope creep pull in nearby spots that "look the same."
2. Run the project gates in this order:
   ```bash
   mise run lint
   mise run typecheck
   mise run test
   mise run complexipy
   ```
3. If any gate fails, **treat the failure as evidence the transformation was wrong**. Revert the change. Report which gate failed and why. Move on to the next approved item — do not retry the same transformation, and do not suppress the failure.
4. If all green, continue.

Do **not** combine multiple approved items into one edit pass. The gates between items are the safety net.

Do **not** commit. The user decides when the pass is done and how to bundle the result.

## Phase 6 — Report

After the last approved item lands (or after a failure that stops the pass), report:

- **Applied** — numbered list, with a one-line before/after sketch per item.
- **Reverted** — what was attempted but rolled back, with the failing gate output.
- **Proposed-but-declined** — items the user said no to (one line each).
- **Considered-but-not-proposed** — findings you judged off-the-bar in phase 3 (one line each). This is the discipline check; most candidates should land here.

The considered-but-not-proposed list is the most valuable part of the report. It shows the user what tools surfaced and why the judge said no.

## Hard guardrails

- **Never** run against `src/` or the whole repo. One module at a time.
- **Never** introduce new tooling as part of this skill. Use only what's installed via `pyproject.toml` (`ruff`, `basedpyright`, `complexipy`). If a tool would meaningfully change the output and you want it, propose adding it as a separate change first — and read S34 on why this project keeps one static-analysis surface.
- **Never** add a `# pyright: ignore` or `# noqa` to make a refactor pass. If the suppression count grows during this skill, the refactor was wrong.
- **Never** regenerate `complexipy-snapshot.json`. The watermark mutates automatically on a successful `mise run complexipy`.
- **Never** combine multiple approved items into one edit pass.
- **Never** commit. Surface the diff for the user to commit.
- **Never** edit files outside `$MODULE`. Cross-module findings are *reported*, not acted on.

## Output contract

A successful run MUST include, in this order:

1. The deterministic findings from phase 2 (verbatim tool output, lightly grouped).
2. The numbered proposal list from phase 4 with all four fields per item.
3. For each approved item: gate results and a one-paragraph note on the diff applied (or the revert if it failed).
4. The phase 6 report.

A run where the judge rejects every finding is a valid successful outcome. It produces phase 2 findings plus the one-sentence "leave as-is" recommendation, then stops.

## Self-prompts before producing the proposal list

Read these to yourself before writing phase 4:

- *"For each finding, can I answer 'yes' to one of the two phase-3 questions in one sentence, without hand-waving?"*
- *"Am I proposing five things because the file 'feels' uneven, or because each of the five independently clears the bar?"*
- *"Did I add a `# pyright: ignore` or `# noqa` mentally while imagining the after? If yes, drop the item."*
- *"Have I named the specific transformation, or am I gesturing at 'make this nicer'?"*
- *"What's the smallest version of this change that captures the win? If the smallest version isn't worth doing, the bigger version isn't either."*
