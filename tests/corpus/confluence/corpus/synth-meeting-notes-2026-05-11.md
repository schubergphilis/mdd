---
test_corpus:
  authoring: markdown-first
  shapes:
  - paragraph
  - heading-h1
  - heading-h2
  - heading-h3
  - list-bullet
  - list-ordered
  - table
  - inline-strong
  - inline-em
  - inline-code
  - inline-link
  - blockquote
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/98579/Meeting+notes+Platform+sync+2026-05-11
  page_id: '98579'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  title: Meeting notes — Platform sync, 2026-05-11
  status: current
  version: 2
  version_message: Created via mdd
  created_at: '2026-05-11T20:55:04.958Z'
  created_by:
    account_id: 557058:738d4176-8fd3-4b84-92d8-245731e9dfd9
    display_name: Leo Simons
  updated_at: '2026-05-11T20:55:05.817Z'
  updated_by:
    account_id: 557058:738d4176-8fd3-4b84-92d8-245731e9dfd9
    display_name: Leo Simons
  labels: []
  exported_at: '2026-05-11T20:55:06.288470+00:00'
  source_format: storage
  attachments: []
---

# Meeting notes — Platform sync, 2026-05-11

Weekly platform team sync. **Synthetic test content** — no real
attendees, no real customers, no real decisions. Names and
project references are invented for narrative coherence in the
round-trip corpus.

## Attendees

| Name        | Role               | Joined |
| ----------- | ------------------ | ------ |
| Alice Chen  | Platform engineer  | 09:00  |
| Bob Singh   | Platform engineer  | 09:00  |
| Carol Mendez | SRE lead          | 09:03  |
| Dan Park    | Engineering manager | 09:00  |

Apologies: *Eva Lindqvist* (on parental leave), *Faisal Omar*
(customer escalation).

## Agenda

1. Last week's action items
2. Q2 milestone status
3. Database migration rollout plan
4. Incident review: 2026-05-09 partial outage
5. Open floor

---

## 1. Last week's action items

Three items from 2026-05-04. Status of each:

- **Alice**: write the rollout doc for the migration. *Done* —
  see the `migration-rollout` doc.
- **Bob**: investigate the `429` spike in the rate-limit gateway.
  *In progress* — initial findings suggest a noisy retry loop
  in one client; full report by 2026-05-15.
- **Carol**: schedule the failover drill. *Blocked* — waiting on
  capacity allocation from infra. Carol will re-raise with
  infra today.

Decision: roll Bob's investigation forward to next week. No new
information expected before then.

## 2. Q2 milestone status

Three milestones remain for Q2. Status as of today:

- **M1 — Service mesh upgrade**: on track for 2026-06-15. No
  blockers. Carol's team has the test plan signed off.
- **M2 — Database migration v2**: on track but tight. Estimated
  completion 2026-06-28 against the Q2 deadline of 2026-06-30.
  We need one of the two stretch items (audit logging or
  cross-region replicas) to slip if any unplanned work lands.
- **M3 — Platform metrics overhaul**: behind by ~2 weeks. Root
  cause is two engineers reallocated to incident response. Dan
  will reset expectations with the requesting stakeholder by
  end of week.

> *Dan's framing:* "On-track-but-tight is our default state. The
> question is which of the M2 stretch items we drop first when
> the data-replication estimate slips, not whether it will."

## 3. Database migration rollout plan

Alice walked through the rollout doc. Three phases:

1. **Phase 1** (2026-05-20 to 2026-05-23): dual-write to old and
   new schemas. Read path unchanged. Reversible by toggling the
   write fan-out off.
2. **Phase 2** (2026-05-24 to 2026-05-30): read path moves to
   new schema. Old schema still receives writes for rollback
   capacity. Reversible by toggling the read source.
3. **Phase 3** (2026-05-31 onwards): writes stop going to old
   schema. Old data retained read-only for 90 days for audit.
   Not reversible without backfill.

The migration runs across **all three regions** simultaneously
in each phase. Carol pushed back: she'd prefer one region per
phase, staged over a week. After discussion the team agreed to
a **compromise**: phase 1 simultaneous (low risk, easy rollback),
phase 2 staggered region-by-region with 24 hours between cuts,
phase 3 simultaneous (already validated by phase 2).

Action items from this discussion:

- Alice updates the rollout doc to reflect the staggered phase 2.
- Carol drafts the region-cut go/no-go checklist.
- Bob writes the smoke-test suite that the cut runs against
  before each region promotes.

## 4. Incident review: 2026-05-09 partial outage

15-minute degradation in the `us-west-2` region. Caused by a
deploy that touched the rate-limit gateway's retry budget; the
new value (3 retries with 200ms backoff) interacted poorly with
a downstream service that was already serving 503s under load.

What went well:

- Time-to-detect: 90 seconds (alert fired on p99 latency).
- Time-to-rollback: 4 minutes (one-command rollback).
- Communication: status page updated within 2 minutes of
  acknowledgement.

What didn't go well:

- The retry budget change was reviewed but the reviewer didn't
  notice the downstream service was already degraded in
  pre-prod telemetry. The dashboard for the downstream service
  wasn't linked from the change description.
- Post-mortem was written, but the action items were vague
  ("improve review process"). Need to convert into specific,
  trackable items.

Carol will rewrite the action items by 2026-05-15.

## 5. Open floor

- *Bob*: any appetite for revisiting the on-call rotation
  length? Six-hour focused shifts have been working but mid-
  week handoffs introduce churn. Park to next sync.
- *Alice*: the [migration runbook template](https://example.com/migration-runbook)
  is now in the templates repo. Use it for any future schema
  migration; copies of v1 of the template that exist in older
  branches should be ignored.
- *Dan*: reminder that the all-hands is moved to 2026-05-22.
  Calendar invite is out.

---

**Next sync**: Monday 2026-05-18, 09:00. Standing agenda
applies. Send agenda additions to Dan by Friday EOD.
