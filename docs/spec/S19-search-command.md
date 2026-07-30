# 019 - search command

**Purpose:** `mdd search "<query>"` is a thin ripgrep wrapper that searches markdown across all configured mirror locations.

**Status:** Implemented (2026-05-08)

## Introduction

`mdd search` returns matches in a human-readable or JSON form. No AI, no network, no token. Built first so agents and humans can use it immediately. Mirror locations include Confluence spaces, SharePoint sites, docs repos, and any further root source a wrapper distribution registers.

Originates from research note R03.

## Subcommands

```
mdd search "<query>" [--space SPACE] [--site SITE] [--source TYPE:ID]
                     [--include <path>] [--exclude <path>]
                     [--type md|qmd|all]
                     [--limit N] [--per-file-limit N]
                     [--sort]
                     [--include-frontmatter]
                     [--json]
                     [--color auto|always|never]
                     [--trace]
                     [--exclude-blacklisted]
```

## Requirements

**Search roots from config**
- Root sources are **registered**, not hardcoded: each one declares
  its config file, the top-level section, and the key holding the
  identifier → block mapping. The core registers three built-ins:
  - `confluence.spaces.<key>.output_dir`
  - `sharepoint.sites.<name>.output_dir`
  - `docs.<name>.output_dir` (a plain directory of markdown docs, one
    entry per mirror repository)
- A wrapper distribution registers further sources from its CLI entry
  point — the same seam as the mirror-backend registry — so the core
  ships no search filter for an integration it does not have. The SBP
  wrapper registers `lucid.folders.<name>.output_dir` this way.
- Every configured block is read the same way, so a registered source
  needs no loader of its own.
- Roots that don't exist locally are skipped silently (the user may
  not have cloned every mirror).
- `--include` adds an extra root for one run; `--exclude` removes
  one.

**Filters**
- `--source TYPE:ID` restricts to one root of any registered source
  type. `--space SPACE` and `--site SITE` are shorthands for the two
  built-ins (`confluence:` and `sharepoint:`). All are repeatable.
  An unregistered `TYPE` is an argparse error listing the registered
  types.
- When any filter is set, results are restricted to roots from the
  source types whose filter is active. `--site AI` returns only
  sharepoint roots matching `AI` (no confluence, no docs). `--space
  Labs` against a config with no `Labs` space returns nothing, even
  if a sharepoint site named `Labs` exists. Identifier matching is
  case-insensitive. `--include` paths are kept regardless.
- `--type md` (default), `--qmd`, or `--all` controls the file
  filter.
- `--limit N` caps total matches across all roots (default 10).
  In streaming mode this also stops `rg` early — once N matches
  have been emitted the process is terminated.
- `--per-file-limit N` caps matches inside a single file
  (default 50); forwarded to `rg --max-count`.
- `--color {auto,always,never}` colorizes human output (default
  `auto`). When enabled, matched spans render in bold red, file
  paths in magenta, line numbers in green, and metadata labels
  (`Title:`, `(page N)`) in dim. `NO_COLOR` and `FORCE_COLOR`
  environment variables are honoured. JSON output is never
  colorized regardless of this flag.
- `--trace` prints the resolved `rg` argv to stderr before
  invoking it, prefixed with `[mdd search]`. Useful for
  reproducing a search outside the wrapper.

**Long-line truncation (human output only)**

Matched lines longer than 500 characters are truncated for human
display, keeping the matched span roughly centered. `…` is inserted
on whichever side(s) had content elided. The ANSI-highlighted span
still wraps the original matched text. The JSON output preserves
the full line in `snippet`.
- `--exclude-blacklisted` filters out content from blacklisted
  ([S07](S07-data-protection.md)) spaces / sites. Off by default — local search is
  unrestricted because the user already has the content on disk;
  the blacklist gates *publishing*, not reading.

**Backend: ripgrep**
- Shell out to `rg --type md` (or `--type qmd` etc.) with smart-case
  matching, per-file match cap, and `--json` when requested.
- Require `rg` on `PATH`; if missing, exit 1 with an actionable
  install hint (`brew install ripgrep` / `apt install ripgrep`).
- Don't roll a Python search backend; ripgrep is fast enough at the
  scale and battle-tested.

**Output**

Default human-readable: streamed as `rg` produces matches. For each
file, a header line (mirror-prefixed path + optional `(page N)`)
and a `Title:` line are emitted before its first match, followed by
a blank line, then one `Lnn:` line per match.

Example:
```
confluence/ENGINEERING/Onboarding/New Hire Setup.md  (page 4521)
  Title: New Hire Setup

  L42:  - Provision laptop via the IT portal
  L48:  Note: see also the [HR onboarding checklist]

sharepoint/Engineering/HR/Joining.docx.md
  Title: Joining checklist

  L12:  - Laptop provisioned by IT
```

**Streaming vs. sorted output**

- Default: stream. Each rg match is parsed, formatted, and printed
  immediately. `--limit` caps total matches and terminates rg as
  soon as the cap is hit. Results appear in the order rg produces
  them (effectively file-by-file because rg walks the tree).
- `--sort`: buffer the full rg output, group matches by file, then
  emit. Use this when you want all matches from one file printed
  contiguously even if rg's traversal order would interleave them
  (rare, but possible with parallel directory walking).

`--json`: one record per match, agent-friendly:
```json
{"path": "...", "mirror": "confluence/ENGINEERING", "line": 42,
 "title": "New Hire Setup", "snippet": "...", "page_id": "4521"}
```

**Frontmatter handling**
- By default, search excludes the YAML frontmatter block (matches
  inside frontmatter are filtered out before display).
- `--include-frontmatter` includes it.

## Design Approach

Three small concerns: resolve mirror roots from the config file of
each registered root source (`configs/confluence.yaml`,
`configs/sharepoint.yaml`, plus the global `~/.config/mdd/config.yaml`
for `docs`, and whatever a wrapper registers); shell out to `rg` with
the appropriate flags; format human or JSON output, stripping
frontmatter blocks unless asked otherwise.

The registry is deliberately data-only — a source is a frozen
dataclass, not a loader class — because every source keeps its roots
in the same `<identifier>: {output_dir: …}` shape. That is what makes
a wrapper's registration a one-liner.

The title for the result header is pulled from each matched file's
frontmatter at format time.

## Out of scope

- Building a search index. ripgrep over filesystem is enough.
- Semantic / embedding-based search (deferred per research note R03;
  reconsidered if review-quality demands it).
- Cross-mirror linking. Search returns paths; the user (or agent)
  navigates.
- Authoring queries against a structured frontmatter schema
  (e.g. "find all pages with `status: ARCHIVED`"). Out of scope; a
  later `mdd query` could do that with proper YAML walking.
