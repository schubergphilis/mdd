# S35: Argparse-based CLI parsing

**Purpose:** Replace `mdd`'s home-grown argument-parsing helpers and command-registry layer with a single argparse tree, eliminating several hundred lines of duplicated parsing and dispatch code.

**Status:** Implemented (2026-05-16)

## Introduction

Most of the `mdd` command modules implement their own flag parser. Today there are three coexisting styles:

1. **argparse** — already used by [`convert`](S03-convert-command.md).
2. **A bespoke flag-spec mini-framework** — `FlagSpec` / `consume_flags` / `_coerce_value` / `_require_value` living in `src/mdd/commands/_options.py` (~120 lines), paired with per-subcommand `@dataclass` opt holders. Currently consumed by `ai`, `gitlab`, and `sharepoint`. `confluence.py` keeps its own pre-extraction copy of the same framework inline.
3. **Hand-rolled `while i < len(args):` loops** — surviving in `lucid`, `search`, and `skills`. Each module reimplements value validation, error messages, and help printing on its own.

Each module also maintains a hand-written `_USAGE` triple-quoted string and a separate `USAGE: list[str]` consumed by a custom `_registry.py` that exists primarily to drive `mdd help`'s section-grouped output. The result is a `mdd help` listing that drifts out of sync with the actual flags, plus a 121-line `_options.py` plus a duplicate copy of the same framework still pinned inside `confluence.py`.

`argparse` from the standard library covers all of this and is already proven in the codebase (`convert.py`). This spec leans into the rewrite: single top-level argparse tree, all subcommand trees flattened to two levels, custom registry removed, error messages and help text from argparse defaults. No backward-compatibility shims — `mdd` has no external users yet.

## Requirements

- Every command module under `src/mdd/commands/` is wired into one top-level `argparse.ArgumentParser` built in `src/mdd/cli.py`. No hand-rolled flag loops remain.
- The home-grown helpers are deleted: `src/mdd/commands/_options.py` in full, the duplicate `_FlagSpec` / `_consume_flags` / `_coerce_value` / `_require_value` block still embedded in `confluence.py`, every per-opts `@dataclass` used purely for parsing, every `_print_usage` helper, every `_USAGE` triple-quoted string, and every `USAGE: list[str]` constant.
- `src/mdd/commands/_registry.py` is removed; command discovery happens via an explicit import list in `cli.py`. The section-grouped `mdd help` output is replaced by argparse's flat `mdd --help`.
- Subcommand trees flatten to at most two levels. `mdd <command> <verb>-<noun>` replaces every existing `mdd <command> <verb> <noun>` form. Concrete renames:
  - `mdd confluence sync space …` → `mdd confluence sync-space …`
  - `mdd confluence export page …` → `mdd confluence export-page …`
  - `mdd confluence create page …` → `mdd confluence create-page …`
  - `mdd confluence update page …` → `mdd confluence update-page …`
  - `mdd gitlab list repos` → `mdd gitlab list-repos`
  - `mdd gitlab create repo …` → `mdd gitlab create-repo …`
  - `mdd lucid list folders` / `mdd lucid list docs …` → `mdd lucid ls [PATH]` (single ls subcommand; see S25)
  - `mdd lucid sync folder …` → `mdd lucid sync-folder …`
  - `mdd sharepoint list sites` → `mdd sharepoint list-sites`
  - `mdd sharepoint sync site …` → `mdd sharepoint sync-site …`
  - `mdd sharepoint sync folder …` → `mdd sharepoint sync-folder …`
  - Subcommands already flat (`mdd ai rewrite|index|review`, `mdd skills list|install|uninstall`, `mdd confluence whoami`, `mdd gitlab push|status`) stay as they are.
- Deprecated/alias subcommands (e.g. `mdd sharepoint export site` / `export folder` forwarders) are deleted rather than ported. No transitional aliases.
- `mdd echo` survives as a smoke test (the only flat top-level subcommand with no real work to do).
- `mdd <subcommand> --help` and `mdd <subcommand> <sub-subcommand> --help` work at every level (argparse default).
- `mdd --help` (and `mdd` with no args) produces the top-level subcommand listing. The grouping that `_registry.by_section()` provided today is dropped; the flat argparse listing is the canonical view.
- A shared parent parser provides `--config <file>` and `--dry-run` for the subcommands that take them; ad-hoc redeclarations are removed.
- Top-level logging flags (`-v`, `-vv`, `-vvv`, `--trace`, `--trace-bodies`, `--log-level=`) keep working. They MAY move from a manual pre-pass to argparse global options if that simplifies the dispatcher — see [Design Approach](#design-approach).
- Argparse's default error phrasing and exit code (`SystemExit(2)` on parse failure) are accepted everywhere. No wrapping of `parser.error()`.
- Test coverage does not regress. Tests that asserted on the old `"Error: …"` wording switch to substring checks on argparse's phrasing or to exit-code-only assertions.
- The change set lands incrementally, one heavy module per PR after an architecture-setup PR.

## Design Approach

### One global argparse tree, built in `cli.py`

`src/mdd/cli.py:build_parser()` returns a single top-level `ArgumentParser(prog="mdd")`. It owns:

- The top-level logging flags as real argparse arguments on the root parser.
- A `subparsers = root.add_subparsers(dest="command", required=True)` factory.
- An explicit list of `from mdd.commands import echo, convert, …` imports, each followed by `module.register(subparsers, parents=COMMON_PARENTS)`.

Each command module exposes:

```python
def register(subparsers, parents) -> None:
    parser = subparsers.add_parser("name", parents=[parents.common], help="…", description="…")
    sub = parser.add_subparsers(dest="subcommand", required=True)  # if any
    p1 = sub.add_parser("verb-noun", parents=[parents.config_required], help="…")
    p1.add_argument(...)
    p1.set_defaults(func=_run_verb_noun)
    ...
```

No per-module `cmd_<name>(args: list[str]) -> int` entry point; routing is `ns.func(ns)`.

### Shared parent parsers

`cli.py` constructs one or two parent `ArgumentParser(add_help=False)` instances and passes them to each module via a small `CommonParents` struct (or simply a tuple of two parsers). Examples:

- `common` — only `--verbose` reporting flags if any survive the logging-flag relocation; else empty / unused.
- `config_required` — adds `--config <file>` with `type=Path`, `default=None`.
- `dry_run` — adds `--dry-run` (`action="store_true"`).

Subparsers that need both compose them: `parents=[config_required, dry_run]`.

If a parent parser saves fewer than two declarations per consumer (one declaration in two subparsers), keep flags inline — parents that don't pay for themselves are noise.

### `_registry.py` is removed

The registry exists today only to (1) auto-discover command modules and (2) drive `mdd help` section ordering. Argparse handles discovery via the explicit import list in `cli.py`; section ordering goes away with `mdd help`. Net deletion: ~70 lines plus the corresponding `register(...)` boilerplate in every command module.

`mdd help` either becomes a thin wrapper that prints `root_parser.format_help()` and exits, or is deleted in favour of `mdd --help`. Preference: keep the `mdd help` subcommand as a synonym for `mdd --help` because shell users type it more often, but back it with the same code path.

### Each subcommand handler signature

```python
class _SyncSpaceArgs(argparse.Namespace):
    config: Path | None
    space_key: str
    dry_run: bool


def _run_sync_space(ns: argparse.Namespace) -> int:
    args = cast(_SyncSpaceArgs, ns)
    space_key = args.space_key
    dry_run = args.dry_run
    ...
```

See the [typed-Namespace adapter convention](#typed-namespace-adapter-2026-05-amendment) below for the rationale; the convention was added as a 2026-05 amendment to the original S35 rollout (which used `value: T = ns.attr  # pyright: ignore[reportAny]` typed locals).

### Top-level logging flags

Two options:

- **A (preferred)**: declare `-v` / `-vv` / `-vvv` / `--trace` / `--trace-bodies` / `--log-level=` as real argparse arguments on the root parser. Argparse handles them in normal `parse_args()` and the subcommand handler can read `ns.log_level`. Pre-pass is gone.
- **B (fallback)**: keep `_extract_log_flags()` as today. Use this only if a real argparse conflict surfaces (e.g. a subcommand also wants `-v` for something).

Default: A. If a conflict surfaces while migrating a specific module, fall back to B and note it in the migration plan.

### Tests

Per-command test files (`tests/commands/test_*.py`) stay where they are. They now exercise the global parser via `mdd.cli.main([...])` rather than `cmd_<name>([...])`. A small helper `parse_and_run(argv: list[str]) -> tuple[int, str, str]` returning `(exit_code, stdout, stderr)` can live in `tests/_argparse_helpers.py` if it removes repeated `capsys` boilerplate; otherwise leave per-test.

### CI scripts and tooling

The few internal scripts and `mise.toml` tasks that shell out to `mdd <subcommand>` need a sweep for the flattened names. The migration plan calls out specific paths to grep. Examples in agent skills under `.claude/skills/` MUST be updated to use the new flat names.

## Implementation Notes

- PR 1 lands the architecture (global parser, parents, registry deletion) alongside the trivial modules; subsequent PRs migrate one heavy module each, smallest-to-largest, so the recipe is hardened before it meets `confluence.py`.
- `convert.py` already uses argparse but with its own `build_parser()` returning a standalone `ArgumentParser`. PR 1 also rewires `convert` into the global tree via `register(subparsers, parents)`.
- The `confluence.py` migration deletes both its embedded copy of the framework and the shared `_options.py`, and lands last so the recipe is exercised on smaller modules first.
- Residual `# noqa: C901,PLR09xx` markers remain in `lucid.py`, `search.py`, and `skills.py` from before the [S34](S34-code-quality-gates.md) hot-file pass. The argparse migration is expected to clear most of them incidentally; `RUF100` will flag any that survive a sufficiently flat handler.
- No new third-party dependency is introduced; `argparse` is in the standard library.

## Typed Namespace adapter (2026-05 amendment)

The original S35 rollout used `value: T = ns.attr  # pyright: ignore[reportAny]` typed locals at the top of every `_run_*` handler. That pattern shipped 132 `# pyright: ignore[reportAny]` suppressions across `src/mdd/commands/`. This amendment replaces the convention with a per-handler `argparse.Namespace` subclass + `typing.cast`, which is the stdlib-documented pattern for getting strict-typed handler bodies without leaving vanilla argparse.

### Convention

Each `_run_<name>` handler is paired with a private `_<Name>Args(argparse.Namespace)` subclass declared in the same module. The subclass declares one annotated attribute per `add_argument` call that the handler consumes, with the same `dest` name and the same type the argparse `type=` argument coerces to. The handler casts once at the top and reads only typed attributes thereafter.

```python
class _ExportPageArgs(argparse.Namespace):
    config: Path | None
    output: Path | None
    page_ref: str
    include_export_header: bool
    skip_attachments: bool


def _run_export_page(ns: argparse.Namespace) -> int:
    args = cast(_ExportPageArgs, ns)
    output_dir = args.output if args.output is not None else Path()
    page_ref = args.page_ref
    include_header = args.include_export_header
    skip_attachments = args.skip_attachments
    ...
```

Rules:

- The Namespace subclass MUST live next to its `_run_*` handler — same module, named `_<Verb><Noun>Args`. No central namespaces module.
- The subclass MUST list every `dest` the handler reads, and only those `dest`s. Root logging flags (`verbose`, `trace`, `log_level`, etc.) and `_root_parser` are NOT declared on per-command subclasses; if a handler reads them, declare them locally too. Reading root state from `_run_*` handlers is rare and discouraged outside `cli.py`.
- The cast happens once at the top of the handler. `ns` is not read directly anywhere else in the body.
- The subclass MUST NOT carry a `__slots__`, `__init__`, or methods. It is a pure typing artefact — argparse populates the instance.
- No `# pyright: ignore[reportAny]` may remain on lines covered by `args.<attr>` reads after the convention is applied.
- The `set_defaults(func=_run_<name>)` line stays unchanged. The Namespace subclass is never passed to `parse_args`; the cast happens at handler entry.

### Why cast and not `parse_args(namespace=...)`

argparse only accepts one Namespace at `parse_args()` time. With subparser dispatch (the S35 design), the top-level parser does not know which subcommand will be selected until parsing completes. Passing a typed Namespace at parse time would require building a union Namespace that includes every subcommand's fields, defeating the purpose. `cast` at handler entry is the canonical workaround and is documented as such by the basedpyright community.

### Trade-offs (recorded for posterity)

- **Cast is an unchecked assertion.** Pyright trusts the cast; runtime trusts argparse to populate the attrs. The only way the assertion is wrong is a programmer error where the handler reads an attr the parser doesn't add. Tests already exercise each `_run_*` end-to-end via `mdd.cli.main([...])`; misalignments surface as `AttributeError` in tests, not silently.
- **Field declarations are duplicated next to `add_argument`.** The Namespace subclass restates each `dest` and type. This duplication is the price of vanilla argparse + strict typing. Alternatives evaluated (dataclass `from_ns`, `getarg` helper, `pydantic-settings CliApp`, `cyclopts`, `tyro`, `Tap`) either kept the duplication, introduced framework churn, or regressed `--help` output quality. The full evaluation is in P03 session D's DONE stanza.
- **One Namespace subclass per `_run_*` handler.** ~30 small classes across 16 modules. They are short (5–15 lines each) and live next to the handler that owns them.
- **Root flags stay typed in `cli.py`.** `cli.py:_resolve_log_level` and `cli.py:_apply_logging` use the same cast pattern with a `_RootArgs(argparse.Namespace)` subclass.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [S02 — mdd CLI Tool](S02-mdd-cli-tool.md) — the dispatcher this spec largely replaces
- [S34 — Code Quality Gates](S34-code-quality-gates.md) — the structural-violation gate that this refactor incidentally helps satisfy

## Open questions

(All four original open questions have been resolved by the design decisions above.
This section is left as a placeholder in case implementation surfaces new ones.)

## Out of scope

- Backward compatibility shims. The CLI shape shifts: subcommand renames, argparse-default error wording, `SystemExit(2)` on parse failure, no transitional aliases for `mdd confluence sync space` and friends. `mdd` has no external users yet; this is the moment to standardise.
- A click / typer / fire migration. The trade-off (third-party dep, doctest-style help vs. familiar argparse output, type-driven decorators) is not worth it for this codebase; `convert.py` is already proof that argparse fits.
- Section grouping in `mdd --help`. The custom `_registry.by_section()` output is dropped; the flat argparse listing is the canonical view. A custom `HelpFormatter` could restore grouping later if anyone misses it.
- Renaming entire commands (e.g. `mdd confluence-sync` as a top-level verb instead of `mdd confluence sync-space`). Only the verb-noun flattening is in scope; raise a separate spec for further reshuffles.
