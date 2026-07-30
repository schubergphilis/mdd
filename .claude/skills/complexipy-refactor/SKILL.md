---
name: complexipy-refactor
description: Refactor a function from the complexipy snapshot to genuinely improve maintainability, with the cognitive-complexity score as a check (not a target). Use when the user says "refactor function X to lower CC", "burn down the complexipy snapshot", "drop CC on …", "fix this high-complexity function", or after `complexipy --failed` surfaces a candidate. Forces a pre-refactor orientation step and a reviewer-acceptance check before any code changes.
---

# Complexipy-driven refactor

The complexipy snapshot (`complexipy-snapshot.json`) lists functions whose cognitive complexity exceeds 15. Each is a *tap on the shoulder* — "look at this function again" — not a target to minimise. The job of this skill is to make sure the refactor an agent produces is a real improvement, not a metric-gaming exercise that lowers the score while making the code harder to read.

See [S37](../../../docs/spec/S37-complexipy-cognitive-complexity.md) for the gate definition and the snapshot's role. Read it before starting.

## When to use

- User asks to refactor a named high-CC function ("drop CC on `update_page`", "split `read_block`").
- User asks to burn down the snapshot ("refactor the next severe-tier offender", "shrink `complexipy-snapshot.json`").
- A failing complexipy run on a refactor PR shows a new function above 15 — use this skill to evaluate whether to refactor or split into a separate PR.

## When NOT to use

- The function is in `tests/**`, `scripts/**`, or `src/mdd/templates/**` — those are excluded from the gate and not worth refactoring for CC reasons.
- The user wants a *feature change* that incidentally touches a high-CC function — do the feature change normally; don't conflate it with a CC-driven refactor. Resulting CC changes are fine; pursuing CC reduction is out of scope for the feature PR.
- The high-CC function is structurally branchy by nature (XML readers, format dispatchers over open enums, retry loops). Splitting them into N small helpers usually makes them harder to grep. The honest output of this skill on such a function is "leave at watermark" — see step 4.

---

## Step 1 — Orientation (mandatory; do NOT skip)

Before touching any code, do the following and *write down* the answers. The agent that skips this step will produce metric-gaming.

1. **Read the function in full.** Note its location and current CC score (from the snapshot or `uv run complexipy --ignore-complexity --plain src/mdd | grep <function>`).
2. **Read the type definitions the function operates on.** Dataclasses, protocols, enums, type aliases. Often the *type itself* already encodes the rule the function hand-writes — when the type changes, the function follows automatically.
3. **Grep at least two peer files** in the same package. Look for:
   - The same isinstance-pattern with different transforms.
   - The same `for x in y: if isinstance(z, ...): coerce; append` shape.
   - The same dispatching if-chain over a known set of types.
4. **Write a one-sentence summary**: "This function does ___."
5. **Write a one-sentence finding**: "The same shape exists in: ___" or "No similar shape elsewhere."

Output these five items as a short orientation note in your reply *before* proposing any change. The user (or reviewer) needs to see the orientation before they see the diff.

## Step 2 — Propose the refactor

Based on the orientation, propose exactly one refactor. The proposal must answer **the reviewer-acceptance test**:

> *"If I removed the CC number from the picture entirely and showed only the diff, would a reviewer say 'yes, please apply'?"*

If the only honest justification is "the score drops from X to Y", you are gaming the metric. Go back to step 1 and look harder, or skip to step 4 (decline).

Acceptable justifications include:
- "The omission rule moves from a hand-curated table to the dataclass field defaults — there is now one source of truth instead of two."
- "Three peer files duplicate the same walk-and-transform shape; hoisting it into a shared helper deletes two closures and exposes a previously-implicit contract on one shared helper."
- "Two strategies were tried at different abstraction levels; making them peers in a resolver tuple makes the order explicit and adding a third strategy a one-line change."

To find concrete past examples, `git log --grep='refactor(' --grep='cognitive complexity'` lists committed refactors that passed this test.

## Step 3 — Anti-patterns (if you find yourself doing these, STOP)

Each of these *lowers CC* but *does not improve maintainability*. The skill explicitly forbids them as the sole motivation for a refactor:

- **Extracting a helper called from exactly one site** just to shorten the parent. Inline call-sites with one caller are usually a code smell; the parent reads better with the logic in place. If the helper is genuinely reusable, an unrelated future PR will introduce the second caller; don't pre-extract.
- **Replacing a scannable if-chain with a dict-of-callables or frozenset table** when the cases aren't extensible. If the cases are closed (a fixed set of types, never to grow), the if-chain is clearer than a table because the reader sees the predicate and the action on adjacent lines.
- **Splitting a function purely along statement boundaries** (top half / bottom half) without a logical seam. The split has to correspond to actual phases or concerns — "lines 1–20" and "lines 21–40" is not a seam.
- **Renaming inner closures to module-private helpers** without first checking whether the same closure pattern appears in peer files. If it does, the helper belongs in the shared module, not next to the original closure.
- **Adding `# noqa: PLR0911` (or any other suppression)** because your refactor pushed the function over a different lint threshold. Going green on CC at the cost of new suppressions elsewhere is moving the bump under the rug.

## Step 4 — Decline is a valid outcome

After orientation, you may find no genuinely-better refactor exists. The right output then is:

```
Recommend: leave at watermark.
Reason: <one sentence; e.g. "The function is a straight-line dispatch
over a closed set of node types; splitting it would produce N small
helpers no easier to read than the original.">
```

Then STOP. Do not produce a diff. Do not invoke `mise run complexipy-snapshot`. Report the finding to the user and move on.

An honest decline is the most valuable output this skill produces. Some functions are inherently branchy (XML readers, format dispatchers over open enums) and any refactor would replace one thing-to-read with several things-to-read. The watermark exists exactly so those functions can stay on the list without blocking CI.

## Step 5 — Apply and verify

If you proceeded past step 4, now you can edit code.

1. Make the change. Keep it scoped to the one function and any directly-related peers identified in step 1.
2. Run the local gates in this order:
   ```bash
   mise run lint
   mise run typecheck
   mise run test
   mise run complexipy
   ```
   All four must pass. **Do not** invoke `mise run complexipy-snapshot` — that regenerates the baseline and defeats the gate. The snapshot mutates automatically on a successful `mise run complexipy`; you commit the mutation, you do not request it.
3. Commit the refactor. One function per commit. Title format:
   ```
   refactor(<scope>): drop <function> cognitive complexity <before> -> <after>
   ```
   Body: cite the reviewer-acceptance justification from step 2 verbatim. Do not list the CC delta as the headline reason — it goes in the title only. The commit message is the durable record of this refactor; `git log --grep='cognitive complexity'` is the canonical "what's been done" view.

## Step 6 — Push and check CI

Push the branch and open a PR per the "Session completion" section of `AGENTS.md`, then check the run:

```bash
gh -R schubergphilis/mdd pr checks <number>
```

CI must go green before the next refactor starts. If complexipy fails on the new commit, *read the failure carefully* — sometimes the snapshot mutation surfaces a previously-missed watermark mismatch, which is its own bug rather than a problem with your refactor.

---

## Hard guardrails

- **Never** run `mise run complexipy-snapshot` as part of this skill's flow.
- **Never** add a new `# noqa` for a non-CC rule to compensate for a CC-driven refactor.
- **Never** combine multiple function refactors into one commit (one function per commit).
- **Never** edit `complexipy-snapshot.json` by hand — let `mise run complexipy` produce the mutation.
- **Never** declare success without all four local gates passing.

## Self-prompts before producing the diff

Read these to yourself before writing any new code:

- *"What is the **type** of the thing this function operates on? Does that type already encode the rule I'm about to hand-write?"*
- *"If a reviewer saw only the diff and my one-sentence justification, would they say 'yes, apply'?"*
- *"What's the **next** function I would refactor in the same file? If I can't name one, my refactor probably solved an isolated symptom."*
- *"Is the shape I'm extracting genuinely shared with two or more peer files, or am I creating a helper that exists only because the score told me to?"*

## Output contract

The reply for an applied refactor MUST include, in this order:

1. The five-item orientation note from step 1.
2. The reviewer-acceptance justification from step 2.
3. The commit SHA produced.
4. The CC before → after (citation, not headline).

The reply for a declined refactor MUST include:

1. The five-item orientation note.
2. The decline reason from step 4.
3. *No diff, no commit.*

Either reply is a valid successful outcome.
