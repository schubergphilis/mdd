# Contributing

Thanks for taking the time to look at `mdd`.

Contributions are governed by the [Apache-2.0 licence](LICENSE), and
participation by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting set up

```bash
mise install          # python + uv
mise run install      # uv sync --all-groups
mise run ci           # the full gate
```

Three external tools are exercised by the unit suite and must be on
`PATH`: `quarto`, `rsvg-convert` (librsvg) and `rg` (ripgrep).

## The gate

`mise run ci` is the contract. It runs, in order: conflict-marker check,
`ruff check` + `ruff format --check`, `basedpyright` in strict mode, the
`complexipy` cognitive-complexity gate, `pip-audit` over the dependency
closure, the unit suite, and the IR round-trip and coverage suites.

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

## A note on how this is built

`mdd` is written largely by AI agents under human review. That does not
change what is expected of a contribution — the gate is the gate — but it
does mean the codebase carries unusually detailed inline rationale.
Please keep that up: explain *why*, not *what*.
