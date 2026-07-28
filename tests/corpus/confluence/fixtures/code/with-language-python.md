---
test_corpus:
  authoring: markdown-first
  shapes:
  - code-block
  - code-block-language
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/65941/Code+block+with+language+tag+python
  page_id: '65941'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  status: current
  version: 2
  updated_at: '2026-05-11T19:22:45.452Z'
  updated_by: Leo Simons
  exported_at: '2026-05-11T19:22:45.872303+00:00'
---

# Code block with language tag (python)

A fenced code block tagged `python`. Confluence storage represents
the language as `<ac:parameter ac:name="language">python</ac:parameter>`
inside the code macro.

```python
def fibonacci(n: int) -> int:
    """Return the nth Fibonacci number (0-indexed)."""
    if n < 2:
        return n
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b


if __name__ == "__main__":
    for i in range(10):
        print(f"fib({i}) = {fibonacci(i)}")
```

Round-trip must preserve the language tag, the indentation, the
function body, the trailing blank line before `if __name__`, and
the f-string syntax.
