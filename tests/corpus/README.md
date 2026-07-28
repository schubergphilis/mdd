# Test corpora

This directory hosts vendored corpora that drive unit, office, and
integration tests against the converter and sync layers.

| Source | Path | Spec |
|---|---|---|
| Confluence (`markdown.atlassian.net/wiki/spaces/MDD`) | [`confluence/`](confluence/README.md) | [S33](../../docs/spec/S33-ir-roundtrip-testing-and-benchmarks.md) |
| SharePoint (`example.sharepoint.com/sites/MDD`) | [`sharepoint/`](sharepoint/README.md) | [S38](../../docs/spec/S38-sharepoint-test-corpus.md) |

Future sources (e.g. Lucid) follow the same `tests/corpus/<source>/`
convention: one per-source `README.md`, a `configs/<source>.yaml`
points `mdd <source> ...` at the local mirror, and the corpus itself
lives under a name-equivalent layout (so the walker code can run
against the corpus without changes).
