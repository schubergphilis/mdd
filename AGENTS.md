# AI agent instructions for mdd

[README.md](README.md) explains the project.

[CONTRIBUTING.md](CONTRIBUTING.md) explains how to make open source contributions.

Use `mise tasks` to discover build functionality. Remember to use it.

Big features need a spec in `docs/spec/`, see [`000-specs.md`](docs/spec/000-specs.md).

Never run `op read`, `op item get`, `op signin` or any other 1Password CLI command that returns secrets. Do not attempt to resolve `op://` references. Secrets must not end up in session context.

The installed `mdd` may be a wrapped or aliased command, so instead use `uv run mdd`.

## Code quality

Code must have full type annotations and be `ruff`-formated.

Code should have high test coverage (gate is 70%, but aim 90%+ for new code).

See `docs/spec/S34-code-quality-gates.md` for details.

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
