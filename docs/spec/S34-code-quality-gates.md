# 034 — Code Quality Gates

**Purpose:** Define the static-analysis rule set, complexity thresholds, and grandfathering policy that `mise run lint` enforces, so future iterations (human and agent) cannot let function size, branchiness, or argument bloat regress unnoticed.

**Status:** Implemented (2026-05-15)

## Introduction

The pre-existing lint configuration (`select = ["E", "F", "I", "W", "UP", "B", "SIM"]`) catches stylistic and pyflakes-level bugs but does not gate any **structural** code-quality metric. As a result long functions, deeply nested control flow, and chained signatures with many parameters have accumulated in several modules — most visibly in `src/mdd/commands/confluence.py`, `src/mdd/commands/gitlab.py`, and the IR readers/writers.

This spec promotes a deliberate set of additional Ruff rules into the gate, fixes thresholds for them, and documents the grandfathering convention that lets us enable the gate today without a multi-day refactor blocking everything else.

The rationale for prioritising this in mid-2026 is empirical: published measurements of repositories where AI coding agents do significant unsupervised work show ~39% increases in cognitive complexity and ~18% increases in static-analysis warnings over a few months. Agents have none of the implicit human harness — no aesthetic disgust at a 300-line function, no organisational memory — so the gate has to be made explicit and machine-checkable.

## Requirements

### Rules enabled

The following rule categories MUST be present in `[tool.ruff.lint] select`:

```
"E", "F", "I", "W", "UP", "B", "SIM",                    # existing, retained
"C90",                                                    # mccabe cyclomatic complexity
"PLR0911", "PLR0912", "PLR0913", "PLR0915",              # size / branch / arg smells
"RUF",                                                    # ruff-native (dead noqa, mutable defaults, ...)
"FURB", "PERF", "C4", "PIE", "RET", "PGH",               # quality misc
"PTH", "TC", "PT", "ARG",                                # codebase-fit (pathlib, TYPE_CHECKING, pytest, unused args)
```

Thresholds (under `[tool.ruff.lint.mccabe]` and `[tool.ruff.lint.pylint]`):

| Setting | Value | Default | Rationale |
|---|---|---|---|
| `max-complexity` | 10 | (off) | Industry-standard McCabe ceiling. Functions above this are hard to test exhaustively. |
| `max-args` | 6 | 5 | One above default. Several call sites in the Confluence/SharePoint clients legitimately take config + client + path + a couple of options. |
| `max-branches` | 10 | 12 | Tighter than default — branches are the readability killer. |
| `max-statements` | 40 | 50 | Tighter than default. A 40-statement function is already getting hard to hold in one's head; 50 is too lax for new code. |
| `max-returns` | 6 | 6 | Default kept. |

### Rules explicitly NOT enabled

These were considered and rejected. Each rejection is sticky: do not re-add without reopening this spec.

| Code | Reason |
|---|---|
| `PLR0917` (too-many-positional-args) | Requires `preview = true` in Ruff; preview rules can change shape between releases. `PLR0913` already covers arg count. |
| `D` (pydocstyle) | The codebase doesn't enforce docstrings; enabling this would dump hundreds of low-value violations. |
| `ANN` (flake8-annotations) | basedpyright strict already enforces annotations more precisely. |
| `N` (pep8-naming) | High false-positive rate on legitimate naming (e.g. XML namespace prefixes, single-letter loop variables). Not the stated problem. |
| `S` (flake8-bandit) | ~~Noisy on `subprocess.run`, `tempfile`, `assert`, all of which are used deliberately. Security review is a separate concern.~~ **Reversed by the 2026-06-08 amendment below** — adopted with a curated ignore list. |
| `EM` (flake8-errmsg) | Pure style; no measurable quality improvement. |
| `TRY` (tryceratops) | Opinionated about exception patterns. The Confluence/SharePoint clients have nontrivial retry/error handling that this rule fights with. May revisit per-module. |
| `ERA` (eradicate) | Frequently wrong on TODO blocks and commented examples. |

### Per-file ignores

```toml
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["ARG001", "ARG002", "ARG005"]
```

**Why:** an initial survey showed 259 `ARG*` violations in `tests/` vs 16 in `src/`. The test hits are pytest fixtures, mock signatures, and parametrised callbacks — all false positives for the "this argument is dead code" reading. Excluding `tests/` keeps the 16 real signals in `src/` visible without drowning them.

### Suppressed sub-codes

The following Ruff sub-codes inside otherwise-enabled categories MUST be ignored project-wide:

```toml
ignore = [
    "RUF001",  # ambiguous unicode in strings
    "RUF002",  # ambiguous unicode in docstrings
    "RUF003",  # ambiguous unicode in comments
]
```

**Why:** the project handles Confluence and Markdown content, which legitimately contains em-dashes, curly quotes, NBSP, and other non-ASCII characters. Flagging these in strings/docstrings/comments produces ~26 false positives with no real signal.

### Grandfathering convention

Existing structural violations (C90/PLR09xx) MUST be silenced with a **targeted `# noqa: <code>`** comment on the offending `def` line — never with `--ignore` in config and never with a blank `# noqa`. Example:

```python
def update_page(  # noqa: PLR0913
    config: ConfluenceConfig,
    client: ConfluenceClient,
    page_id: str,
    body_md: str,
    title: str | None = None,
    version_message: str | None = None,
    parent_id: str | None = None,
) -> UpdateResult:
    ...
```

This makes the technical debt **visible at the function definition** rather than buried in a config file. Refactoring the function removes the `# noqa`; CI fails until the violation is genuinely gone.

Blanket `# noqa` (no code) is forbidden and is caught by `PGH004`. `RUF100` catches stale `# noqa` comments after a refactor lands.

### Pre-existing violations that block enabling the rules

The survey conducted on `9d51052` (main, 2026-05-15) found 921 violations across the proposed rule set. Categorised:

| Category | Count | Disposition |
|---|---|---|
| Structural (C90, PLR09xx) | 251 | Grandfather via `# noqa` per the convention above; refactor in priority order. |
| `ARG` in `tests/` | 259 | Per-file-ignored (see above). |
| `ARG` in `src/` | 16 | Investigate and fix or `# noqa: ARG00x` with a one-line reason. |
| Typing imports (`TC*`) | 171 | Mostly machine-fixable. |
| `RUF100` unused `# noqa` | 54 | Machine-fixable. |
| Ambiguous unicode (`RUF001..3`) | 26 | Suppressed at config level (see above). |
| Misc quality | ~120 | Mostly machine-fixable. |

Concentration of structural violations (top 6 files hold ~80 of 251):

```
17  src/mdd/commands/confluence.py
14  src/mdd/commands/gitlab.py
12  src/mdd/confluence/ir/writer.py
12  src/mdd/commands/ai.py
11  src/mdd/confluence/sync.py
11  src/mdd/commands/sharepoint.py
```

These six files are the priority refactor list.

## Amendment (2026-06-08): adopt flake8-bandit (`S`)

The original spec rejected `S` as "noisy … security review is a separate
concern." S43's supply-chain work
reframes that: source-level security smells *are* a standing quality
concern for a tool that shells out constantly (`glab`, `quarto`,
`rsvg-convert`, `op`, `rg`, AppleScript), makes httpx calls, parses XML
(`lxml`, for Confluence storage), loads YAML frontmatter, and handles
`op://` secrets. `S` is ruff's port of `bandit`; it is the cheapest way
to keep those smells from regressing. This amendment reopens the
rejection (per invariant 1 / 4, which require a spec amendment to add
`src/**` ignores) and adopts `S` with a curated suppression policy.

**Add to `select`:** `"S"`.

**Curated ignores (with rationale) — these are intentional, not debt:**

| Code | Scope | Rationale |
|---|---|---|
| `S404` (`import subprocess`) | project | We orchestrate external tools by design; importing `subprocess` is not a finding. |
| `S603` (`subprocess` call) | project | Calls never pass an untrusted shell string; arguments are fixed argv lists. `S602` (`shell=True`) stays **enabled** as the real signal. |
| `S607` (partial executable path) | project | We deliberately resolve `glab`/`quarto`/`rg`/`op`/`rsvg-convert` via `PATH`; absolute paths would break the install model. |
| `S101` (`assert`) | `tests/**` | pytest uses bare `assert`; only test code is exempted. |
| `S105`/`S106` (hardcoded password) | `tests/**` | Fixture credentials in tests are not secrets. |

**Stay enabled as hard signals** (illustrative, not exhaustive):
`S602` (`shell=True`), `S301`/`S302` (pickle/marshal), `S506`
(`yaml.load` without `SafeLoader`), `S113` (request without timeout),
`S501` (TLS verification disabled), `S324` (weak hash),
`S320` (unsafe `lxml` parsing).

**`S320` / lxml:** the Confluence IR readers parse storage XHTML with
`lxml`. Either adopt `defusedxml`'s lxml shim where untrusted input is
parsed, or carry a **targeted per-line `# noqa: S320`** with a one-line
reason at each genuine parse site (per the grandfathering convention).
This is decided per-call-site during the rollout, not blanket-ignored.

**Rollout** mirrors the original staged shape: a triage survey, then a
single PR that adds `"S"` to `select`, the project + `tests/**` ignores
above, and per-line `# noqa: S<code>` markers (each with a reason) for
any remaining genuine hits, landing `mise run ci` green. The per-file
`tests/**` ignore list grows by `S101`/`S105`/`S106`; the only new
`src/**` config-level ignores are `S404`/`S603`/`S607`, named here as
invariant 4 requires.

## Design Approach

**Ruff is the single static-analysis surface.** The 2026 Python tooling consensus has consolidated on Ruff for linting and basedpyright for type-checking. Adding a second tool for complexity (lizard, xenon, radon) would split the gate across two binaries with different config formats, two `mise.toml` tasks, and two CI failure modes. Ruff's McCabe + Pylint-refactor rules cover the structural metrics we need with one tool, one config block, one error stream.

**Cognitive complexity is deferred.** Ruff does not implement SonarQube-style cognitive complexity (which penalises nesting). [complexipy](https://github.com/rohaquinlop/complexipy) does, with a snapshot-based regression model that fits this project well. Adopting it is a separate decision and out of scope for this spec — it would be a follow-on spec adding `complexipy check --snapshot` to `mise run lint` once the McCabe-driven refactor pass has reduced the worst offenders. McCabe + the PLR0xxx size limits get most of the value at zero new tooling cost.

**SonarQube and friends are explicitly out of scope.** Self-hosted SonarQube requires a JVM, Postgres, and Elasticsearch, with ongoing maintenance estimated at 15–20 engineering hours per quarter. The signal-to-effort ratio is wrong for a single-package repo. Cloud-hosted variants (Codacy, DeepSource, Qodana) duplicate what Ruff gives us with a per-committer subscription. The structural metrics they pioneered have been ported to the Ruff/complexipy stack.

**Grandfathering > big-bang.** Enabling the rules and forcing a 921-violation cleanup before any other work can land would block the project for days. Grandfathering with targeted `# noqa` markers makes the gate active immediately for *new* code, makes existing debt visible at the function definition, and lets the refactor pass proceed at a sustainable rhythm.

**Tighter-than-default thresholds.** The defaults Ruff inherits from flake8/pylint were calibrated for codebases without aggressive type checking. With basedpyright strict already in place, our functions tend to be more declarative and shorter; the lower thresholds (40 statements, 10 branches) catch genuine over-growth earlier without false-positive churn on idiomatic code.

## Invariants going forward

These are the rules that MUST hold from S34 onwards:

1. **No structural threshold may be raised without a spec amendment.** Lowering thresholds (making them stricter) is fine and welcome. Raising `max-statements` from 40 to 50, etc., requires reopening this spec with rationale.
2. **Grandfathering `# noqa` MUST cite a specific code, never a bare `# noqa`.** PGH004 enforces this. Blanket suppression hides regressions.
3. **A grandfathered function MAY NOT grow.** If a function carries `# noqa: PLR0915`, any PR that *adds* statements to it MUST instead refactor it enough to remove the `# noqa`. Reviewer guidance, not machine-enforced — but it is the explicit expectation.
4. **`per-file-ignores` is scoped to `tests/**` only.** Adding ignores for `src/**` requires a spec amendment naming the file and the codes.
5. **`ignore` at config level is reserved for the three ambiguous-unicode codes listed above.** Other codes get per-file or per-line ignores with a reason.
6. **`mise run ci` MUST fail on any violation that is not grandfathered or per-file-ignored.** No "warn-only" mode. The gate is a hard gate.
7. **CI runs `ruff check` (not `ruff check --fix`).** Auto-fix is a developer-local convenience; CI checks the committed state.

## Implementation Notes

The rollout is staged into three review-sized PRs:

1. **Machine-fix pass.** Apply Ruff's safe + unsafe auto-fixes for the new rules (TC*, RUF100, RET505, C416, FURB110/188, PTH201, PIE810, PERF401, etc.). Pure mechanical change; small per-file diffs. No config change in this PR.
2. **Enable the gate with grandfathering.** Add the rule set to `pyproject.toml`, add `per-file-ignores` for `tests/**`, add the three `RUF00x` suppressions, and add targeted `# noqa: <code>` markers to every remaining structural violation. CI goes green at this point.
3. **Refactor pass (N PRs, one per hot file).** Walk the six top-offender files in priority order; each PR refactors one file, removes its `# noqa` markers, and lands independently.

The `mise run lint` task does not change in surface. The new rules are picked up automatically via the `pyproject.toml` change in PR 2.

`AGENTS.md` / `CLAUDE.md` gets a short pointer to this spec under a new "Code quality" section so future agents read the invariants before generating code.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- S13 — CI is the gate that enforces this spec; both pipelines invoke `mise run lint` and inherit the new rules automatically.
- [S01](S01-spec-based-development.md) — this spec exists because the structural quality of the codebase is a durable design concern, not a one-off cleanup task.

## Open questions

1. Should `complexipy` (cognitive complexity) be adopted as a follow-on once the McCabe-driven refactor pass has reduced the top-six offenders? **Resolved (2026-05-18) by [S37](S37-complexipy-cognitive-complexity.md):** yes, with threshold 15 and a snapshot-watermark grandfathering mechanism.
2. Should `TRY` be enabled on a per-module basis (e.g. `tests/**` excluded, `src/mdd/confluence/**` excluded, `src/mdd/cli.py` and `commands/**` enabled)? Deferred; revisit after the refactor pass.
3. Should `max-positional-args` be enforced once Ruff promotes `PLR0917` out of preview? Likely yes, with a threshold of 5. Revisit when Ruff stabilises the rule.

## Out of scope

- Cognitive-complexity tooling (complexipy / lizard / radon). Tracked as open question 1.
- SonarQube / Codacy / DeepSource / Qodana — explicitly rejected (see Design Approach).
- Architectural enforcement (tach, import-linter). The `src/mdd/` layout is already reasonably layered; formalising boundaries is a separate decision.
- Coverage thresholds beyond the existing `--cov-fail-under=70`.
- `pip-audit` (dependency vulnerability scanning) as a *lint* gate — it
  is a CI gate instead, per the CI/CD amendment. (The
  `bandit`-equivalent *source* scan is now in scope via the `S` rules —
  see the 2026-06-08 amendment above.)
- IDE / pre-commit integration. Developers already see Ruff via `mise run lint` and editor extensions; no project-level pre-commit hook is added.
