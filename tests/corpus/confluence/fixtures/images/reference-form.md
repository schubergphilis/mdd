---
test_corpus:
  authoring: markdown-first
  shapes:
  - image-reference
  - link-reference-definition
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/1147096/Reference-form+images
  page_id: '1147096'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-13T19:02:57.733Z'
  updated_by: Leo-Bot Simons
  exported_at: '2026-05-13T19:02:58.181721+00:00'
---

# Reference-form images

CommonMark image references use the `![alt][label]` syntax with a
matching `[label]: url "title"` definition elsewhere in the
document. The parser resolves the reference at read time; Confluence
storage represents the resolved image as `<ac:image><ri:url
ri:value="…"/></ac:image>` identical to the inline form. The
reference form exists purely as authoring convenience — the storage
XHTML does not carry the label.

A reference-form image: ![placeholder one][placeholder-one]. And a
second reference: ![placeholder two][p2]. Both labels resolve to
the same kind of external placeholder image and exercise the
parser's reference-resolution path.

[placeholder-one]: https://placehold.co/200x100.png "Placeholder one"
[p2]: https://placehold.co/300x150.png "Second placeholder"

The round-trip from markdown -> storage -> markdown should preserve
the rendered image but is not required to preserve the reference-
definition shape; the writer may emit inline `![alt](url)` form on
the way back because storage carries no labels. Reference-form
preservation is an authoring concern handled at a higher layer.
