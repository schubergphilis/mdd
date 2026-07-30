# Contributing

Thanks for taking the time to look at `mdd`!

Contributions are governed by the [Apache-2.0 licence](LICENSE), and
participation by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Setting up

```bash
mise install          # python + uv
mise run install      # uv sync --all-groups
mise tasks            # list development commands
mise run ci           # the ci gate
```

## The gate

`mise run ci` is the basic contract. It runs, in order: conflict-marker
check, `ruff check` + `ruff format --check`, `basedpyright` in strict mode,
the `complexipy` cognitive-complexity gate, `pip-audit` over the dependency
closure, the unit suite with coverage checks (aim >90% for new code).

GitHub will also run the IR round-trip suite: `mise run ir-roundtrip-bench`.

A pull request is expected to be green before review. In particular:

- **Full type annotations.** `basedpyright` runs in strict mode and must
  report zero errors. Suppress with a specific code
  (`# pyright: ignore[reportAny]`), never a bare ignore.
- **Structural limits.** Cyclomatic complexity ≤ 10, ≤ 40 statements,
  ≤ 10 branches, ≤ 6 arguments, ≤ 6 returns per function. New code that
  trips these gets refactored, not `# noqa`'d — and a blanket `# noqa`
  with no code is rejected outright.
- **Tests for behaviour changes.** Anything talking to a live service is
  marked `@pytest.mark.integration` and stays out of the default run.
  Likewise anything that depends on Microsoft Office is marked
  `@pytest.mark.office`.

## Design docs

Non-trivial features start with a spec in `docs/spec/` (`SNN-<slug>.md`).
`mise run new-spec <slug>` scaffolds one and `mise run spec-check`
validates the result. Specs are self-contained by rule: they describe the
design without depending on any working document to be readable.

## Commits

[Conventional Commits](https://conventionalcommits.org/):
`type(scope): description`, with `type` one of `feat`, `fix`, `docs`,
`style`, `refactor`, `test`, `build`, `ci`, `perf`, `revert`,
`improvement`, `chore`.

## Using AI agents

`mdd` is written largely by AI agents under human review. That does not
change what is expected of a contribution — the gate is the gate — but it
does mean the codebase needs detailed inline rationale.
Please keep that up: explain *why*, not *what*.
