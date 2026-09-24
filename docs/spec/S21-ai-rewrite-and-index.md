# 021 - ai rewrite and ai index commands

**Purpose:** Two user-facing AI commands built on the S20 client: `mdd ai rewrite` and `mdd ai index`.

**Status:** Implemented (2026-08-13)

## Introduction

`mdd ai rewrite` proposes tone/clarity rewrites of one or more markdown files. `mdd ai index` generates or refreshes a directory `INDEX.md` listing every page with a one-sentence summary.

Bundled in one spec because they share infrastructure (caching,
output handling, frontmatter awareness) and are similarly small.

Originates from research note R03.

## Subcommands

```
mdd ai rewrite <path>... [--style <prompt-file>] [--apply] [--model MODEL]
mdd ai index <dir>       [--depth 1|all] [--apply] [--model MODEL]
```

## `mdd ai rewrite`

**Behaviour**
- For each input file, send the body (frontmatter excluded) plus a
  tone-of-voice system prompt to the model (default:
  `ai.models.default` from [S20](S20-litellm-ai-client.md)).
- Default output: a `<file>.rewrite.md` sibling alongside the
  source (e.g. `notes.md` → `notes.md.rewrite.md`; the full
  source filename is preserved so multi-dot names like
  `RFC.draft.md` round-trip to `RFC.draft.md.rewrite.md` without
  losing information). The user reviews with `git diff` or in an
  editor. **No source file is mutated without `--apply`** — the
  candidate-sibling pattern is the primary safety mechanism.
- `--apply` overwrites in place (atomic `*.tmp → rename`). The
  prior file content is preserved in git history; no separate
  backup. A path that is a symlink is refused with an error before
  it is read; a symlink at the `*.tmp` sibling fails the write.

**Tone-of-voice prompt**

The rewrite system prompt has two blocks composed at call time:

- **Tone block** — bundled at `src/mdd/ai/prompts/tone-of-voice.md`.
  Encodes a concise house voice (clear, professional, low-jargon).
  `--style <file>` overrides this block per run; the file is plain
  markdown used as the tone half of the system prompt.
- **Constraints block** — bundled at
  `src/mdd/ai/prompts/rewrite-constraints.md`. Carries the
  load-bearing rules (don't alter substance, return only the
  rewritten body) plus an explicit placeholder-preservation
  section: what the `__MDD_PROTECTED_<n>__` tokens are, that they
  must be reproduced verbatim, and that they must not be
  reformatted, renumbered, translated or wrapped in backticks.
  **Never overridable.** `--style` swaps only the tone block; the
  constraints block is always appended after the user's tone so the
  placeholder-preservation rule survives, regardless of how
  aggressive the custom style is.

Both digests participate in the cache key (body hash + tone digest
+ constraints digest + model id + mdd version per [S20](
S20-litellm-ai-client.md)). Editing either bundled prompt changes
its digest and so invalidates every cached rewrite — intended, but
worth knowing before touching a prompt file, because the next run
re-bills every page.

**Pass-through rules** (the AI is allowed to rewrite *body prose
only*)
- Frontmatter — passed through unchanged. The model never sees it
  and may not add any: when the source has no frontmatter and the
  model's reply opens with a `---` block, the rewrite is rejected
  like any other unusable output (dumped to `<file>.rewrite.fail`,
  nothing written to the source or the `.rewrite.md` sibling). The
  managed-elsewhere check under `--apply` runs on the text that
  would be written, not on the original.
- Tables, code blocks, fenced `{=confluence}` blocks, fenced
  `{=html}` blocks — passed through unchanged.
- Image references and links — preserved; the model is instructed
  not to reword link text in ways that break the document's
  structure.
- The Confluence export header ([S09](S09-confluence-command.md)) — passed through
  unchanged.
- The MDD footer ([S09](S09-confluence-command.md)) — passed through unchanged.

The pass-through is **enforced by extraction-and-restitch**, not
by trusting the model. Protected regions are replaced with
placeholder tokens before the model call and substituted back
afterwards. If a placeholder is missing from the response, fail
loudly (model hallucinated away a protected region; output is
unsafe).

**Nothing to rewrite → `skipped`**

A page whose body, once protected regions are extracted, contains
nothing but headings, standalone macro calls (`{{...}}` on a line
of its own) and placeholder tokens has no prose a tone rewrite
could improve. Such a page is reported as `skipped` and **no API
call is made**. This is both a cost saving and a risk reduction:
the only thing a model could do to a stub page is damage it.

**Output-token budget**

Every rewrite call sends an explicit `max_tokens` of 16384, flat —
not scaled from the input length.

- Flat, because `max_tokens` is a *ceiling*, not a spend. Billing
  follows the tokens actually emitted, so asking for headroom that
  goes unused costs nothing, while asking for too little truncates
  the answer.
- Left unset entirely, the gateway applies its own default (4096
  for the Anthropic models behind LiteLLM), which silently
  truncates any page whose rewrite runs longer.
- Not higher than 16384, because the Anthropic API rejects a
  non-streaming request whose `max_tokens` is above roughly 21k.
  Raising the ceiling further needs streaming support in the
  client, which is out of scope for [S20](S20-litellm-ai-client.md)
  and not implemented. Long pages are handled by chunking instead.

**Chunking long bodies**

A body whose model input exceeds a target size of 8000 characters
is split and rewritten chunk by chunk.

- Protected regions are extracted from the **whole body first**,
  before any splitting. Placeholder numbering therefore stays
  global, and no chunk boundary can land inside a table or a fenced
  block — by the time splitting happens, those are single opaque
  tokens.
- Split points are chosen in preference order: `##` heading
  boundaries, then `###` heading boundaries, then blank-line
  paragraph boundaries, then hard line boundaries. The first level
  that produces chunks under the target wins.
- The concatenation of the chunks is byte-identical to the
  un-chunked input. Splitting never adds, drops or normalises
  whitespace.
- Chunks are rewritten **serially**, each as its own `chat()` call
  with its own cache key, so a re-run after a partial failure
  re-uses the chunks that already succeeded.
- If any chunk comes back truncated, or the joined output has lost
  a placeholder, **the whole file is refused**. A file half in the
  new tone and half in the old is worse than a clear failure that
  can be retried.

Trade-off, stated plainly: each chunk is rewritten without sight of
the rest of the page, so the model cannot smooth out repetition
across section boundaries or adjust a later section to a change it
made earlier. The gain is that long pages complete at all, and
complete reliably. Reliability wins.

**Truncation refusal**

A completion whose `finish_reason` indicates truncation (see
[S20](S20-litellm-ai-client.md)) is refused, not stitched. The
rewrite of that file fails with an actionable error and nothing is
written to the source or the sibling.

Previously the truncated text was stitched and written to disk, so
a long page could silently lose most of its content — the
protected-region check passes happily when the model simply stopped
before reaching the interesting part. [S20](S20-litellm-ai-client.md)
additionally keeps truncated completions out of the cache, so a
retry actually retries.

**Failure dumps**

Rejected model output is not discarded; it is written to
`<file>.rewrite.fail` for inspection.

- The suffix is deliberately **not** `.md`, so a
  `find . -name '*.md'` sweep does not pick up a dump and feed it
  back through the rewriter.
- The dump is the raw model output verbatim, prefixed by an
  HTML-comment header carrying: the source path, the rejection
  reason, prompt and completion token counts, the finish reason,
  whether the response came from cache, the input and output
  character counts, and a per-protected-region report saying which
  placeholders survived and which did not. Placeholder-like tokens
  the model emitted that match no region are listed too, so a
  mangled token is distinguishable from a deleted one.
- Because the header is a comment, the body below it still diffs
  against the source.
- Dump paths are listed again in the end-of-run summary.

**Shrink warning**

A rewrite whose body keeps under 90% of the source body's length
logs a warning naming both lengths and the percentage change. The
output is still written — this is advisory, not a refusal.

It exists because unprotected prose has no placeholder to lose: a
model that quietly drops half a page's paragraphs still stitches
cleanly and still reports `stop`. A size comparison is the only
cheap signal that something went missing.

**Cache behaviour**
- Cache key includes: file body hash, tone digest, constraints
  digest, model id, mdd version (per [S20](S20-litellm-ai-client.md)
  default).
- Re-running on an unchanged file with the same tone is a no-op
  (cache hit, no API call).

**Run summary**
- Per file, one of four statuses:
  - `rewritten` — a live model call produced usable output.
  - `cached` — the output came from the [S20](S20-litellm-ai-client.md)
    cache; no API call.
  - `skipped` — nothing but headings, macros and protected blocks;
    no API call attempted.
  - `error` — the file was refused (truncation, lost placeholder,
    managed-elsewhere page under `--apply`, or an I/O failure).
- End of run: the tally of all four statuses, the paths of any
  failure dumps, then total tokens and estimated cost.

**Output**
- Files are processed serially, and the chunks of a single file
  likewise. The `ai.concurrency` bound from
  [S20](S20-litellm-ai-client.md) still caps in-flight calls, but
  `rewrite` does not try to fill it: progress is easier to read and
  a rate-limited run degrades more gracefully.
- Errors per file are reported and processing continues; exit
  non-zero if any file failed.

## `mdd ai index`

**Behaviour**
- Walks `<dir>` recursively, finding `.md` files (ignoring already-
  generated `INDEX.md` files at any level). Symlinked `.md` entries
  are skipped: they are never read, summarised or written back.
- For each `.md`: compute body hash; if frontmatter has a matching
  `mdd.ai.summary_input_hash`, reuse the cached summary (free).
  Else, summarise via the model (default: `ai.models.summarise`)
  and save the result back into the file's frontmatter.
- Generate or refresh `<dir>/INDEX.md`:
  ```markdown
  # Index

  *Auto-generated by `mdd ai index`. Re-run to refresh.*

  ## Architecture

  - **[Platform Topology](Architecture/Platform-Topology.md)** —
    overview of the platform's main runtime components and how
    they connect.
  - **[Deployment Pipeline](Architecture/Deployment-Pipeline.md)** —
    end-to-end flow from PR merge to production rollout.

  ## Process

  - **[Onboarding](Process/Onboarding.md)** — checklist for new joiners.
  ```
- `--depth 1` lists files only (flat list, no grouping). `--depth
  all` lets the model cluster pages into topic groups (one extra
  LLM call); the cluster names become H2 headings.
- `--apply` writes `INDEX.md` (default) and writes summaries back
  into source-file frontmatter. Without `--apply`, prints the
  proposed `INDEX.md` to stdout. Same safety pattern as `rewrite`:
  nothing on disk changes without explicit opt-in.
- The generated `INDEX.md` carries its own frontmatter:
  ```yaml
  ---
  ai_generated: true
  generated_by: mdd ai index
  generated_at: 2026-05-08T10:30:00Z
  ---
  ```

**Per-file summary frontmatter**
- Stored on the source `.md`:
  ```yaml
  mdd:
    ai:
      summary: "Overview of the platform's main runtime components and how they connect."
      summary_input_hash: 9f86d081...
      summary_model: claude-haiku-4-5
      summary_at: 2026-05-08T10:30:00Z
  ```
- The `summary_input_hash` is what makes reruns a no-op.

**Topic clustering** (only at `--depth all`)
- After per-file summaries, send the list (file + one-line summary)
  to the default model with a clustering prompt.
- Model returns `[{topic_title, file_paths[]}, ...]`. Entries that
  are not an object with a string `topic_title` and a list of string
  `file_paths` are dropped with a warning.
- Render each topic as an H2 with the listed files under it. Only
  paths from the indexed set are rendered; any other path the model
  names is skipped with a warning. Files no cluster claims land in a
  trailing `## Other` section.
- Summaries and topic titles are model text and are rendered as
  literal text: whitespace runs collapse to one line and the
  characters that would open a link, image, fence, raw HTML, macro,
  heading, emphasis or strikethrough are backslash-escaped, as are
  parentheses, so a model-written `](confluence-attachment:...)` is
  never picked up by the attachment upload scan when the index is
  later published.

## Design Approach

**Default prompts** are bundled in `templates/prompts/` (one each
for rewrite, summarise, cluster). They are plain markdown so users
can read and override them.

**Cache keys** (all on top of [S20](S20-litellm-ai-client.md)'s base key):
- Rewrite: `(body_hash, style_hash, constraints_hash, model_id,
  mdd_version, "rewrite")`. A chunked rewrite keys each chunk
  separately, since the chunk text is the user message.
- Index per-file summary: `(body_hash, model_id, mdd_version, "summary")`
- Index clustering: `(joined_summaries_hash, model_id, mdd_version, "cluster")`

**Safety design** — the `--apply` vs candidate-sibling distinction
is deliberate. Rewrites are *suggestions*; the default behaviour
must never silently mutate the user's source. `INDEX.md` follows
the same rule: stdout by default, file write only with `--apply`.

## Out of scope

- Multi-file rewrite that reasons about cross-file consistency
  (that's [S22](S22-ai-review-command.md)'s `review` territory).
- Translation. The default style is monolingual.
- Generating frontmatter fields beyond `mdd.ai.*`.
- Customising the index header / styling.
