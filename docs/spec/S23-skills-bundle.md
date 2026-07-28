# 023 - Agent skills bundle and skills command

**Purpose:** Bundle Claude Code skills with `mdd` so agents can discover when and how to drive `mdd` reliably.

**Status:** Implemented (2026-05-09)

## Introduction

`mdd skills install` deploys the bundled skills into `~/.claude/skills/`.

Originates from research doc 003.

## Requirements

**`mdd skills list`**
- Lists each bundled skill with status:
  - **installed** if a corresponding `~/.claude/skills/<name>` exists
    pointing at our bundled file.
  - **available** otherwise.
- `--target <dir>` to inspect a non-default skills directory
  (testing).

**`mdd skills install`**
- Default target: `~/.claude/skills/`.
- For each bundled skill, **symlink** the directory under the
  target (preferred over copy: edits to the bundled skill in a
  newer `mdd` install propagate without re-running `install`).
- If a non-symlink directory exists at the target with the same
  name, do not overwrite without `--force`. Print "skipped:
  user-modified" and continue. Symlinks pointing at our bundle are
  always replaceable.
- `--target <dir>` overrides the target directory.
- Idempotent: repeated runs are no-ops on already-installed skills.

**`mdd skills uninstall`**
- Removes only symlinks that point at the bundled directory.
  Other entries are left alone.
- Prints what was removed.

## Design Approach

**Symlinks, not copies.** Installing a newer `mdd` updates the
bundled skill content automatically. User-modified (non-symlink)
entries are never silently overwritten; `--force` is required.

**Target discovery.** Read from `os.environ["CLAUDE_HOME"]` if
set, else default to `~/.claude/skills/`. The `--target` flag
overrides both.

**SKILL.md template** — bundled skills follow this shape:

```markdown
---
name: mdd-confluence-skill
description: |
  How to drive Confluence sync via the mdd CLI; when to prefer
  `mdd confluence sync` over the Confluence REST API.
---

## When to use

Trigger this skill when the user mentions any of:
- syncing / mirroring a Confluence space
- updating a Confluence page from local markdown
- listing pages in a Confluence space

## When NOT to use

- The user wants to call Confluence's REST API directly for a
  one-off operation `mdd` doesn't expose (e.g. comments).

## Common flows

- Full space sync: `mdd confluence sync-space SPACE`
- Single-page update: `mdd confluence update-page <file.md>`

For parameter details: `mdd confluence --help`.
```

## Subcommands

```
mdd skills list
mdd skills install [--force] [--target <dir>]
mdd skills uninstall [--target <dir>]
```

## Bundled skills

Each skill is a directory containing a `SKILL.md` (markdown file
with frontmatter that the Claude Code agent system reads). Skills
shipped in v1:

- **`mdd-confluence-skill`** — when to use `mdd confluence sync` /
  `update page`; when to *not* call the Confluence REST API
  directly. Examples for common flows.
- **`mdd-sharepoint-skill`** — when to use `mdd sharepoint sync`;
  the divergence-handling flow; the office-file-edit-by-non-mdd-
  user case.
- **`mdd-lucid-skill`** — when to use `mdd lucid sync`; how to
  identify a Lucid mirror; rate-limit considerations.
- **`mdd-search-skill`** — preferring `mdd search --json` over
  ad-hoc `find` / `grep` for retrieving content from mirrors.
- **`mdd-rewrite-skill`** — invoking `mdd ai rewrite`; tone-of-
  voice guardrails; presenting diffs to the user.
- **`mdd-review-skill`** — invoking `mdd ai review`; how to
  summarise findings to the user without acting on them.

Each skill is concise (< 100 lines body): trigger conditions,
skip conditions, two or three example invocations, a pointer at
`mdd <command> --help` for parameter detail. Skills do not duplicate
CLI documentation; they teach agents *when* to reach for the tool.

## Out of scope

- Per-skill enable/disable. The Claude Code agent picks up skills
  by directory presence; absence is the only "off" we need.
- Live-updating skills via a remote channel. Skills update with
  `mdd` upgrades.
- Skills for non-Claude-Code agents. Skills are markdown; any
  agent that can be prompted to read them works, but we don't ship
  agent-specific adapters.
