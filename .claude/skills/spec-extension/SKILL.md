---
name: spec-extension
description: Draft a new spec or extend an existing one in docs/spec/. Use when the user asks to "draft a spec for X", "write a spec for X", "extend spec SNN", or "add a spec". Handles existence check, upstream reading, design-fork questions, numbered open questions, and committing the result.
---

# Draft or extend a spec

Use when asked to draft a new spec, write a spec for a feature, or extend an existing numbered spec.

**This skill produces spec files only.** Do not edit `src/mdd/` or write implementation code while drafting — design comes first, code follows in a separate session.

## Step 1 — Read the overview spec and related specs

Read `docs/spec/000-specs.md` in full and apply its conventions, especially the **cross-reference rule**: use relative links (`[data protection](S07-data-protection.md)`), never bare numbers ("S07"). Specs are the durable design record and must be readable on their own — they must not link out to `docs/research/`, which holds working documents. Copy the minimum relevant content into the spec instead.

Then scan the spec index titles for likely overlap with the new topic and read the 1–3 most relevant entries in full. Do not read all listed specs exhaustively — judgement, not enumeration.

## Step 2 — Decide whether to amend an existing spec

Before scaffolding a new file, check for overlap:

```bash
grep -l -i "<topic-keyword>" docs/spec/*.md
ls docs/spec/ | grep -i "<topic-slug>"
```

If a relevant spec already exists, amend it rather than opening a new numbered file. When in doubt between amend and add, ask the user.

If you are adding a new spec, reference the related specs using the relative-link convention.

## Step 3 — Scaffold with `mise run new-spec`

If you need a new spec, scaffold from the template:

```bash
mise run new-spec <slug>
```

This picks the next free number and copies `docs/spec/spec-template.md` to `docs/spec/S<NN>-<slug>.md`. Keep `Status: Draft` until the feature lands. When flipping to implemented, use the exact form `Implemented (YYYY-MM-DD)` where the date is the commit date of the newest commit that landed the spec — no shas, no PR numbers, no prose. See the "Status convention" section in `docs/spec/000-specs.md` for the full list of accepted forms.

## Step 4 — Ask at design forks, not at every step

Ask the user only at genuine branch points where guessing wrong means rewriting the spec. Rules:

- **Cap at 4 options.** If 5 options arise, split into two questions.
- **Recommended option first.** The user should be able to accept the default without reading every alternative.
- **Include previews for concrete choices.** When two options produce visibly different output (YAML schemas, API shapes, commit-subject styles), show both as inline previews rather than describing them in prose.

Example of a good design-fork question:

> Two approaches for storing Confluence page IDs in frontmatter:
>
> **Option A (recommended)** — nested key:
> ```yaml
> confluence:
>   page_id: "12345"
>   space_key: "TEAM"
> ```
>
> **Option B** — flat keys:
> ```yaml
> confluence_page_id: "12345"
> confluence_space_key: "TEAM"
> ```
>
> Which do you prefer?

## Step 5 — Flag topics as out of scope

Keep specs tight and focused. Populate the out-of-scope section with the things that can be excluded:

```markdown
## Out of scope

- Binary release packaging (deferred — see above).
- CD for Confluence write-back (deferred — see above).
- Coverage threshold enforcement.
```

## Step 6 — Number open questions

Collect unresolved questions in a dedicated section:

```markdown
## Open questions

1. Does the API support filtering by namespace when listing groups?
2. Is `spaceKey` accepted by Confluence v3 `/pages` endpoint or only by v1?
3. Should export fail loudly on a missing attachment or warn and skip?
```

Number each question so reviewers can answer by reference ("Q2: yes, spaceKey works in v3"). Specs cite the question number they answer when one implementation session closes them.

## Step 7 — Update the index

Regenerate the table with `uv run python scripts/spec-list.py` and **patch the new row(s) into the existing index table** in `docs/spec/000-specs.md`. Do not overwrite the surrounding prose — the file is prose-wrapping-a-table, not a table file. The simplest correct edit is appending the new row(s) to the bottom of the existing table.

## Step 8 — Run the hygiene check

Before committing, validate the new or amended spec:

```bash
mise run spec-check
```

Fix any well-formedness or broken-sibling-link errors before moving on. If deeper review is wanted, invoke `/spec-hygiene-check`.

## Step 9 — Commit and open a PR

Spec batches go in one commit, not one-spec-per-commit — a coherent batch flowing from the same research reads as one decision. A single spec is still one commit.

```bash
git checkout -b docs/spec-<slug>
git add docs/spec/S<NN>-<slug>.md docs/spec/000-specs.md
git commit -m "docs(spec): add S<NN> — <short title>"
```

Then push the branch and open a PR per the "Session completion" section of `AGENTS.md`. Specs land through review like any other change.

For docs-only commits, skip `mise run ci` — running lint/typecheck/test on a markdown addition is theatre.

## When this skill does NOT apply

- Fixing a bug in an existing feature — open an issue with `gh issue create` instead.
- Implementing specs that are already written — that is a normal code session.
- Review of spec quality or hygiene — use `/spec-hygiene-check`.
