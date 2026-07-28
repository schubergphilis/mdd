---
name: mdd-search-skill
description: |
  How to search across mdd mirror repositories using `mdd search`; when to
  prefer it over ad-hoc `find` / `grep` invocations.
---

## When to use

Trigger this skill when the user asks to:

- Find content in Confluence, SharePoint, or Lucid mirrors
- Search for a term or pattern across all mirrored markdown files
- Retrieve structured match data for downstream processing (use `--json`)
- Skip blacklisted / data-protection-gated content in search results

## When NOT to use

- The user wants to build or query a semantic search index; `mdd search` is
  ripgrep-backed full-text search, not vector/embedding search.
- The search is against raw `.docx` / `.pptx` files (not converted mirrors).
- The user wants to search Confluence live via its REST API; `mdd search`
  only searches the local git mirror, not the live Confluence instance.

## Common flows

**Basic full-text search across all mirrors**:
```
mdd search "authentication flow"
```

**Structured output for further processing**:
```
mdd search "authentication flow" --json
```

**Restrict to a specific Confluence space or SharePoint site**:
```
mdd search "authentication flow" --space INFRA
mdd search "authentication flow" --site "IT Documents"
```

**Exclude blacklisted content**:
```
mdd search "password policy" --exclude-blacklisted
```

**Common options**:
- `--json` — one JSON record per match; preferred for agent use
- `--space SPACE` — filter to a Confluence space key (repeatable)
- `--site SITE` — filter to a SharePoint site name (repeatable)
- `--lucid-team TEAM` — filter to a Lucid folder name (repeatable)
- `--type md|qmd|all` — file filter (default: `md`)
- `--limit N` — cap total matches (default: 100)
- `--include-frontmatter` — include matches inside YAML frontmatter
- `--exclude-blacklisted` — skip blacklisted roots per data-protection config
- `--include <path>` — add an extra search root for this run
- `--exclude <path>` — remove a root from the search for this run

Requires: `rg` (ripgrep) on PATH. Install: `brew install ripgrep`

For full parameter detail: `mdd search --help`
