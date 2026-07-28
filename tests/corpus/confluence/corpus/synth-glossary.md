---
test_corpus:
  authoring: markdown-first
  shapes:
  - paragraph
  - heading-h1
  - heading-h2
  - heading-h3
  - list-bullet
  - code-block
  - code-block-language
  - inline-strong
  - inline-em
  - inline-code
  - inline-link
  - horizontal-rule
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/164122/Platform+glossary
  page_id: '164122'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  title: Platform glossary
  status: current
  version: 2
  version_message: Created via mdd
  created_at: '2026-05-11T20:55:02.191Z'
  created_by:
    account_id: 557058:738d4176-8fd3-4b84-92d8-245731e9dfd9
    display_name: Leo Simons
  updated_at: '2026-05-11T20:55:03.086Z'
  updated_by:
    account_id: 557058:738d4176-8fd3-4b84-92d8-245731e9dfd9
    display_name: Leo Simons
  labels: []
  exported_at: '2026-05-11T20:55:03.455150+00:00'
  source_format: storage
  attachments: []
---

# Platform glossary

A short glossary of terms used inside Acme's platform team.
**Synthetic test content** for the round-trip corpus. Definitions
are written in everyday English, not formally — the prose shape
deliberately includes a mix of short and long entries, code
examples, and cross-references so the long-form round-trip
exercises naturally-occurring combinations.

Entries are alphabetical.

---

## Backfill

The process of generating data for a new schema, table, or
metric retroactively by replaying historical events through the
new producer code. Backfills are usually one-shot batch jobs;
they should be *idempotent* (running them twice produces the
same result), *resumable* (a crash mid-run doesn't force a
restart from zero), and *throttled* (they don't starve the
foreground workload).

A typical backfill is invoked like:

```bash
acme-backfill run \
    --producer payments \
    --from 2025-01-01 \
    --to 2025-12-31 \
    --concurrency 4
```

The `--concurrency` flag is the lever that distinguishes a
backfill that completes overnight from one that runs for a week.
Too low and the job blocks subsequent work; too high and it
contends with the foreground workload. The historical rule of
thumb is to start at 4, watch the foreground p99 for an hour,
and tune from there.

See also: **Idempotency**, **Replay**.

## Canary

A deployment pattern where a new version of a service receives
a small fraction of production traffic (typically 1–5 %) for a
fixed observation window before being promoted to receive all
traffic.

Canary windows at Acme are **15 minutes** for code-only changes
and **60 minutes** for anything touching the data path. The
observation window is what catches the slow regressions —
errors that take 10 minutes to manifest, or memory leaks that
only show up under sustained load. A canary that's "green" at
30 seconds is not green.

The canary is automatically rolled back if any of three
conditions fire:

- p99 latency exceeds 1.5× the baseline.
- Error rate exceeds 0.1 % more than baseline.
- Memory usage trends upward at >50 MB/minute.

## Dual-write

A schema-migration pattern where the application writes the same
data to both the **old** and **new** schemas during the migration
window. The read path stays on the old schema until validation
is complete. Once reads are migrated and the old write path is
removed, the migration is done.

Dual-write is reversible until the old schema is dropped, which
makes it the safest migration pattern available. The cost is
two writes per logical operation during the migration window —
budget for ~2× the storage I/O for the duration.

```python
# Pseudocode for a dual-write helper
def write_payment(p):
    write_old_schema(p)         # legacy
    try:
        write_new_schema(p)     # new
    except SchemaError as e:
        log_dual_write_failure(p, e)
        # Do NOT raise — old write succeeded, the user
        # action shouldn't fail because of migration
        # plumbing.
```

The `try/except` around the new-schema write is deliberate: the
migration must not be a regression in availability. Failures
during the dual-write window are logged and reconciled by a
batch job, not by failing the user request.

See also: **Backfill**, **Migration**.

## Idempotency

A property of an operation: running it once produces the same
end state as running it twice (or N times). For HTTP, `PUT` and
`DELETE` are idempotent by convention; `POST` is not.

In practice at Acme:

- **API endpoints**: idempotent unless documented otherwise.
  Clients are expected to retry on 5xx, and retries must not
  produce duplicate side effects.
- **Background jobs**: idempotent by default. Job runners may
  retry on infrastructure failure without coordination.
- **Migrations**: idempotent strictly. The same migration run
  twice produces the same schema; the second run is a no-op.

The most common idempotency mistake is treating *eventual*
consistency as if it were *strict* consistency. A read after
write may not return the value just written; idempotent code
must not depend on the value being visible immediately.

## Migration

A change to the structure or location of stored data. Acme uses
the term narrowly: migrations are about schemas, table shapes,
storage tiers, or region placement. Data **transformations**
(applying business logic to existing data) are not migrations.

Three migration patterns are sanctioned:

- **Dual-write** (see entry): for additive changes where the
  old schema can be retained.
- **Expand-contract**: add the new column/table, backfill,
  migrate readers, then drop the old column/table. Slower than
  dual-write but works when dual-writing isn't feasible.
- **Cutover**: write a freeze, run the migration job, lift the
  freeze. Reserved for cases where neither of the above works.
  Requires explicit approval from the engineering manager.

## Replay

Re-running a stream of events through a consumer, typically to
backfill new state derived from those events. Distinct from a
**retry**, which re-attempts a single failed operation.

Replays are *destructive of derived state*: any computed
aggregates, indexes, or projections that the consumer maintains
will be rebuilt. The original event stream is not modified by a
replay.

```yaml
# Example replay invocation (acme-replay tool)
producer: payments
from: 2024-01-01T00:00:00Z
to: 2024-12-31T23:59:59Z
consumer: search-index
batch-size: 1000
parallel: 8
```

Replays should be tested in pre-prod before production. The
common failure mode is the consumer code having changed in ways
that break on historical event shapes (e.g. a field that was
added in 2025 but didn't exist in 2024 events).

---

This glossary is a living document. Add new entries at the
correct alphabetical position; prefer short, direct prose over
academic precision. If you're not sure whether a term needs an
entry, the test is: would a new engineer joining the team have
to ask what it means? If yes, write it down.
