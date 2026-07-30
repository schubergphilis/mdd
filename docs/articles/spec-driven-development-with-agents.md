# Spec-driven development with AI agents

Almost every design document in this repository ends with a list of resolved
questions. This one comes from
[the documentation-site spec](../spec/S06-documentation-site.md):

> 3. ~~Do generated reference pages get committed and drift-gated, or generated
>    at build time and never stored?~~ **Resolved.** Committed to
>    `docs/reference/`, drift-gated in `mise run ci`. See "Generated reference
>    pages are committed".

The struck-through text is the mechanism. Each question marks a fork where
two designs were possible; the resolution names the winner; and the losing
option stays on the page, crossed out but readable. Multiply that by
thirty-seven specs and fifteen research notes and you have the design record
published on this site. It is not documentation of `mdd`'s code — it is how the code got
written, largely by AI agents under human review
([CONTRIBUTING.md](../../CONTRIBUTING.md)). This article describes the
method as one project practices it: the gates, the rules added after
something went wrong, and what it costs.

## Spec before code

The rule is old by this project's standards: new features get a structured
spec before implementation, focused on design rationale rather than
implementation detail ([S01](../spec/S01-spec-based-development.md)). Each
spec states a purpose, the requirements, the approach chosen, and the options
rejected along the way. A status line tracks it from draft to implemented or
superseded, and [the spec index](../spec/000-specs.md) holds the conventions.

The specs are themselves gated. A build script fails CI on a broken link
between specs, a missing status line, or an `Implemented` status without a
plain date ([the spec index](../spec/000-specs.md)). The design record gets
the same treatment as the code because the agents that write the code read
the specs first, and a rotten record produces rotten code.

Working documents live somewhere else. Research notes — surveys, spikes,
measurements — go in `docs/research/`, and they are deliberately not kept up
to date as the code moves on
([the research index](../research/000-research.md)).
Specs must not link out to them; anything a spec depends on gets copied in, so
the durable record reads on its own. The split lets a note be honestly wrong
later without anything needing repair. The best example: the note comparing
Confluence conversion approaches recommended building on Pandoc with a custom
Lua writer ([R12](../research/R12-confluence-ir-comparison.md)). A fourth
spike overturned that within days — a first-party typed document model beat
Pandoc on every fidelity measure at roughly 94 times less wall-clock
([R13](../research/R13-confluence-ir-spike-pure-python.md)). The note keeps
the overturned recommendation intact under a "Revision" heading, because the
losing analysis is what makes the final decision auditable.

## The gates: a harness agents do not have

One command, `mise run ci`, is the whole quality gate, and the CI pipeline
runs the same tasks a contributor runs locally
([CONTRIBUTING.md](../../CONTRIBUTING.md)). From `.mise.toml`:

```toml
[tasks.ci]
description = "Full CI gate"
depends = [
  "verify-clean",
  "lint",
  "typecheck",
  "complexipy",
  "audit",
  "test",
  "ir-roundtrip",
  "ir-coverage",
  "check-mdd-commands",
]
```

In words: a git-conflict-marker check, ruff lint and format, basedpyright in
strict mode, a cognitive-complexity gate, a dependency audit, the test suite
with coverage, round-trip suites for the document model, and a check that
every `mdd …` command string in user-facing prose names a real command.

The spec that added the structural rules cites published measurements of
repositories where agents work with little supervision — cognitive complexity
up roughly 39% in a few months — and draws the conclusion: "Agents have none
of the implicit human harness — no aesthetic disgust at a 300-line function,
no organisational memory — so the gate has to be made explicit and
machine-checkable" ([S34](../spec/S34-code-quality-gates.md)).

Two decisions in that spec had a losing option worth naming.

**Grandfathering beat the big-bang cleanup.** Enabling the new rules exposed
921 existing violations; fixing them all before any other work could land
would have blocked the project for days. Instead, every existing violation got
a targeted marker on the offending line — never a config-level ignore, never a
bare `# noqa`. This one is still in `src/mdd/ir/serialize.py`, suppressing the
too-many-return-statements rule:

```python
def to_dict(node: object) -> JsonValue:  # noqa: PLR0911
```

The debt is visible at the function definition, and the gate is fully active
for new code from day one. A grandfathered function may not grow: adding
statements to it means refactoring it enough to drop the marker.

**Rejections are sticky, and one was reversed.** The spec keeps a table of
rules considered and not enabled, each with a reason, under the instruction
"do not re-add without reopening this spec." One entry has since been struck
through: the security-lint rules were rejected as noisy — "security review is
a separate concern" — then adopted a month later by amendment, with a curated
ignore list, once the packaging work reframed source-level security smells as
a standing concern for a tool that shells out constantly
([S34](../spec/S34-code-quality-gates.md)). The wrong call and the correction
sit next to each other in the table, in that order.

## The watermark: stopping an agent from making things worse

The cognitive-complexity gate is the most interesting one, because it answers
a question every agent-heavy project hits: how do you hold new code to a
standard the existing code does not meet, without freezing all work until
someone clears the backlog?

`complexipy`, the scanner, has no per-function suppression syntax, so the
marker convention could not carry over; patching one in would have meant
maintaining a fork, which the spec rejects
([S37](../spec/S37-complexipy-cognitive-complexity.md)). Instead the
repository commits a snapshot file, `complexipy-snapshot.json`, recording each
over-threshold function's current score. One entry:

```json
  {
    "path": "src/mdd/ai/rewrite.py",
    "file_name": "rewrite.py",
    "functions": [
      {
        "name": "rewrite_file",
        "complexity": 17
      }
    ]
  },
```

The recorded score is a watermark. This function passes CI at complexity 17 or
below; if a change pushes it to 18, the gate fails. New functions are held to
a threshold of 15 — a measured choice, not a default accepted blindly. Reusing
10, the threshold of the complexity gate already in place, would have produced
135 violations against 75 at 15, gating too aggressively for the same shape of
function ([S37](../spec/S37-complexipy-cognitive-complexity.md)).

The spec states the trade-off plainly: a watermark is less visible in a diff
than an inline marker, but more accurate, because the exact baseline is stored
rather than "this function is grandfathered at some level." And the
file only moves in one direction by policy — regenerating the snapshot "MUST
NOT be run as a routine 'make CI green' reflex"; it exists for deliberate
refactor pull requests that lower watermarks. The mechanism visibly works: the
snapshot listed every function above threshold at adoption, and at the time of
writing it is down to thirteen files. A companion spec keeps file *length* a
heuristic rather than a gate — a target of 300 lines, a soft ceiling of 500,
and an explicit decision **not** to add a file-length lint rule, because
per-function metrics are the machine-checked surface
([S36](../spec/S36-module-structure.md)).

## Rules written after something went wrong

A spec about method tends to read as though the method arrived fully formed.
The git history says otherwise.

The clearest case is the no-cross-references-from-code rule. For most of the
project's life, code cited the specs back: spec numbers in comments, spike
markers in test names, issue numbers in error text. A run of commits in July
2026 stripped every such citation from `src/` and `tests/`, and the rule that
landed with them states why: "The reference is one-directional: specs point at
code, code does not point back" ([AGENTS.md](../../AGENTS.md)). A reader of
the code may not have the spec, and the old issue numbers predate the
open-source cut, so they resolve to nothing — or worse, to an unrelated GitHub
issue that happens to share the number. Removing the citations was only half
the job: the repository still modeled the pattern in places an agent reads
right before editing code, so the rule had to be written where the agents
look. One latent tension remains: the module-structure spec asks oversized
files to carry an `# S36-exception:` comment, which is itself a spec number in
a code comment. Nothing currently carries the marker, so the two rules have
not yet collided.

The command-line interface is a rebuilt dead end. The original spec described
a home-grown command registry, and over time a bespoke flag-parsing
mini-framework grew alongside it — three coexisting parsing styles, each
module maintaining its own usage strings. A rewrite deleted all of it in favor
of a single argparse tree ([S35](../spec/S35-argparse-cli-parsing.md)). The
original spec survives, marked superseded, as the record of the approach that
did not work ([S02](../spec/S02-mdd-cli-tool.md)).

Smaller reversals hide inside individual specs. The skills bundle — the
mechanism that ships agent workflow descriptions with `mdd` so agents know
when to reach for the tool — originally computed its skill index at import
time; that turned out to be incompatible with letting a wrapping distribution
register its own skills, so discovery became lazy
([S23](../spec/S23-skills-bundle.md)). The resolved questions at the bottom of
most specs — like the one this article opened with — record smaller forks the
same way.

## What it costs

Spec discipline is overhead, and pretending otherwise would make this article
worthless. Every non-trivial feature pays for a design document before any
code, plus the hygiene work of keeping the index, the status lines, and the
cross-references valid. The gates add their own tax: a change that trips a
structural threshold gets refactored rather than suppressed, which is slower
than shipping it.

The record also drifts, by design, and the project pays to keep that honest
rather than to prevent it. Running the command-string checker over the design
record surfaced 95 mismatches — commands renamed since a spec was written, and
commands proposed and rejected in exactly the sections that make the record
worth keeping. Every one was correct, so the check runs over specs in an
advisory mode that never fails: rewriting a spec to match today's command tree
would falsify the record ([S06](../spec/S06-documentation-site.md)).

Not everything stated is practiced. The founding spec asks for specs "under
100 lines when possible"; the specs that carry the most weight run well past
200 ([S01](../spec/S01-spec-based-development.md)). Its three-step status
ladder has quietly grown into five states in the conventions document. The
method's own record shows the method being renegotiated, which is consistent
with everything above.

For the conventions themselves, start at
[the spec index](../spec/000-specs.md). For how the design record relates to
the rest of this site, see [the design record](../design-record/index.md).
