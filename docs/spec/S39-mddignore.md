# S39: `.mddignore` source-side filtering

**Purpose:** Add a `.gitignore`-style `.mddignore` file (plus matching `--ignore=<path>` CLI flag) that filters source content **before** download/conversion during `mdd` sync commands, so users can skip large or uninteresting subtrees (e.g. `Archive/`, `old/`) without post-sync cleanup.

**Status:** Implemented (2026-05-24)

## Introduction

Several `mdd` sync commands pull content from remote sources into a local mirror repo:

- [`mdd sharepoint sync-site` / `sync-folder`](S18-sharepoint-sync.md) — reads OneDrive-mirrored SharePoint trees and converts office files to markdown.
- [`mdd confluence sync`](S14-confluence-sync.md) — reconciles a Confluence space against a local mirror.
- `mdd lucid sync-folder` — mirrors Lucid Cloud team folders. A
  wrapper-supplied command (the private SBP layer), included here because
  it consumes the same matcher.

None of these commands currently expose a way to skip source paths. Every file under the configured root gets pulled and converted. On real corpora this is painful: our "Labs" SharePoint mirror produces a ~12 GB working tree, of which roughly 7 GB lives in `*/Archive/` and `*/old/` subtrees the user has no interest in. The only existing workaround is to delete those folders after each sync, which is tedious and gets undone on the next run.

[`utils/blacklist.py`](S07-data-protection.md) (the data-protection gate) is a coarse, whole-space/whole-site confidentiality gate — see S07 for exactly which commands it covers and when it fires. It does not, and is not designed to, do per-path filtering. They are different layers and do not interact.

This spec defines a single shared source-side filter — `.mddignore` — usable by all three sync commands above. The first wiring landed in SharePoint; Confluence wiring landed on top of the same matcher (see [Confluence wiring](#confluence-wiring) below); Lucid wiring follows as separate work.

## Requirements

### File format and pattern syntax

- Pattern syntax is **gitignore wildmatch**, delegated to the [`pathspec`](https://pypi.org/project/pathspec/) library (the de facto Python gitignore matcher used by `pre-commit`, `black`, `mypy`, and `ruff`). `mdd` MUST NOT reimplement gitignore semantics.
- A `.mddignore` file is a UTF-8 text file containing one pattern per line; lines starting with `#` are comments; blank lines are ignored. The full gitignore grammar applies, including `**`, `/`-anchoring, `*` globs, and `!` negation (with whatever precedence rules `pathspec` already implements — `mdd` MUST NOT layer additional negation semantics on top).
- Patterns are matched against **POSIX-style forward-slash relative paths** rooted at the destination mirror root, regardless of the host platform. This matches gitignore's own behaviour and keeps `.mddignore` files portable between contributors on macOS, Linux, and Windows.

### File location

- The canonical location is **root-only**: a single `.mddignore` at the destination mirror root (the same directory that holds the synced markdown tree).
- Nested per-directory `.mddignore` files are out of scope for v1 (see [Out of scope](#out-of-scope)). Only the root file is read.
- If no `.mddignore` exists at the root, and no `--ignore` flag is passed, sync behaviour is **identical** to today's: every source path is considered.

### CLI flag: `--ignore=<path>`

- All sync commands that consult `.mddignore` MUST also accept a `--ignore=<path>` flag pointing at an alternate ignore file.
- `--ignore` may be supplied **multiple times** on a single invocation; all named files are loaded and their patterns combined.
- The flag exists primarily for the bootstrap case — when the destination repo does not yet exist (or does not yet contain a `.mddignore`) and the user wants to start the first sync with an ignore set already in effect.

### Precedence: CLI vs. dest-repo file

- When both `--ignore=<path>` and `<dest>/.mddignore` exist, the effective pattern set is the **union** of all loaded files. Both apply.
- There is no "CLI overrides dest" or "dest overrides CLI" mode. Union is the only behaviour. Document this in `--help` so the user does not expect git-style "the closer file wins" precedence.

### Precedence vs. `utils/blacklist.py`

- `.mddignore` and the blacklist gate operate at different layers and are not designed to interact: `.mddignore` filters *which paths* within an otherwise-permitted space/site get pulled; the blacklist gate governs *whether `mdd` touches the space/site at all* — see [S07](S07-data-protection.md) for its exact trigger condition.
- Neither filter overrides or short-circuits the other. Skipping a path via `.mddignore` says nothing about whether that path's space/site is blacklisted, and vice versa.

### Already-synced state

- `.mddignore` MUST match `git`'s `.gitignore` behaviour for pre-existing content: **it only blocks new pulls.** Files that are already present in the destination working tree are left alone, even if a newly-added pattern would match them.
- The matcher MUST NOT delete or rename existing files on the basis of a newly-matched pattern during a normal sync.
- The matcher MUST NOT warn or log about pre-existing matches during a normal sync. (A user adding `*/Archive/*` to `.mddignore` after a 12 GB sync should not be flooded with thousands of "would-skip" notices for content that is already on disk.)
- Cleaning up already-synced content that newly matches an ignore pattern is the user's responsibility by default. The opt-in [`--prune-ignored`](#opt-in-cleanup-prune-ignored) flag automates it per-invocation.

### Opt-in cleanup: `--prune-ignored`

The default-off `--prune-ignored` flag is an explicit, per-invocation escape hatch for the "I added a pattern after a large sync, clean it up" case. Auto-prune-on-pattern-add is forbidden: every cleanup MUST be requested explicitly on the command line. The flag MUST be available on every sync command that consults `.mddignore`.

Behaviour:

- When `--prune-ignored` is set, sync walks the destination mirror tree **before** the normal sync runs and deletes every file whose POSIX-style relative path is matched by the loaded matcher (the same union of `<dest>/.mddignore` plus any `--ignore=<path>` arguments used by the normal-sync match).
- The walk MUST be confined to the matcher's relative-path domain. Out of scope, never deleted:
  - The dest-root `.mddignore` file itself.
  - Any path outside the destination mirror root.
  - The destination's `.git/` (and other VCS metadata) and any other dotfiles at the mirror root.
- Pruning runs once, at sync start, in a single pass. The normal sync walk follows immediately after.
- Counters: pruned files are surfaced as a separate `N pruned (ignored)` summary line alongside the existing `N skipped (ignored)`, `N converted`, `N copied`, `N unchanged` totals. `pruned` and `skipped` do not overlap — `pruned` is the local cleanup; `skipped` is the source-side filter that runs afterward.
- Logging: each deletion MUST emit one INFO-level line naming the path. Destructive operations need an audit trail in scrollback; a single summary count is not sufficient.

Interactions with other flags:

- **`--dry-run`** combined with `--prune-ignored`: the prune pass logs each path it WOULD delete (INFO, prefixed to make the dry-run intent visible) but performs no deletion. The summary line reads `N pruned (ignored, dry-run)`.
- **`--read-only`** combined with `--prune-ignored` MUST be rejected at argument-parse time with a clear error and a non-zero exit code. Both flags are explicit user choices about destructiveness; the combination is contradictory ("don't write to the source" + "delete locally") and silently picking one would be surprising. Users who want a local prune without source writes can run `--prune-ignored` alone (the SharePoint/Confluence `--read-only` semantics never required this combination to begin with).

`--prune-ignored` is supported in `mdd sharepoint sync-site` / `sync-folder` and `mdd confluence sync-space`. The `mdd lucid sync-folder` wiring depends on that command first consuming `.mddignore` (the matcher-load and `--ignore` plumbing land separately as part of the v1 follow-up wiring).

### Performance: directory-level pruning

- For patterns that are **trivially folder-anchored** (e.g. `Archive/`, `*/Archive/`, `**/old/`), the matcher MUST support **directory-level pruning** — when a sync walks the source tree and encounters a directory whose every descendant would be ignored, the walker can skip listing that directory entirely. On a SharePoint corpus this is the difference between a 100k-file traversal and a 5k-file traversal.
- For patterns that cannot be statically resolved at the directory level (e.g. `*.tmp` — siblings of any extension may exist), the matcher MUST fall back to **per-file** filtering. Directory pruning is a performance optimisation, never a correctness shortcut: if any descendant **might not** match, the directory MUST be walked normally and each file checked.
- `pathspec` exposes the per-pattern metadata needed to draw this distinction (anchored vs. unanchored patterns, trailing-slash patterns vs. extension patterns). The matcher API surfaces a `prune_dir(rel_dir)` method that returns `True` only when the pattern set guarantees every descendant is ignored.

### Sync command behaviour

When a sync command consults the matcher:

- A skipped file MUST NOT be downloaded, converted, or otherwise touched. The point of source-side filtering is to avoid the cost of pulling content that will not be kept.
- A skipped file MUST be counted in the per-sync summary line so the user can verify the filter is doing what they expect — e.g. `N skipped (ignored)` alongside the existing `N converted`, `N copied`, `N unchanged` totals.
- A pruned directory MUST NOT be walked. Pruning is silent at debug-log level; summary counts roll the pruned descendants into `N skipped (ignored)` when the walker can cheaply estimate them, but exact counts are not required for pruned subtrees.

### Single shared matcher

- The matcher is implemented **once**, in a shared module (sketch: `src/mdd/utils/mddignore.py`), and consumed by `sharepoint`, `confluence`, and `lucid` syncs through the same API. There is no per-source-type fork of gitignore semantics.
- The API surface is small: load from a dest-repo root plus zero-or-more CLI paths, ask whether a relative path is ignored, ask whether a directory can be pruned. No source-specific knowledge lives in the matcher itself.

## Design Approach

**Delegate gitignore semantics to `pathspec`.** Reimplementing `**`, anchoring, and negation precedence is a known trap; `pathspec` is the standard Python implementation and is already battle-tested by the major linters/formatters. The dependency footprint is small (pure Python, no transitive deps of its own).

**Root-only over nested.** Nested `.gitignore`-style files are subtle (closer files override further ones; deletes-from-ignore via `!` interact with parent files). `git` itself shipped without nested ignores for the first decade. There is no concrete user demand for nesting in `mdd` today; deferring it costs nothing and avoids locking in precedence rules prematurely. If nesting is requested later, the matcher API can grow without breaking the v1 contract.

**Union, not override, for CLI + dest file.** The CLI flag's purpose is bootstrap — the dest repo does not exist yet, so there is no `.mddignore` to either override or compose with. Once the dest repo exists and contains a `.mddignore`, the CLI flag is essentially additive in practice. Union semantics make that explicit and avoid the surprising case where a user passes `--ignore=foo` to "add to the rules" and silently loses the dest-repo file.

**`.mddignore` and the blacklist operate at different layers.** `.mddignore` is a per-path cost-saver within a space/site `mdd` is otherwise allowed to touch (don't waste bandwidth and disk on `Archive/`). The blacklist ([S07](S07-data-protection.md)) is a whole-space/whole-site confidentiality gate — see S07 for its exact trigger condition. Statement of non-interaction, not a precedence rule.

**Match git on already-synced content; opt-in cleanup is explicit per invocation.** Users have strong, deeply-trained intuition for `.gitignore`: adding a pattern does not delete tracked files. Matching that intuition is the right default. Cleanup of already-synced content lives behind `--prune-ignored`, which is opt-in per invocation, never sticky, and never inferred from `.mddignore` edits. The `--read-only` + `--prune-ignored` combination is rejected rather than silently resolved — both flags are explicit choices about destructiveness, and the safe move is to make the user pick one rather than guess.

**Directory pruning as a performance optimisation, never a correctness shortcut.** The matcher distinguishes "can prove every descendant is ignored" (prune) from "might have ignored descendants" (walk + per-file filter). The classification is conservative: when in doubt, walk. `pathspec` exposes the per-pattern information needed (e.g. whether a pattern is folder-anchored with a trailing `/`, whether it carries `**`, whether it has an extension glob that could match anything).

**Single shared matcher, source-type agnostic.** Defining the matcher once means SharePoint, Confluence, and Lucid all benefit from the same gitignore implementation, the same union semantics, and the same prune logic. The cost of designing for all three up front is low; the cost of retrofitting later is higher (each source would otherwise grow its own subtly-different filter).

## Implementation Notes

### Matcher module

Sketch (interface, not contract):

```python
@dataclass(frozen=True)
class MddIgnore:
    spec: pathspec.PathSpec        # combined union of all sources
    sources: tuple[Path, ...]      # for debug / future --explain

    @classmethod
    def load(cls, dest_repo_root: Path, cli_ignore: Iterable[Path] = ()) -> "MddIgnore":
        """Load .mddignore from dest root plus any --ignore paths. Missing files are silently empty."""

    def is_ignored(self, rel_path: Path, *, is_dir: bool) -> bool:
        """True iff the path would be ignored. POSIX-style rel paths internally."""

    def prune_dir(self, rel_dir: Path) -> bool:
        """True iff every descendant of rel_dir is provably ignored.
        Conservative: returns False when in doubt."""
```

The matcher lives in `src/mdd/utils/` so all three sync packages can import it without creating a cross-package dependency.

### Consumers

Each sync command wires the matcher in two places:

1. **At sync start**, load the matcher once from `<dest>/.mddignore` plus any `--ignore` flag values.
2. **At directory enumeration**, call `prune_dir(rel)` before listing; skip the subtree when it returns `True`.
3. **At file consideration**, call `is_ignored(rel, is_dir=False)`; on `True`, skip download/conversion and increment a per-sync `skipped_ignored` counter.

For SharePoint specifically (the first wiring), the natural touch points are the sync walker in `src/mdd/sharepoint/sync.py` and the per-file decision function in `src/mdd/sharepoint/rules.py`. A new `FileAction` variant (e.g. `SKIP_IGNORED`) carries the skip through the existing action pipeline so the summary builder can count it without bespoke plumbing.

For Lucid, the wiring is analogous but is **not** part of this spec's first delivery — it is follow-up work tracked separately. The matcher API is designed so the wiring is small (load once, ask `is_ignored` per file, ask `prune_dir` per subtree).

### Confluence wiring

Confluence has no filesystem paths to match against — a page's location is
a title chain in the Confluence tree, not a directory on disk until
`export`/`sync` decides where its markdown file lands. `src/mdd/confluence/sync/mddignore.py`
bridges this: for every page in `sync-space`'s desired-state map it walks
the same tree-building and filename-sanitisation logic `build_path_map`
(`mdd.confluence.export`) uses, and derives the same two rel-paths the
matcher needs — the page's own `<title>.md` rel-path, and the rel-path of
the directory that would hold its children. Those synthetic rel-paths are
then checked with `is_ignored` / `prune_dir` exactly as a filesystem sync
would check a real path.

Two filter passes run per `sync-space` invocation, mirroring the
directory-pruning and per-file requirements above:

1. **Subtree pruning** — a page's child-subtree rel-path is checked with
   both `is_ignored(..., is_dir=True)` (catches a literal `Archive/`
   pattern even on a leaf page, which has no descendants to prove
   `prune_dir` right) and `prune_dir` (catches patterns like
   `**/Archive/` that only resolve once descendants are considered).
   Either match drops the page and every descendant from the desired-state
   map in one shot — the bulk-saving case.
2. **Per-page filtering** — every page that survives pruning is checked
   individually against its own `<title>.md` rel-path.

Pages already tracked locally (present in the current-state map, i.e.
already have a `page_id` in some file's frontmatter) are never dropped,
matching the "ignore blocks new pulls only" contract — the same rule the
SharePoint wiring follows.

### `--ignore` flag

Each consumer CLI (`mdd sharepoint sync-folder`, `mdd sharepoint sync-site`, and `mdd confluence sync-space`) accepts `--ignore=<path>`, declared via `argparse` with `action="append"` so it can be supplied multiple times. `--help` documents the union semantics and the relationship to `<dest>/.mddignore`.

### `--prune-ignored` flag

Each consumer CLI accepts `--prune-ignored` (boolean, default `False`), declared via `argparse` with `action="store_true"`. Each consumer's argument parser MUST reject the combination of `--prune-ignored` and `--read-only` (where `--read-only` exists) at parse time, e.g. via `parser.error(...)` after `parse_args` or an equivalent post-parse check.

The matcher module exposes a `walk_prunable(dest_root: Path) -> Iterator[Path]` helper that yields every file under `dest_root` whose matcher relative path returns `is_ignored == True`. The helper enforces the safety domain (skips `dest_root/.mddignore`, skips dot-prefixed entries at the mirror root, never escapes `dest_root`). Each sync command consumes this helper, deletes (or, under `--dry-run`, only logs) each yielded path, and increments a `pruned_ignored` counter for the summary line.

### Summary line

The per-sync summary line gains `N skipped (ignored)`. This makes the filter visible — a user adding a pattern can verify it is matching by running once and looking at the count.

### Migration

Existing mirrors continue to work unchanged: with no `.mddignore` and no `--ignore` flag, the matcher is empty and `is_ignored` is `False` for every path. Sync output is byte-identical to today's. There is no schema change, no state-file migration, no rerun-after-upgrade requirement.

For users who want to start filtering an existing mirror:

1. Add `.mddignore` at the dest repo root with the desired patterns.
2. Run sync. New pulls under matching paths are skipped.
3. Manually delete any already-synced content under those paths (`rm -rf …`) if cleanup is desired. `mdd` will not re-pull it.

## Related upstream specs

- [000-specs](000-specs.md) — shared spec conventions.
- [S07](S07-data-protection.md) — `utils/blacklist.py` is the whole-space/whole-site confidentiality gate; `.mddignore` is the per-path source filter. Different layers, no interaction.
- [S10](S10-sharepoint-command.md) — `mdd sharepoint` consumes the matcher for OneDrive-backed sync.
- [S14](S14-confluence-sync.md) — `mdd confluence sync` is the second consumer, wired directly into `sync-space` (see [Confluence wiring](#confluence-wiring) above).
- [S18](S18-sharepoint-sync.md) — bidirectional SharePoint sync; the matcher gates the pull half.
- The private Lucid mirror — `mdd lucid sync-folder`, a wrapper-supplied
  command, is the third consumer (follow-up wiring).

## Open questions

1. Should the matcher accept `.mddignore` files passed as **stdin**, for one-shot CI invocations that do not want to write a temp file? Probably yes via `--ignore=-`, but defer until a real need appears.
2. Should `prune_dir` be exposed as a CLI verb (`mdd sharepoint explain-ignore <path>`) for debugging? Likely useful but not blocking; revisit after first wiring lands.

## Out of scope

- **Nested per-directory `.mddignore` files.** Only the dest-repo root is read. Adding nesting later is forward-compatible with this design but is not v1.
- **Custom precedence on `!negation`.** Whatever `pathspec` does is what `mdd` does. `mdd` MUST NOT add its own layer of negation/precedence rules.
- **Regex patterns.** Patterns are gitignore wildmatch only; no `pcre`/`re` syntax.
- **Source-side `.mddignore` (pushed up to SharePoint/Confluence/Lucid).** The file lives in the destination mirror only. The source is read-only as far as the ignore mechanism is concerned.
- **Auto-prune on pattern add.** `--prune-ignored` is per invocation and never sticky. `mdd` does not detect "the matcher changed since the last sync" and run an implicit prune; the user must request cleanup explicitly each time.
- **Wiring into `mdd lucid sync-folder`.** The matcher is designed once for all three sync commands; SharePoint and Confluence are wired (see [Confluence wiring](#confluence-wiring) above). The Lucid follow-up consumes the same matcher with no API changes expected.
- **Replacing or merging with [`utils/blacklist.py`](S07-data-protection.md).** The blacklist remains a separate gate — see S07 for its mechanism.
