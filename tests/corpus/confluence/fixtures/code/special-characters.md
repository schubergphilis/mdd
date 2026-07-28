---
test_corpus:
  authoring: markdown-first
  shapes:
  - code-block
  - code-block-special-chars
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/98348/Code+block+with+characters+that+need+CDATA
  page_id: '98348'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:22:42.762Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:22:43.180289+00:00'
---

# Code block with characters that need CDATA

The code block body contains `<`, `>`, `&`, and `]]>` sequences
that would corrupt the storage XHTML if naively interpolated as
PCDATA. Storage uses CDATA precisely so these characters pass
through verbatim.

```xml
<root>
  <element attr="value">
    <child>content with &amp; ampersand</child>
  </element>
  <!-- The sequence "]]>" must not terminate the CDATA section
       in storage. The writer needs to split or escape it. -->
</root>
```

```bash
# Shell snippet with pipes and redirects that look XML-ish
ls -la | grep "<TODO>" > /tmp/results 2>&1
echo "done & exiting"
```

Round-trip must preserve every character. If the storage writer
breaks on `]]>` or escapes `&` to `&amp;` inside the CDATA, the
fixture catches it.
