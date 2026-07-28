You are reviewing a potentially stale markdown page against one or more newer pages from the same documentation mirror. Determine whether the stale candidate's content has been replicated or superseded by the newer pages.

Output **JSON only** — no prose before or after. The JSON must match this schema exactly:

```json
{
  "replacement": "<relative-path-of-the-best-replacement-page-or-null>",
  "confidence": "high|medium|low",
  "evidence": "one or two sentence explanation of why this page is superseded"
}
```

Or, if the stale candidate is NOT superseded:

```json
null
}
```

Rules:
- `confidence: high` — the newer page clearly covers the same topic with up-to-date information; the stale candidate adds little or nothing.
- `confidence: medium` — significant overlap with a newer page but the stale candidate has some unique content worth preserving.
- `confidence: low` — only superficial topic similarity; the stale candidate is largely independent.
- Only return a non-null result when a specific newer page is a clear replacement. Do not combine multiple newer pages.
- `replacement` must be the relative path exactly as provided in the "Newer candidates" section.
- If no newer page is a clear replacement, return `null` (not an object).

Do not add any text outside the JSON value.
