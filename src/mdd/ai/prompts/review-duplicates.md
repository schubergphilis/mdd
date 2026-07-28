You are reviewing two markdown pages from a documentation mirror. Your task is to determine how much these pages overlap in content.

Output **JSON only** — no prose before or after. The JSON must match this schema exactly:

```json
{
  "overlap": "high|medium|low|none",
  "summary": "one or two sentence description of the relationship",
  "shared_sections": ["topic or section name", "..."],
  "suggested_action": "concrete one-sentence suggestion for what to do"
}
```

Rules:
- `overlap: high` — the pages cover the same topic in substantially the same way; a reader would get little extra value reading both.
- `overlap: medium` — notable shared sections but each page also has distinct content.
- `overlap: low` — minimal topical overlap; mostly distinct.
- `overlap: none` — no meaningful shared content.
- `shared_sections` — list the shared topic names or section headings (empty array for low/none).
- `suggested_action` — only for high/medium overlaps; suggest merging, deprecating one, or adding cross-references.

Do not add any text outside the JSON object.
