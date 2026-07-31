# AI agent instructions for mdd

[README.md](README.md) explains the project.

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to make open source contributions.

Use `mise tasks` to discover build functionality. Remember to use it.

`mise run check-mdd-commands` checks every `mdd …` string in prose against the real argparse tree. A distribution that composes this CLI runs the same gate over its own prose from a sibling checkout: `--repo-root PATH` selects the tree to scan (default: cwd), `--dispatcher MODULE:CALLABLE` the parser factory to check against (default: `mdd.cli:build_dispatcher`).

Big features need a spec in `docs/spec/`, see [`000-specs.md`](docs/spec/000-specs.md).

Research notes live in `docs/research/`, see [`000-research.md`](docs/research/000-research.md). They are working documents; specs are the durable record and must not link out to them.

Never run `op read`, `op item get`, `op signin` or any other 1Password CLI command that returns secrets. Do not attempt to resolve `op://` references. Secrets must not end up in session context.

The installed `mdd` may be a wrapped or aliased command, so instead use `uv run mdd`.

## Skills

`.claude/skills/` holds repeatable workflows for the tooling this repo
already ships. Invoke one with a `/` prefix when the task matches:

* `/article-synthesis` — draft a `docs/articles/` page from the spec and research corpus, with citation density and preserved reversals enforced
* `/complexipy-refactor` — refactor a function off the `complexipy-snapshot.json` watermark, with the score as a check rather than a target
* `/refactor-module` — scoped single-module pass: run the gates over one path, judge which findings are worth acting on, apply one transformation at a time
* `/spec-extension` — draft or extend a `docs/spec/SNN-*.md`
* `/spec-hygiene-check` — drive `mise run spec-check` and interpret its output

## Code quality

Code must have full type annotations and be `ruff`-formated.

Code should have high test coverage (gate is 70%, but aim 90%+ for new code).

See `docs/spec/S34-code-quality-gates.md` for details.

### No cross-references from code

Do not cite spec, plan, or issue numbers in Python code under `src/` or
`tests/` — not in comments, docstrings, log messages, `argparse` help, or error
text. That includes `(spec S27)`, `S31 §"Open questions"`, `spec-009`,
`plan P03 phase 2`, `issue #118` and `Spike fix 2`.

The reference is one-directional: specs point at code, code does not point back.
A reader of the code may not have the spec — `S44` lives in a separate private
distribution and never resolves here at all — and the `issue #NN` numbers
predate the open-source cut, so they resolve to nothing, or worse, to an
unrelated GitHub issue that happens to share the number.

If a citation is the only place a rule is written down, state the rule in one
short sentence instead. If the code already says it, delete the comment. Links
to public external standards (`CommonMark §4.7`) are fine — a reader can look
those up.

`README.md` and fixture markdown under `tests/` are documentation, so the docs
convention applies there instead: a **relative link** to a spec
(`[S18](../../../docs/spec/S18-sharepoint-sync.md)`) is fine, but a bare number
or an undefined link reference (`[S07]`, which renders as literal text) is not.
Prose in `docs/`, and relative links between specs, are unaffected: that is
where cross-referencing belongs.

## Git and GitHub usage

Follow [Conventional Commits](https://conventionalcommits.org/):
* **Format:** `type(scope): description`
* **Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `build`, `ci`, `perf`, `revert`, `improvement`, `chore`

Use `gh` to work with GitHub, main upstream repo is `schubergphilis/mdd`:
* prefer fast-forward/rebase merges; squash merging denied
* force pushing main or amending main is denied
* prefer pushing new branches to `schubergphilis/mdd` remote if you have access
* `gh pr` for pull requests
* `gh issue` for issue tracking
* commit code on branches and make PRs
* PRs are merged after human review or explicit instruction

## Session completion

Continue working until every change is committed, pushed, and CI passes.

1. **Quality gate**:
   ```bash
   mise run ci
   ```

2. **Commit and push**:
   ```bash
   git checkout -b <type>/<slug>
   git add <files>
   git commit -m "<type>(<scope>): <description>"
   git push -u <remote> <type>/<slug>
   ```

3. **Open PR**:
   ```bash
   gh pr create \
    -R schubergphilis/mdd \
    --title "<type>(<scope>): <description>" \
    --body "<long description>"
   ```

4. **Check PR CI**:
   ```bash
   gh -R schubergphilis/mdd pr view <number> --json headRefName,state,url
   gh -R schubergphilis/mdd pr checks <number> --json name,workflow,state,link
   ```
