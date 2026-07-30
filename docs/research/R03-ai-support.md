# 003 - AI agent support

**Status:** Research notes. Not an implementation spec.

**Problem brief.** We have, or will have, a substantial corpus of
markdown mirrors (Confluence spaces and SharePoint sites) sitting in
GitLab repos. The user wants to turn this into an
agent-friendly knowledge base with a few concrete capabilities:

1. **Agent skills that wrap the `mdd` CLI** so Claude Code (and other
   skill-aware agents) can drive `mdd` reliably.
2. **Markdown corpus as external memory for agents** — searchable,
   probably via ripgrep, with a thin `mdd search` wrapper.
3. **AI-proposed rewrites** of existing content (language polish,
   tone-of-voice).
4. **Duplication and inconsistency detection** across spaces — find
   pages that overlap or contradict.
5. **Stale-content detection** — old pages that have been
   superseded; propose cleanups, redirects, or merges.
6. **AI-generated indexes and summaries** so each mirror has a
   maintained `INDEX.md` / `README.md`.

The model gateway is a **self-hosted LiteLLM proxy** (written as
`https://litellm.example.com/` in the examples below). Users get a
personal API token from the gateway's own token portal and store it in
1Password. The proxy exposes
an OpenAI-compatible API surface with a curated set of upstream
models (OpenAI, Anthropic, etc.) configured by the gateway operator.
Audit, cost tracking, and per-user budgets live on the proxy.

This document maps the surface area, identifies the shared
infrastructure these features need, and proposes a CLI shape, a
skills layout, and a phased rollout. It deliberately stops short of
prescribing exact subcommand flags, prompt wording, or embedding
storage layouts — those belong in follow-up implementation specs.

## The LiteLLM proxy: what it is and how we integrate

LiteLLM proxy is an OpenAI-API-compatible reverse proxy that sits in
front of multiple model providers and exposes them under one unified
API, with virtual keys, audit, and budgets. Practically, integration
boils down to:

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://litellm.example.com/v1",
    api_key=resolve_secret("op://Employee/litellm-pat/token"),
)
client.chat.completions.create(model="claude-sonnet-4-5", messages=[...])
```

That's it — the OpenAI Python SDK works as-is. We add no extra
dependency beyond `openai>=1.50` (or whatever satisfies the
LiteLLM-supported features we use). Embeddings, when we get there,
use the same client (`client.embeddings.create(model="...", input=...)`).

### Auth

- Token comes from the gateway's token portal. User stores it in 1Password under
  e.g. `Employee/litellm-pat` with field `token`.
- Config references it as `ai.api_token: op://Employee/litellm-pat/token`.
- Resolution goes through `mdd.utils.secrets.resolve_secret()` (spec
  007), exactly the same pattern as Confluence and GitLab tokens. No
  `op read` from agents (per CLAUDE.md and the existing memory).

### Model selection

The set of models exposed by the gateway is whatever the gateway
admin has configured. We can't pin a specific model in `mdd` and hope
it stays available; instead:

- Config names a **default model per task class**:
  - `ai.models.default` — general-purpose (rewrites, review)
  - `ai.models.summarise` — cheap/fast (summaries, indexes)
  - `ai.models.embed` — embedding model (if/when used)
- `mdd ai` subcommands accept `--model <id>` to override per call.
- On startup, the client lists `/v1/models` and surfaces an actionable
  error if a configured model isn't available
  (`"Model 'claude-sonnet-4-5' not in <gateway>/v1/models;
  available: ..."`). This catches the "the gateway changed its
  model list" failure mode early.

### Concurrency and rate

LiteLLM proxy passes upstream rate limits through (and may add its
own per-key budget on top). Practical considerations:

- Honour `Retry-After` on 429 (same posture recommended in research
  doc 002 for Confluence).
- Cap concurrent in-flight requests at a low default (e.g. 4) to be a
  good citizen; expose `--concurrency`.
- Cache aggressively by content hash (see "Caching" below).

### Cost

- Each call costs real money on a real budget. Default to the
  cheapest model that produces acceptable quality for each task
  class. Use bigger models only when invoked explicitly or for
  high-stakes operations (rewrites, contradiction-checking).
- Print a per-run summary that includes token counts and (if the
  proxy returns it) cost in USD/EUR.

## Proposed CLI surface

Three new top-level groups, plus one orthogonal one:

```
mdd search          # ripgrep wrapper — no AI, no token needed
mdd ai rewrite      # propose tone/clarity rewrites
mdd ai index        # generate / refresh INDEX.md
mdd ai review       # cross-page checks: dup, inconsistency, stale
mdd ai chat         # one-shot Q&A with the corpus as context (optional)
mdd skills install  # install agent skills into ~/.claude/skills/
mdd skills list
```

Splitting `search` from `ai`:

- **`mdd search`** is fundamental, free, and has no token requirement.
  It works against any local clone of any mirror. Belongs at the top
  level so it's discoverable.
- **`mdd ai *`** are the LiteLLM-using commands. They require a
  configured token; failing without one is an actionable error
  pointing at `op://...` setup (spec 007).

`mdd ai chat` is an open question — discussed under "What to defer".

### `mdd search`

A thin ripgrep wrapper that knows where mirrors live:

```
mdd search "kubernetes upgrade" [--space SPACE] [--site SITE]
                                [--include-frontmatter]
                                [--json]
```

Behaviour:

- Resolves search roots from config: each `confluence.spaces.<key>.
  output_dir`, each `sharepoint.sites.<name>.output_dir`, plus
  `--include` / `--exclude` overrides. By default, include everything
  configured locally.
- Shells out to `rg` with `--type md`, smart-case, and a result
  limit. Output formats:
  - **Default**: human-readable, grouped by file with the page title
    pulled from frontmatter.
  - **`--json`**: one record per match, agent-friendly:
    `{path, line, title, space, snippet}`.
- Respects the spec 007 blacklist symmetrically? Local search is
  unrestricted by default — the user already has the content; the
  blacklist gates *publishing*, not reading. Possibly add
  `--exclude-blacklisted` for paranoid use.

ripgrep is more than fast enough at the scale we expect. We do not need a
search index, and we do not need embeddings, for `mdd search`.

### `mdd ai rewrite`

Propose a tone/clarity rewrite of one or more files:

```
mdd ai rewrite <path>... [--model MODEL] [--apply]
                         [--style ./styles/house.md]
                         [--scope file|section]
```

Behaviour:

- Reads each file, ships content + a system prompt that encodes the
  desired style to the LLM, receives a rewrite.
- Default output: a `.rewrite.md` sibling file. User reviews
  (`git diff`-style or open-in-editor). `--apply` overwrites in
  place (still leaves a backup; sync via spec 002 already covers
  the "atomic with backup" pattern).
- `--scope section` chunks per H2 to keep prompts small and outputs
  reviewable. Default is the whole file.
- Tone-of-voice prompt lives in a versioned file:
  `templates/prompts/tone-of-voice.md` bundled with `mdd`, with a
  `--style` override for per-team / per-space variants. The prompt
  is committed material; the AI is just a stylistic transformer.
- Caches by SHA-256 of (input file + style prompt + model name + mdd
  version). Re-running on unchanged input is a free no-op.
- Never edits frontmatter — the AI is allowed to rewrite *body
  prose only*. Tables, code blocks, fenced confluence blocks, image
  references, and the export header are passed through unchanged.

### `mdd ai index`

Generate or refresh an `INDEX.md` for a directory:

```
mdd ai index <dir> [--model MODEL] [--depth 1|all] [--apply]
```

Behaviour:

- Walks the directory; for each `.md`, extracts a one-sentence
  summary (LLM call, with caching).
- Renders an `INDEX.md` that lists each page with title and summary,
  optionally grouped by topic (LLM-clustered) at `--depth all`.
- Refreshes incrementally — only re-summarises files whose content
  hash changed. Stores `mdd.ai.summary` and
  `mdd.ai.summary_input_hash` in **the source file's frontmatter**
  (or in the index's metadata block; either works — see open
  question below).
- The generated `INDEX.md` is itself a markdown file in the mirror;
  on the next sync (Confluence or SharePoint), it round-trips like
  any other page. For Confluence, the generated index can become a
  page; for SharePoint, it lives as a file in the directory.

The "indexes are pages too" property is nice — it means the AI's
output is reviewable, editable, and version-controlled by the same
machinery as everything else.

### `mdd ai review`

Cross-page review checks. Three sub-modes, runnable individually or
all-at-once:

```
mdd ai review --duplicates [--space SPACE] [--similarity 0.85]
mdd ai review --inconsistencies [--space SPACE]
mdd ai review --stale [--space SPACE] [--age 365]
mdd ai review --all
```

The output is always a structured Markdown report (`docs/review/
2026-05-08-SPACE.md` by default) with anchored sections, file links,
and proposed actions. The report is itself committable and reviewable
by humans. Re-running produces a fresh report; old reports stay in
git history.

#### Duplicates

Two-tier approach:

1. **Cheap shortlist**: TF-IDF / BM25 over markdown bodies (use
   `rank-bm25` or similar; tiny dependency, no LLM). For each
   document, find the top-K most similar candidates within the
   space. This is fast enough to run on every review.
2. **LLM judge**: send each shortlisted pair to the LLM with a
   strict prompt — *"are these two pages substantially overlapping
   in content? Output JSON: `{overlap: high|medium|low|none,
   summary: ..., suggested_action: ...}`"*. Filter to
   `overlap: high`. Output candidates as report entries.

The shortlist keeps cost bounded — for a 500-page space, we ship
~500 × K (say K=5) = 2500 short LLM calls in the worst case, far
fewer in practice with caching.

Output:

```markdown
## Likely duplicates

- **HIGH**: `Engineering/Onboarding.md` and `Engineering/New Hire Setup.md`
  - Both describe the laptop-provisioning flow with overlapping
    sections (sections 2 and 4).
  - Suggested: keep `New Hire Setup.md` as canonical;
    add a deprecation note + redirect link from `Onboarding.md`,
    or merge sections into the canonical page.
- **MEDIUM**: ...
```

#### Inconsistencies

Same shortlist machinery (find related pages), different LLM prompt:
*"do these pages contradict each other on any factual claim?"* Lower
recall (most page pairs don't contradict), higher signal — surface
contradictions with a quoted snippet from each side.

This is the trickiest of the three. Expect false positives (wording
differences flagged as contradictions). The output is a report for
humans to triage, not an action list.

#### Stale

Heuristic + LLM:

- Heuristic: pages whose `updated_at` is older than `--age` (default
  365 days), and / or whose body contains a date pattern more than
  N years old in a "last reviewed" / "as of" position.
- For each stale candidate: find related pages (BM25 again),
  compare with LLM (*"is this page's content replicated or replaced
  by any of these newer pages? if yes, propose a redirect note."*).
- Output:
  ```markdown
  ## Stale candidates

  - `Tech/Old Deployment Runbook.md` — last updated 2022-03-12
    - Likely superseded by `Platform/Deployment.md` (updated 2026-04-08)
    - Suggested action: archive on Confluence; add redirect note
      pointing at the newer page; keep file in mirror with
      `confluence.status: ARCHIVED` (per spec 014's archive policy).
  ```

The output of `mdd ai review --stale` directly feeds the spec 014
archive flow: the user can take the suggestions and apply them via
Confluence (which sync then mirrors back), or via direct frontmatter
edits + sync push.

### `mdd skills install` / `mdd skills list`

Distribute Claude Code skills bundled with `mdd`:

```
src/mdd/skills/
  mdd-confluence-skill/
    SKILL.md             # how to drive `mdd confluence` from an agent
  mdd-sharepoint-skill/
    SKILL.md
  mdd-search-skill/
    SKILL.md
  mdd-rewrite-skill/
    SKILL.md             # tone-of-voice prompts; how to invoke `mdd ai rewrite`
  mdd-review-skill/
    SKILL.md
```

`mdd skills install` symlinks (or copies) each into
`~/.claude/skills/<name>/`, idempotent. `--force` overwrites prior
installs. `mdd skills list` shows installed vs. available with
status.

The skills themselves are documentation files that an agent reads
to decide *when* to use `mdd` and *how* to chain commands. They
contain:

- A short "trigger when" section so the agent knows the skill is
  relevant.
- A short "skip when" section to prevent overuse.
- Concrete example invocations.
- Pointers to the relevant `mdd <command> --help` for parameter
  details (so we don't have to keep skill markdown perfectly in sync
  with CLI flags).

This deliberately mirrors the layout of skills the user already has
in their environment (`python-knowledge-patch`, `1password`,
`update-config`, etc.) — it's a familiar shape for any
Claude-Code-using colleague.

For non-Claude-Code agents (Cursor, Aider, custom internal agents),
the same `SKILL.md` files double as documentation: any agent can be
prompted to read them.

## Markdown corpus as agent memory

The "external memory" framing matters because it shapes the
recommendation. Two retrieval strategies are common:

- **Lexical** (ripgrep / BM25): cheap, predictable, no embeddings,
  no token cost. Effective when the agent already knows roughly
  what it's looking for.
- **Semantic** (embeddings + ANN search): better recall when the
  query and the answer use different vocabulary; requires an
  embedding pipeline and storage.

Recommendation for v1: **lexical only**. `mdd search` over the
mirrors gives agents enough leverage. Add an embeddings layer in a
later phase if and only if review / dedupe quality warrants it. The
embedding work has nontrivial storage / freshness / cost properties
(see "Embeddings, deferred" below).

### What about retrieval-augmented Q&A?

`mdd ai chat <question>` is an obvious next step:

1. Run `mdd search` with the question.
2. Pass top-K hits + question to the LLM as context.
3. Stream the answer.

This is small in code and useful for the "what does our doc say
about X?" use case. Suggest including it but flagging as
experimental in v1.

## Caching: the load-bearing engineering decision

Every AI feature that rereads content uses the same caching pattern:

- Compute SHA-256 of the **prompt input** = (file content + system
  prompt + model id + mdd version + relevant config).
- Look up the hash in a cache (`.mdd-ai-cache/<hash>.json`).
- If hit, return the cached response. If miss, call the model,
  store, return.

Cache location options:

1. **Per-mirror, gitignored**: `.mdd-ai-cache/` at the root of each
   mirror clone. Simple, mirror-local. Each user has their own
   cache.
2. **User-global**: `~/.cache/mdd/ai/`. Shared across mirrors;
   wins on first-touch when a similar input was hashed already.
   Slight risk of cross-tenant cache pollution (different mirrors
   might use the same prompt template; that's fine, identical input
   = identical output).
3. **Mirror-tracked, committed to git**: surface for sharing
   between users (you ran `mdd ai rewrite`; I get the cached output
   for free). Privacy / ergonomic risks: the cache may capture
   sensitive snippets in keys / values; commits get noisy.

Recommendation: **option 2** (user-global cache) with TTL of e.g.
30 days. Simple, fast, no commit noise. Make the cache directory a
config knob (`ai.cache_dir`) so tooling can override.

Caching matters because LLM calls are expensive *and* slow. A
warm-cache run of `mdd ai index` on a 200-page space should take
seconds (just hashing); a cold run takes minutes and tokens.

## Privacy, blacklist, and what we send to the AI

The spec 007 blacklist gates **publishing to a remote**: it prevents
confidential content from leaving the organisation's boundary. The
LiteLLM gateway is self-hosted — internal by construction. Three
policy options:

1. **Send blacklisted content to the internal AI freely.** It
   doesn't leave the organisation; the gateway is internal
   infrastructure.
   Aggressive but defensible if the gateway is genuinely confined.
2. **Apply the same blacklist to AI calls.** Skip blacklisted
   spaces / sites from `mdd ai *` runs. Safest; loses the AI's
   ability to help with the most sensitive content.
3. **Per-space classification flag in config.** `confidential:
   true` means "do not send to internal AI either". Gives the
   user fine-grained control.

Recommendation: **option 3** by default, with the flag *defaulting
to whatever the blacklist says* (i.e. blacklisted = don't send to
AI), so users get the safe default for free without any extra
config work, and can opt in to AI-on-confidential-content space-by-
space when their data-handling agreement permits it. Encode this in
spec 007 by adding an `ai_eligible: bool` field per blacklist entry
(default `false` for blacklisted, `true` otherwise).

This is a policy choice that should be confirmed against the
organisation's data-protection guidance — flagged as an open
question.

## Embeddings, deferred

For semantic similarity (better duplicate / inconsistency / stale
detection), embeddings are the standard tool. The shape:

- Use the embedding model exposed via LiteLLM (typical:
  `text-embedding-3-large` or similar).
- Chunk pages into ~500-token sections (paragraph-or-H2-aware).
- Embed each chunk; store as a vector.
- For similarity queries: ANN search via FAISS / sqlite-vss / a
  flat numpy table (small enough at the scale we expect).

Storage: a sister directory `.mdd-embeddings/` that is **not** part
of the main mirror — vectors are large, change with embedding
model, and aren't useful as content. Could be:

- Local-only (gitignored), recomputed on each machine.
- A separate GitLab repo per mirror (`mdd/embeddings/<space>`).
- A central index (single `mdd-embeddings` repo with all spaces).

Each option has trade-offs. **Defer this entirely** until the
non-embedding path proves insufficient. BM25 + LLM judge gets us a
long way; embeddings are the optimization, not the foundation.

## Skills bundle: what each skill contains

Sketch of skill content (the actual prose to be drafted at impl
time):

- **`mdd-confluence-skill`**: triggers on tasks that mention
  Confluence, page sync, exporting / publishing pages. Tells the
  agent to use `mdd confluence sync` for full reconciliation,
  `mdd confluence update-page` for single-page edits, and to
  *never* call the Confluence REST API directly (auth / rate-limit
  reasons covered by spec 009).
- **`mdd-sharepoint-skill`**: same shape, for SharePoint sync.
- **`mdd-search-skill`**: when the user asks for information
  retrieval against the organisation's knowledge base, run `mdd search
  --json <query>` first; rank the top hits; only invoke `mdd ai
  chat` if lexical search is insufficient. Saves tokens and time.
- **`mdd-rewrite-skill`**: tone-of-voice instructions; explicit
  rules ("don't change technical claims, only prose"; "preserve
  frontmatter, fenced blocks, links"); how to present a rewrite to
  the user (diff first, ask before applying).
- **`mdd-review-skill`**: when, why, and how to run
  `mdd ai review` — usually as a separate operation, not inside
  another flow. Output is reviewed by a human; the agent
  summarises but does not apply suggestions automatically.

Skills are short (typically <100 lines each). They live alongside
the codebase so the CLI surface and the skill instructions stay in
lockstep — same logic as keeping `--help` and the docs aligned.

## Cost / token budget

Some napkin math at plausible sizes:

- 500-page space, average page ~1000 tokens.
- Indexing (one summary per page, cheap model): 500 × ~500 input
  + 100 output tokens ≈ 250k input / 50k output → cents to a few
  dollars depending on model. Cached after first run; thereafter
  ~free.
- Rewrites: per-file, on demand, never bulk-default. Negligible
  aggregate cost.
- Review (BM25 + LLM judge on shortlists): 500 × 5 = 2500 LLM
  calls at ~1500 input / 200 output each ≈ ~3M input / 500k
  output. With a cheap model (Haiku-class), low single-digit
  dollars per full review. Not free; not painful.
- Embeddings (if/when added): one-time per page-version. Cheaper
  per call than chat, but bulk; cents to dollars per space.

Caching is what keeps these small in steady state. The first run is
the expensive one.

## What goes in the implementation specs (not here)

Likely a small set of related specs once the user wants to
proceed:

1. **Spec X — `mdd search`**: ripgrep wrapper, JSON output, search
   roots from config. No LLM. Smallest, ships first.
2. **Spec X+1 — LiteLLM client + `mdd ai` scaffolding**: shared
   `mdd.ai.client` module (auth, retry, concurrency, caching),
   model-class config keys, base error messages. No user-facing
   subcommands yet — just the infrastructure.
3. **Spec X+2 — `mdd ai rewrite` and `mdd ai index`**: the simplest
   user-facing AI commands that exercise the infra above.
4. **Spec X+3 — `mdd ai review`**: BM25 shortlist, LLM judge,
   output report shape. Builds on the infra.
5. **Spec X+4 — Skills bundle and `mdd skills install`**: package
   skills with the codebase, install into `~/.claude/skills/`.
6. **Spec X+5 (deferred, maybe never) — Embeddings + ANN**: only
   if review quality demands it.

Each spec is small (~150-300 lines) and stops at one
testable surface. The phasing also lets us validate the LiteLLM
plumbing on a low-stakes command (rewrite) before betting bigger
features (review) on it.

## Open questions for the implementation specs

1. **Blacklist policy for AI calls.** Default to the spec 007
   blacklist also gating AI calls? Confirm against the organisation's
   data-protection guidance before committing. (See "Privacy" above.)
2. **Where to store per-page AI metadata.** In the source file's
   frontmatter (`mdd.ai.summary`, `mdd.ai.summary_input_hash`,
   `mdd.ai.last_rewritten_at`) or in a separate index? Frontmatter
   is consistent with the rest of the mdd model; risk is bloating
   frontmatter on pages that get many AI passes. Probably
   acceptable; revisit if a page gets >10 AI fields.
3. **Tone-of-voice prompt: bundled vs. per-team.** Ship a default
   `templates/prompts/tone-of-voice.md` and accept a `--style`
   override? (Yes, suggested.) Where do per-team styles live —
   alongside the mirror, or in a central config repo?
4. **What happens to AI-generated `INDEX.md` files on Confluence
   sync?** They become Confluence pages. Probably fine; tag them
   with a `confluence.ai_generated: true` flag so we can
   distinguish them from human-authored pages and (optionally)
   regenerate-and-republish on schedule.
5. **`mdd ai chat` vs. shipping a small TUI.** A streaming
   single-shot Q&A is cheap to build. A multi-turn TUI is more
   work and may duplicate what users get from a normal Claude Code
   session pointed at the mirror. Suggest single-shot for v1.
6. **Skills auto-install on first run?** When a user runs `mdd`
   for the first time, prompt to install skills? Or always
   explicit (`mdd skills install`)? Suggest explicit — installing
   into `~/.claude/skills/` without consent is surprising even if
   convenient.
7. **Cache invalidation on `mdd` upgrade.** Including `mdd
   __version__` in the cache-key namespace makes upgrades flush
   the cache automatically. Cleaner than a manual `mdd ai
   cache-clear`. Suggest yes.
8. **Multi-user budget visibility.** Should `mdd ai *` print the
   user's remaining LiteLLM budget after each run? The proxy
   exposes this; surfacing it costs nothing. Probably yes.

## Useful references

- LiteLLM project (open-source proxy):
  <https://github.com/BerriAI/litellm>
- LiteLLM proxy docs (auth, virtual keys, OpenAI-compatible API):
  <https://docs.litellm.ai/docs/proxy/quick_start>
- OpenAI Python SDK (used unchanged against the proxy):
  <https://github.com/openai/openai-python>
- Claude Code skills format: see existing `~/.claude/skills/`
  examples (`python-knowledge-patch`, `1password`, etc.) for the
  conventions we should follow.
- BM25 in Python (for the cheap shortlist tier of `mdd ai review`):
  <https://github.com/dorianbrown/rank_bm25>
