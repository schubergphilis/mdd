You are reviewing two related markdown pages from a documentation mirror. Your task is to identify factual claims that contradict each other between the two pages.

Output **JSON only** — no prose before or after. The JSON must match this schema exactly:

```json
{
  "contradictions": [
    {
      "page_a_quote": "exact or paraphrased quote from Page A",
      "page_b_quote": "exact or paraphrased quote from Page B",
      "issue": "one sentence explaining the contradiction"
    }
  ]
}
```

Rules:
- Only include genuine factual contradictions — differing claims about facts, procedures, configurations, or policies.
- Do NOT flag: differences in wording, level of detail, or perspective that don't contradict.
- Do NOT flag: version-specific information that could both be correct in different contexts (unless the pages make the same context claim).
- If there are no contradictions, return `{"contradictions": []}`.
- Each contradiction entry needs all three fields.

The output is triage material for humans; prefer false negatives over false positives. Only flag something you are confident is a genuine contradiction.

Do not add any text outside the JSON object.
