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
  - code-block
  - code-block-language
  - inline-strong
  - inline-em
  - inline-code
  - inline-link
  - blockquote
  - horizontal-rule
confluence:
  url: https://markdown.atlassian.net/spaces/MDD/pages/98559/Acme+Internal+Engineering+Handbook
  page_id: '98559'
  space_key: MDD
  space_id: '131077'
  parent_id: '131185'
  title: Acme Internal Engineering Handbook
  status: current
  version: 2
  version_message: Created via mdd
  created_at: '2026-05-11T20:54:59.506Z'
  created_by:
    account_id: 557058:738d4176-8fd3-4b84-92d8-245731e9dfd9
    display_name: Leo Simons
  updated_at: '2026-05-11T20:55:00.353Z'
  updated_by:
    account_id: 557058:738d4176-8fd3-4b84-92d8-245731e9dfd9
    display_name: Leo Simons
  labels: []
  exported_at: '2026-05-11T20:55:00.709460+00:00'
  source_format: storage
  attachments: []
---

# Acme Internal Engineering Handbook

This page is the entry point to the Acme engineering team's
internal handbook. It is **synthetic test content** for the round-
trip corpus — no real people, no real customers, no real products
are referenced. The fictional company "Acme" is used purely as a
narrative anchor so the long-form prose reads naturally and
exercises a realistic mix of markdown shapes.

The handbook covers four areas, in order of how often a new
engineer joining the team needs them:

1. Local development environment
2. Code style and review practices
3. Deployment and rollout
4. Incident response and on-call

Each section below stands on its own; cross-references are
explicit, not implied.

---

## Local development environment

The dev environment runs entirely from a single `mise` toolchain
config. After cloning, run:

```bash
mise install
mise run setup
mise run test
```

`mise install` reads `mise.toml` and installs the right Python,
Node, and supporting binaries into a project-local cache. There
is no `.python-version`, no `nvm use`, and no global pyenv
involvement — the chain is one tool deep and version-pinned.

The `setup` task creates a Python virtual environment under
`.venv/`, installs `uv` if not already present, and runs
`uv sync --all-groups` to materialise every dependency from
`uv.lock`. A successful setup terminates with a green
"environment ready" line on stdout.

### What if setup fails?

The two failure modes that account for ~90 % of new-joiner pain:

- **mise prompts for trust.** Run `mise trust` once per fresh
  clone. `mise run` tasks fail silently without it.
- **Python build dependencies missing.** On macOS, `xcode-select
  --install` resolves it. On Debian, `apt install build-essential
  python3-dev libssl-dev` is the usual fix.

If neither matches, post the full output of `mise doctor` in
the team channel and someone will pair on it within an hour.

---

## Code style and review

We follow three rules, in declining order of importance:

1. **Explicit over clever.** Readability beats brevity. A
   five-line function with a clear name beats a one-liner that
   needs a comment.
2. **Follow the existing patterns.** If you're new to a module,
   read the surrounding code before introducing a new approach.
   Inconsistency within one file is worse than copying a
   slightly-off-pattern that's already established.
3. **One concern per pull request.** Refactors do not ride along
   with feature work. The reviewer's job is harder by an order
   of magnitude when a 200-line diff contains four orthogonal
   changes.

> *On review tone:* be specific. "This could be simpler" is
> not actionable. "Could this be a single comprehension instead
> of the for-loop with append?" — that's a question the author
> can answer yes or no in under a minute.

Tooling enforces what tooling can enforce: `ruff`, `mypy`,
`pytest`. Reviewers focus on what tools can't see: naming,
abstraction boundaries, whether the test cases match the actual
risk surface.

---

## Deployment and rollout

Acme uses a **trunk-based** deployment model. `main` is always
deployable. Every PR that lands triggers a CI build; a green
build deploys to staging automatically.

Promotion from staging to production is **manual** and
**gated**: a human selects a build hash from the recent green
list and confirms the rollout in the deploy tool. The gate
exists because automated promotion at our scale has bitten us
twice — both times when a downstream service had degraded but
not failed, and an automated push compounded the problem.

### Rollback

Rollback is one command: `acme-deploy rollback <service>`. It
re-deploys the last-known-green build hash for that service.
The command is safe to run during an incident — it doesn't
require approval, doesn't log to ticketing, and doesn't touch
the gate.

The team has a [post-mortem template](https://example.com/post-mortem)
that should be filled in within 24 hours of any production
incident, including rollbacks. The template asks the same
questions every time so the data accumulates into a useful
corpus over years.

---

## Incident response and on-call

On-call rotation is one week, starting Monday at 09:00 local
time. The on-call engineer is the **first responder**, not the
sole responder — escalation paths are documented per service
in the runbook.

When paged:

1. Acknowledge within 5 minutes. Even just typing "looking" in
   the channel counts.
2. Update the channel every 15 minutes with one sentence of
   what you're checking, what you've ruled out, and what
   you'll try next.
3. Roll back **first**, debug second. Production stability
   takes precedence over root-cause discovery. The post-mortem
   is the right venue for root cause.
4. Mark the incident resolved only when you've verified the
   fix in production telemetry. "It should be fine now" is
   not resolution.

The on-call engineer doesn't write code that's deployed during
their shift — the cognitive load of monitoring plus writing
plus reviewing leads to errors. The shift trade is six hours
of focused on-call attention plus two hours for the
post-mortem of anything that happened.

---

This handbook is a living document. Propose changes via PR
against the `engineering-handbook` repo; small typo fixes are
self-merge, structural changes need a second approver.
