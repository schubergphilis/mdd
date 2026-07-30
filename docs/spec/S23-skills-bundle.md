# 023 - Agent skills bundle and skills command

**Purpose:** Bundle Claude Code skills with `mdd` so agents can discover when and how to drive `mdd` reliably.

**Status:** Implemented (2026-07-30)

## Introduction

`mdd skills install` deploys the bundled skills into `~/.claude/skills/`.

Originates from research note R03.

Amended 2026-07-30 with the **skill-root registration seam**
(`register_skill_root`), so a distribution that composes the CLI ships
skill bundles of its own rather than only a subset of `mdd`'s.

## Requirements

**Skill roots**
- The bundle is not one directory but an **ordered list of skill
  roots**. `src/mdd/skills/` (resolved via `importlib.resources`) is
  pre-registered as the first entry.
- `mdd.commands.register_skill_root(path)` appends a root. A composing
  distribution calls it from its entry point, before
  `build_dispatcher()`, exactly as it calls
  `mdd.mirror.register_backend` for a mirror backend.
- `mdd.commands.skill_roots()` returns the registered roots in
  registration order.
- A directory under a root counts as a skill when it contains
  `SKILL.md`. A root that does not exist is skipped, not an error — a
  wrapper may ship no skills of its own.
- **Discovery is lazy.** The name set is computed on first use and
  cached; `register_skill_root` invalidates the cache. It must not be
  computed at import time, or a registration performed after import is
  invisible.
- **Collision rule: last-registered wins.** Because the core root is
  registered first, a wrapper deliberately overrides a core skill by
  reusing its directory name. No error, no warning — an override is a
  supported use, not a mistake to report.
- `list`, `install`, and `uninstall` all resolve a name through the same
  index, so `install` can never deploy a different copy than `list`
  displayed.

**`mdd skills list`**
- Prints the numbered skill-root legend first, so the collision rule and
  the roots in play are on screen.
- Lists each bundled skill with status:
  - **installed** if a corresponding `~/.claude/skills/<name>` exists
    pointing at our bundled file.
  - **available** otherwise.
- Tags every skill with the `[N]` marker of the root it resolved to.
  Since a collision is silent by design, this is what makes an
  accidental shadow diagnosable.
- A name shadowed across roots appears **once**, tagged with the
  winning root.
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

**A registration seam, not a plugin scan.** Roots are registered
explicitly, matching the two seams the composition layer already has:
`register_backend` for mirror backends and
`build_dispatcher(extra_commands=...)` for subcommands. There is no
entry-point group and no filesystem search for sibling distributions —
a composing distribution already runs code at startup to build the
dispatcher, so it can register a root in the same breath, and the set
of roots stays inspectable rather than ambient.

`register_skill_root` deliberately does *not* raise on a duplicate name,
which is where it diverges from `register_backend`. A backend name
collision is always a bug (two implementations answering to one key);
a skill name collision is how a wrapper overrides a core skill with a
version tuned for its own tenants, so it must succeed. The cost of that
choice is a silent shadow, which `list` pays back by printing the
owning root for every skill.

**Lazy discovery.** The name set was originally computed at import
time. That is incompatible with registration: a wrapper's entry point
imports `mdd.cli` (and with it the `skills` module) before it can call
`register_skill_root`, so an import-time snapshot could never contain
the wrapper's skills. Discovery is therefore performed on first use and
memoised, and `register_skill_root` clears the memo.

**Composition-seam surface.** The seam a composing distribution
consumes is, in full: `build_dispatcher(default_backend=,
extra_commands=, version=)` and `run()` from `mdd.cli`,
`register_backend` from `mdd.mirror`, and `register_skill_root` from
`mdd.commands`. That surface is specified by the open-source-split spec
(S44), which lives in the wrapper's own repository; this spec owns only
the skills-bundle half of it.

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

`list` output, with a wrapper distribution's root registered second and
`mdd-search-skill` overridden by it:

```
Bundled skills (target: /Users/me/.claude/skills):

Skill roots (last registered wins on a name collision):
  [1] /opt/venv/lib/python3.14/site-packages/mdd/skills
  [2] /opt/venv/lib/python3.14/site-packages/my_dist/skills

  mdd-confluence-skill              installed     [1]
  mdd-lucid-skill                   available     [2]
  mdd-search-skill                  installed     [2]
```

## Registering a root from a composing distribution

```python
from importlib.resources import files

from mdd.cli import build_dispatcher, run
from mdd.commands import register_skill_root


def main() -> int:
    register_skill_root(files("my_dist") / "skills")
    return run(build_dispatcher(extra_commands=[...]))
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
  identify a Lucid mirror; rate-limit considerations. Ships in the
  private SBP wrapper's own skill root, which it adds with
  `register_skill_root`, not in this distribution; it is listed here
  because the bundle format is the same and a wrapper's skills install
  through the same command.
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
- Auto-discovery of skill roots via packaging entry points or a
  filesystem scan. Registration is explicit (see Design Approach).
- Unregistering a root, or per-root ordering control beyond
  registration order. A composing entry point controls both by the
  order in which it calls `register_skill_root`.
- Reporting a shadowed skill as a warning or an error. Overriding is
  supported; `list` printing the owning root is the whole diagnostic.
