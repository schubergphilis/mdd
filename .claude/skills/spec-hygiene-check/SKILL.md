---
name: spec-hygiene-check
description: Run `mise run spec-check` to validate docs/spec/*.md files for well-formedness, broken sibling links, Status section presence, and API endpoint citation hygiene. Invoke before opening a PR that touches docs/spec/, after drafting a spec batch, or before requesting spec review.
---

# Spec hygiene check

Runs `mise run spec-check`, which executes `scripts/spec-check.py` against all
`docs/spec/*.md` files (excluding `000-*.md`).

## When to run

- **Before opening a PR that touches `docs/spec/`** — catches regressions
  before reviewers see them.
- **After a spec-drafting batch** — confirms all new specs have the required
  `**Status:**` line and no unclosed code fences.
- **Before requesting spec review** from another agent or human — cleans up
  link rot and fence mismatches quickly.
- **After renaming or deleting a spec file** — the broken-link check will catch
  any sibling references that now point to a missing file.

## When NOT to run (or when to expect failures)

- **Draft specs with intentionally unresolved items** — a draft may cite API
  endpoints marked `TBD:` on purpose. The check will pass for those (the `TBD:`
  marker is the signal). Do not strip the marker prematurely.
- **The `000-*.md` files** — the overview/shared-patterns specs have different
  conventions and are excluded by the script.
- **During mid-session editing** — unclosed fences are expected while you are
  mid-edit. Run the check once the file is saved to a commit-ready state.

## What is checked

1. **Markdown well-formedness** — triple-backtick fence lines must appear an
   even number of times per file. An odd count means a fence is unclosed.
   Reports `<file>:<line>: fence: unclosed code fence (N opening lines)`.

2. **Broken sibling links** — any link of the form `[text](SNN-foo.md)` or
   `[text](./SNN-foo.md)` must resolve to an existing file in `docs/spec/`.
   External URLs (`https://...`) are ignored.
   Reports `<file>:<line>: link: broken sibling link → SNN-foo.md`.

3. **`**Status:**` line** — every non-000 spec must contain a `**Status:**`
   line. Reports `<file>: status: missing **Status:** line`.

4. **Implemented-status format** — if the Status value starts with
   `Implemented`, it must match `Implemented (YYYY-MM-DD)` exactly. Commit
   shas, PR numbers, or extra prose inside the parens are rejected — the
   commit history is the durable record for those. Reports
   `<file>:<line>: status: Implemented status must be "Implemented (YYYY-MM-DD)" — got: ...`.

5. **API endpoint citation rule** — any URL matching an external REST API path
   pattern (`https://*.atlassian.net/wiki/api/...`,
   `https://graph.microsoft.com/...`, etc.) that appears outside a code fence
   must either be a clickable Markdown link or have `TBD:` on the same line.
   Plain bare URLs to API paths are flagged as under-cited.
   Reports `<file>:<line>: api-cite: bare API URL without link or TBD: marker`.

## Exit behaviour

- **Exit 0** — no violations; tree is clean.
- **Exit 1** — one or more violations; each printed as `<file>:<line>: <category>: <detail>`.
  A summary line is printed to stderr.

## Usage

```bash
mise run spec-check
```

Or directly:

```bash
python3 scripts/spec-check.py
```
