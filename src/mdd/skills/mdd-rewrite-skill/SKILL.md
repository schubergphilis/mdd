---
name: mdd-rewrite-skill
description: |
  How to invoke `mdd ai rewrite` for tone-of-voice improvements; when to use
  it and how to present results to the user without silently overwriting files.
---

## When to use

Trigger this skill when the user asks to:

- Improve clarity or tone of a markdown document
- Rewrite a file for a specific audience or style guide
- Apply a consistent tone-of-voice across a set of pages

## When NOT to use

- The user wants to translate content to a different language.
- The user wants structural changes (reorganise sections, split pages, merge
  pages); those require human judgement, not a rewrite.
- The target file is a managed-elsewhere page (Sphinx, TechDocs); `mdd` will
  still produce a `.rewrite.md` candidate but `--apply` is blocked on those
  pages — do not silently overwrite them.

## Common flows

**Preview rewrite without touching the source** (recommended first step):
```
mdd ai rewrite docs/my-page.md
```
This produces `docs/my-page.md.rewrite.md`. Always show this diff to the user
and ask for approval before applying.

**Apply in place** (only after user approval):
```
mdd ai rewrite --apply docs/my-page.md
```
The write is atomic (temp file + rename). The original is gone — confirm with
the user first.

**Use a custom tone-of-voice prompt**:
```
mdd ai rewrite --style tone-guide.md docs/my-page.md
```

**Rewrite multiple files**:
```
mdd ai rewrite --apply docs/page-a.md docs/page-b.md
```

**Guardrails**:
- Frontmatter, code blocks, tables, and fenced `{=confluence}` / `{=html}`
  blocks are protected and passed through unchanged.
- If the AI model drops a protected region, `mdd` fails loudly — do not retry
  automatically; surface the error to the user.
- Always show `*.rewrite.md` diff to the user before `--apply`.

**Key flags**:
- `--apply` — overwrite in place (ask user first)
- `--style <file>` — custom tone-of-voice prompt
- `--model MODEL` — override the default model

For full parameter detail: `mdd ai rewrite --help`
