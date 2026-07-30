# 015 — AI-tell detection, and how to evaluate a prose linter

**Status:** Open. Proposes an evaluation method; no adoption decision yet.

This note records a first evaluation of the `vale-ai-tells` Vale package
against `mdd`'s prose, explains why that evaluation could not answer the
question it was asked, and proposes a preference-elicitation method that can.

The immediate trigger is [S06](../spec/S06-documentation-site.md), which added
a Vale gate over the documentation site's prose and deferred a rule-set
review until there was content to judge against. The larger question is
narrower and harder than "which style package": almost all of this
repository's prose is written by AI agents under human review, so a
deterministic check against AI-slop tells is a check on the dominant
production process, not a spot check on an occasional contributor.

## The package

[`tbhb/vale-ai-tells`](https://github.com/tbhb/vale-ai-tells), MIT licensed,
actively maintained — around two tagged releases a week since March 2026, at
`v1.26.0` as of this evaluation. It ships three artifacts: `ai-tells`
(77 rules, all at `level: error`), `ai-tells-experimental` (17 rules, mostly
Tengo scripts doing structural analysis), and `ai-tells-commits` (13, scoped
to commit messages). 74 of the 77 core rules are `existence` rules — token
and regex lists.

Pinned release URLs work in `Packages =` exactly as the `write-good` v0.4.1
pin already does, and the synced styles directory would be gitignored the same
way, so nothing is redistributed and the licence question does not arise.

## What the first evaluation measured

Two agents ran the package over three corpora and over the four synthesised
articles drafted for the documentation site. Whole package, all 77 rules:

| Corpus | Words | Files | Alerts | per 1k |
|---|---:|---:|---:|---:|
| `docs/guide/` | 10,515 | 9 | 69 | 6.6 |
| `docs/spec/` + `docs/research/` | 98,261 | 54 | 1,682 | 17.1 |
| `README` + `CONTRIBUTING` + `AGENTS` | 1,619 | 3 | 18 | 11.1 |

42 of the 77 rules never fired on any corpus. A curated 36-rule subset — the
never-fired rules plus the low-noise ones — produced 3 alerts on the guide, 22
on the design record, and 0 on the root files, and all 3 guide alerts were
false positives. Precision over the four articles was about 4%: roughly 118
hits, roughly 5 worth acting on.

Both agents independently recommended rejecting the same rules. Some of those
rejections are clearly right on the evidence:

- **`FormalRegister`** — 107 hits, 92 of which are the word `implement` or
  `implementation`. There is no plainer synonym in this domain.
- **`VerbTricolon`** — its regex treats any word ending in *s* as a verb, so
  it fires on noun lists and on colon-plus-comma enumerations of numbers.
  Near-total false positive.
- **`ShipOveruse`** — "ships with `mdd`" means *is in the production tree*,
  which is the exact distinction the sentences using it exist to draw.

Two other findings are worth keeping regardless of what happens next.

**The tone words are better served by a custom style.** The package covers
only 2 of the 5 words this project already catches by hand (`seamlessly` and
`robust`); `simply`, `easily` and `powerful` are absent as bare tokens. And
the rule carrying those two, `OverusedVocabulary`, also bans `comprehensive`,
`crucial`, `significant`, `genuine` and `actionable`, which this corpus uses
correctly. A hand-written 35-token style caught all 9 tone markers in a
synthetic slop page and produced 9 hits across 110k words of real prose — four
of them being [R14](R14-documentation-strategy-and-site.md)'s own sentence
listing the banned words. Write that style regardless.

**The structural rules found something the lexical rules could not.**
`ai-tells-experimental.ContractionAvoidance` fires on 8 of 9 guide pages.
Contractions per 1000 words across the repository:

| Group | Words | Contractions | per 1k |
|---|---:|---:|---:|
| Articles (4) | 6,473 | 1 | 0.15 |
| `docs/guide/` (9) | 9,730 | 0 | 0.00 |
| `README` + `CONTRIBUTING` + `AGENTS` | 1,524 | 0 | 0.00 |
| `docs/spec/` | 50,577 | 65 | 1.29 |
| `docs/research/` | 39,338 | 144 | 3.66 |

One contraction in 6,473 words is not a style choice; it is the absence of
one. Whether that matters is a house-voice question, but it is a deterministic
finding that human review did not produce, which is the reason to want a tool
like this at all.

## Why the evaluation could not answer the question

The first evaluation's central argument was comparative. It observed that the
package flags `AGENTS.md` (20.2 alerts/1k) and
[S07](../spec/S07-data-protection.md) (19.8/1k) harder than three of the four
agent-drafted articles, and that on ex-punctuation counts
[S06](../spec/S06-documentation-site.md) (8.2) beats two of them. It concluded
that a tool ranking the maintainer's prose above the agents' prose is not
measuring authorship, and used that to justify keeping several rules off.

**That argument rests on a false premise.** Very little of this repository's
prose was written by a human unaided. The specs, the research notes, `AGENTS.md`
and the README are AI-written or AI-assisted, the same as the guide pages and
the articles. There is no human-written control group in the corpus, so
"it flags your prose harder than the agents'" is not evidence of miscalibration.
It is equally consistent with the package working correctly and the entire
baseline being the thing the package detects.

Every conclusion in the first evaluation that leans on the corpus as a
reference standard inherits this error. The rules rejected on measurement
grounds — `FormalRegister`, `VerbTricolon`, `ShipOveruse` — survive it, because
their failures are demonstrable sentence by sentence. The rules rejected on
*house voice* grounds do not, because house voice is exactly what is in
question.

Two of those rejections look wrong on the maintainer's own judgment:

- **`EmDashUsage`.** The single highest-firing rule: 826 hits in the design
  record (8.41/1k), 15 in the guide, 12 across the root files. Rejected on the
  grounds that em-dashes here are deliberate. They are — and there are also
  far too many of them. The rule is crude (it flags every `—` and `–` at error
  level with no exemptions, which is unusable as written), but the signal it
  is reporting is real.
- **`ContrastiveFormulas`.** Rejected because its bare-appositive tokens fire
  on "a heuristic, not a gate" and similar, called "a defining move in this
  repo's register". That construction is also over-used, and being a defining
  move of an AI-written corpus is not a defence.

So the two rules the evaluation argued hardest to keep off are two the
maintainer wants flagged. This is not a small correction at the edges; it
inverts the method. Counting alerts against an AI-written baseline measures
how much a corpus resembles itself.

## What would actually settle it

The missing ingredient is human preference, elicited on concrete prose rather
than on rule descriptions. A rule is worth adopting if applying it produces
text a human reader prefers. Nothing else is decisive, and nothing measured so
far is a proxy for it.

Proposed method:

1. **Fix a rule set under test.** Start with the full 77-rule package plus the
   experimental structural rules, minus the rules whose failures are already
   demonstrated sentence by sentence. Keep `EmDashUsage`,
   `ContrastiveFormulas`, `CataphoricForecasting`, `SemicolonUsage` and the
   other register rules **in**. They are the contested cases and the whole
   point is to stop adjudicating them by argument.

2. **Sample passages from existing prose.** Draw from the guide pages, the
   four articles, and the design record, weighted toward passages that trigger
   contested rules but including untriggered passages as controls. The control
   passages matter: without them the exercise only measures whether rewriting
   helps where a rule fired, not whether the rule fired in the right places.

3. **Have an agent produce a minimal rewrite** that clears the findings.
   Minimality is the load-bearing constraint — the instruction is to make the
   smallest edit that satisfies the rule, not to improve the passage. A
   rewrite that improves the prose for unrelated reasons contaminates the
   comparison, because then the preference measures the rewriter rather than
   the rule.

4. **Present pairs side by side for human judgement.** Original and rewrite,
   order randomised, rule attribution hidden at the point of choice. Record
   the preference, and record *why* in a few words, because the reason is what
   distinguishes "this rule is wrong" from "this rule is right and the rewrite
   was bad".

5. **Attribute preferences back to rules.** A rule whose rewrites are
   preferred is worth adopting. A rule whose rewrites are consistently
   rejected is not, and now with evidence rather than assertion. A rule whose
   rewrites are preferred only sometimes needs its token list narrowed, which
   is the outcome the first evaluation reached for `ContrastiveFormulas` by
   inspection and could not confirm.

### Design questions this raises

**Unit of comparison.** Sentence, paragraph, or section. Sentences isolate the
rule best but strip the context that makes a construction good or bad —
`CataphoricForecasting`'s hits are individually fine and collectively
monotonous, which a sentence-level comparison cannot see. Paragraph is
probably the right default, with a section-level pass for the rules whose
complaint is about rhythm.

**Blinding.** Which is original and which is rewritten will often be guessable.
That is tolerable if the preference is honest, and it is a reason to record
reasons rather than only choices.

**Sample size.** Enough per rule to distinguish a preference from noise, and
the contested rules are the ones that need the most. This is the main cost of
the method and the reason to pick the rule set deliberately in step 1.

**Who judges.** One judge, which is both the constraint and the point: the
question is what this project's prose should read like, and there is one
person whose answer settles that.

**Reusability.** If the harness is worth building, it is worth building so a
second package, or a hand-written style, can be run through it later. The
output is a preference dataset, not a verdict on one package.

## What this is not

Not an `mdd` feature. Running a prose linter over mirrored content is a
plausible and much larger piece of work with an audience well beyond this
repository, and [S06](../spec/S06-documentation-site.md) already places it out
of scope. This note is about this project's own prose gate.

Not a decision to adopt or reject the package. The first evaluation's
demonstrated false positives stand, and its two side findings — the custom
tone-word style, and the contraction result — are worth acting on
independently of anything else here. The contested register rules stay
unadjudicated until there is preference data.

## Open questions

1. Is the minimal-rewrite constraint achievable in practice, or will an agent
   asked to satisfy a rule reliably improve the passage in other ways at the
   same time? If it cannot be held, the comparison measures the rewriter and
   the method needs a different control.
2. Should the design record be in scope at all? It carries the largest alert
   counts and the loosest register, and [S06](../spec/S06-documentation-site.md)
   deliberately exempts it from the Vale gate. Including it in the evaluation
   while keeping it out of the gate is defensible — the preference data is
   about the rules, not about which paths get linted — but it inflates the
   sampling cost.
3. Does a preference for a rewritten passage generalise to a preference for
   the rule, given that the rewrite is one of many that would satisfy it?
4. What is the right treatment of a rule that is right in aggregate and wrong
   per instance? `CataphoricForecasting` is the clear case: eight "N things"
   openers across four articles is a rhythm worth breaking, but no individual
   hit is a defect. A gate that fires per occurrence is the wrong shape for
   that complaint, and an occurrence-density rule may be the right one.
5. Is there a usable human-written control group anywhere — older commits,
   another project by the same author — that would let the comparative
   framing be repaired rather than discarded?

## Artifacts

The first evaluation ran in a scratch directory outside the repository and
modified nothing tracked. Its reproducible parts: a throwaway `.vale.ini` per
configuration (whole package, curated subset, experimental package), a
35-token `mdd.ToneWords` style, a synthetic AI-slop guide page used as a
positive control, and raw JSON alert dumps per corpus. If the evaluation
described above goes ahead, those should be rebuilt inside a committed
harness rather than recovered from scratch space.
