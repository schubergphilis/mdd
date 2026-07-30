# Spec-driven development with AI agents

`mdd` is written largely by AI agents under human review
([CONTRIBUTING.md](../../CONTRIBUTING.md)). The forty-odd specs and fourteen
research notes published on this site are not documentation of the code. They
are the mechanism by which the code got written, and the quality gates around
them are what makes that tolerable. This article describes the method as one
project practices it — the loop, the gates, the rules added after something
went wrong, and what all of it costs.

## Spec before code

The rule is old by this project's standards: new features get a structured
spec before implementation, focused on design rationale rather than
implementation detail
([S01](../spec/S01-spec-based-development.md)). Each spec states a purpose, the
requirements, the approach chosen, and — this is the part that matters — the
options rejected along the way. A status line tracks each spec from draft to
implemented or superseded, and [000-specs](../spec/000-specs.md) indexes the
whole set alongside its conventions.

The specs are themselves gated. `scripts/spec-check.py` fails the build on a
broken link between specs, a missing status line, or an `Implemented` status
that does not carry a plain `(YYYY-MM-DD)` date
([000-specs](../spec/000-specs.md)). The design record gets the same
treatment as the code: machine-checkable rules, enforced in CI, because the
agents that write the code read the specs first and a rotten record produces
rotten code.

Working documents live somewhere else. Research notes — surveys, spikes,
measurements — go in `docs/research/`, and they are deliberately not kept up
to date as the code moves on
([000-research](../research/000-research.md)). Specs must not link out to
them; anything a spec depends on gets copied in, so the durable record reads
on its own ([000-specs](../spec/000-specs.md)). The split lets a note be
honestly wrong later without anything needing repair. The best example: the
IR comparison note recommended building on Pandoc with a custom Lua writer,
and a fourth spike overturned that within days — a first-party typed IR beat
Pandoc on every measured fidelity metric at roughly 94× less wall-clock per
fixture ([R12](../research/R12-confluence-ir-comparison.md),
[R13](../research/R13-confluence-ir-spike-pure-python.md)). R12 keeps its
original recommendation intact under a "Revision" heading rather than
rewriting it, because the overturned analysis is what makes the final
decision auditable.

## The gates: a harness agents do not have

The spec that added the gates states why this project gates structural code
quality, and the reason is specific to agents. Published measurements of
repositories where agents do significant unsupervised work show roughly 39%
increases in cognitive complexity over a few months, and as
[S34](../spec/S34-code-quality-gates.md) puts it: "Agents have none of the
implicit human harness — no aesthetic disgust at a 300-line function, no
organisational memory — so the gate has to be made explicit and
machine-checkable."

So the gates are explicit. `mise run ci` runs, in order: a conflict-marker
check, ruff lint and format checks, basedpyright in strict mode, a
cognitive-complexity gate, a dependency audit, the test suite with coverage,
the IR round-trip suites, and a check that every `mdd …` command string in
user-facing prose is a real command. The CI pipeline invokes the same mise
tasks, so the local gate and the one guarding `main` are the same gate
([CONTRIBUTING.md](../../CONTRIBUTING.md)).

Two decisions in S34 are worth pulling out, because both had a losing option.

**Grandfathering beat the big-bang cleanup.** Enabling the new rules exposed
921 existing violations; fixing them all before any other work could land
would have blocked the project for days. Instead, every existing structural
violation got a targeted `# noqa: <code>` on the offending `def` line — never
a config-level ignore, never a bare `# noqa` — so the debt is visible at the
function definition and the gate is fully active for new code from day one
([S34](../spec/S34-code-quality-gates.md)). A grandfathered function may not
grow: adding statements to it means refactoring it enough to drop the marker.

**Rejections are sticky, and one was reversed.** S34 keeps a table of rules
considered and not enabled, each with a reason, under the instruction "do not
re-add without reopening this spec." One entry has since been struck through:
the security-lint rules were originally rejected as "noisy … security review
is a separate concern," then adopted a month later by amendment, with a
curated ignore list, once the packaging work reframed source-level security
smells as a standing concern for a tool that shells out constantly
([S34](../spec/S34-code-quality-gates.md)). The reversal lives in the spec as
struck-through text next to the amendment that overrode it — the record shows
the wrong call and the correction, in that order.

## The watermark: stopping an agent from making things worse

The most interesting gate is the cognitive-complexity one, because it answers
a question every agent-heavy project hits: how do you hold new code to a
standard the existing code does not meet, without freezing all work until
someone clears the backlog?

`complexipy` has no per-function suppression syntax, so the `# noqa`
convention could not carry over. Instead the repository commits a snapshot
file, `complexipy-snapshot.json`, recording each over-threshold function's
current score as a watermark. A function passes if it stays at or below its
watermark; the threshold of 15 applies to new functions; a function whose
complexity grows above its recorded score fails CI
([S37](../spec/S37-complexipy-cognitive-complexity.md)). The threshold itself
was a measured choice, not a default accepted blindly: 10 — matching the
McCabe gate — would have produced 135 violations against 75 at 15, gating too
aggressively for the same shape of function.

The spec states the trade-off against `# noqa` plainly: the watermark is less
visible in a diff, but more accurate, because the exact baseline is stored
rather than "this function is grandfathered at some level." And the file only
moves in one direction by policy. Regenerating the snapshot "MUST NOT be run
as a routine 'make CI green' reflex" — it exists for deliberate refactor PRs
that lower watermarks ([S37](../spec/S37-complexipy-cognitive-complexity.md)).
The mechanism visibly works: the snapshot listed every function above
threshold at adoption, and at the time of writing it is down to thirteen
files. A companion spec keeps file *length* a heuristic rather than a gate —
a target of 300 lines, a soft ceiling of 500, and an explicit decision **not**
to add a file-length lint rule, because per-function metrics are the
machine-checked surface ([S36](../spec/S36-module-structure.md)).

## Rules written after something went wrong

A spec about method tends to read as though the method arrived fully formed.
The git history says otherwise.

The clearest case is the no-cross-references-from-code rule. For most of the
project's life, code cited the specs back: comments like `(spec S27)`, test
markers like `Spike fix 2`, issue numbers in error text. A run of commits in
July 2026 stripped every such citation from `src/` and `tests/`, and the rule
that landed with them in [AGENTS.md](../../AGENTS.md) states why: "The
reference is one-directional: specs point at code, code does not point back."
A reader of the code may not have the spec, and the old issue numbers predate
the open-source cut, so they resolve to nothing — or worse, to an unrelated
GitHub issue that happens to share the number. The cleanup commit is candid
that removing the citations was only half the job: the repository still
modeled the pattern in places an agent reads immediately before editing code,
so it would have been reintroduced. The rule had to be written where the
agents look. (One latent tension remains: S36's `# S36-exception:` file
marker is itself a spec number in a code comment. Nothing currently carries
the marker, so the two rules have not yet collided.)

The CLI is a rebuilt dead end. The original dispatcher spec described a
home-grown command registry and, over time, a bespoke flag-parsing
mini-framework grew alongside it — three coexisting parsing styles, each
module maintaining its own usage strings. A rewrite deleted all of it in
favor of a single argparse tree, and the original spec survives, marked
superseded, as the record of the approach that did not
([S02](../spec/S02-mdd-cli-tool.md),
[S35](../spec/S35-argparse-cli-parsing.md)).

Smaller reversals hide inside individual specs. The skills bundle — the
mechanism that ships agent workflow descriptions with `mdd` so agents know
when to reach for the tool — originally computed its skill index at import
time; that turned out to be incompatible with letting a wrapping distribution
register its own skills, so discovery became lazy
([S23](../spec/S23-skills-bundle.md)). The resolved open questions at the
bottom of most specs record forks like this one at smaller scale, each with
the losing option written down.

## What it costs

Spec discipline is overhead, and pretending otherwise would make this article
worthless. Every non-trivial feature pays for a design document before any
code, plus the hygiene work of keeping the index, the status lines, and the
cross-references valid. The gates add their own tax: a change that trips a
structural threshold gets refactored rather than suppressed, which is slower
than shipping it.

The record also drifts, by design, and the project pays to keep that honest
rather than to prevent it. Running the command-string checker over the design
record surfaced 95 mismatches — commands renamed since a spec was written,
and commands proposed and rejected in exactly the sections that make the
record worth keeping. Every one was correct, so the check runs over specs in
an advisory mode that never fails: rewriting a spec to match today's command
tree would falsify the record ([S06](../spec/S06-documentation-site.md)).

Not everything stated is practiced. S01 asks for specs "under 100 lines when
possible"; the specs that carry the most weight run well past 200. Its
three-step status ladder has quietly grown into five states in the
conventions document. The method's own record shows the method being
renegotiated, which is consistent with everything above.

This article is itself a product of the process it describes: drafted by an
agent under a skill that enforces citation density and the preservation of
reversals, into a drafts directory it cannot promote from
([S06](../spec/S06-documentation-site.md)). A human decides whether it
publishes.

For the conventions themselves, start at [000-specs](../spec/000-specs.md).
For how the design record relates to the rest of this site, see
[the design record](../guide/09-design-record.md).
