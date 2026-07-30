# MDD — Confluence round-trip test corpus

Local mirror of the `MDD` space on the project test Confluence instance
at <https://markdown.atlassian.net/wiki/spaces/MDD>. Supports the
round-trip experiments described in research note [R06] (IR for
bidirectional sync) and specified in [R07] (test corpus).

This directory is vendored into the main repo as test data; the
previous standalone `mdd/test-confluence/MDD` GitLab repo is archived.

## Layout

```
configs/
  confluence.yaml         — points mdd at markdown.atlassian.net
fixtures/                 — short, focused pages (one shape per file)
corpus/                   — longer-form realistic pages (hand-authored)
  synth-*.md              — synthetic 'fake company' pages
_snapshots/               — captured ground truth per page_id
  <page_id>/
    storage.xhtml
    export_view.html
    metadata.json
scripts/                  — refresh-corpus helper, validators
```

## Configuration

`configs/confluence.yaml` is committed and points at
`markdown.atlassian.net`. The token is referenced by 1Password URL
(no secret in the file). The default ref is the `lsimons-bot`
identity. When `mdd confluence ...` is invoked from inside this
directory, mdd loads `./configs/confluence.yaml` **before**
`~/.config/mdd/confluence.yaml`, so commands never accidentally hit
a production instance. See
[S07](../../../docs/spec/S07-data-protection.md) for the credentials model.

## Common tasks

Author a new markdown-first fixture:

```bash
cd tests/corpus/confluence
mdd confluence create page fixtures/<category>/<name>.md \
    --space MDD --title "<title>"
```

Push every unpublished markdown-first fixture in one go:

```bash
cd tests/corpus/confluence
python scripts/push-fixtures.py --dry-run    # preview
python scripts/push-fixtures.py              # actually push
```

Refresh all snapshots after Confluence-side edits:

```bash
mise run refresh-corpus
```

## Licensing

Same as the parent `mdd` repository — Apache-2.0. The
corpus is hand-authored or hand-synthesised; no third-party content
is included.

## Related

- [confluence-first-authoring.md](docs/confluence-first-authoring.md)
  — step-by-step walkthrough for fixtures composed in the Confluence
  UI (callouts, page links, layouts, merged-cell tables, niche macros).
- [R06](../../../docs/research/R06-confluence-bidirectional-sync-ir.md) — IR design
- [R07](../../../docs/research/R07-confluence-test-corpus.md) — test corpus
- [S07](../../../docs/spec/S07-data-protection.md) — data protection
- [S09](../../../docs/spec/S09-confluence-command.md) — confluence command
- [S14](../../../docs/spec/S14-confluence-sync.md) — confluence sync
