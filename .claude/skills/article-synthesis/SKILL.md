---
name: article-synthesis
description: Draft an article for the documentation site by synthesizing the spec and research corpus into secondary literature. Use when the user asks to "write an article about X", "synthesize an article from the specs", "draft the article on the IR", or "turn R12 into an article". Enforces citation density, preserved reversals, and never overwriting a promoted article.
---

# Synthesize an article from the design record

The specs under `docs/spec/` and the research notes under `docs/research/` are
primary sources. They are precise, cross-referenced, and written for reviewers
and agents. Nobody reads them for pleasure.

This skill produces the secondary literature: an article-shaped page that tells
a higher-level story and cites the primary sources underneath it. Published
articles live in `docs/articles/` and appear high in the site's sidebar, above
the collapsed design record.

**This is the only content on the site with no mechanical backstop.** The CLI
reference has a drift gate, examples have tests, links have a checker, prose
has Vale. An article has none of that, and no check can detect that it
misrepresented a source. The three constraints below exist because of that, and
they are not negotiable.

## The three constraints

### 1. Citation density

Every non-obvious claim links to the spec or note it came from.

The purpose is reviewability, not scholarly manners. With citations, a reviewer
checks "does this sentence match the cited paragraph". Without them, the only
available check is "does this match my memory of the corpus", which is not a
check. Assume the reviewer will spot-check three sentences at random and will
be annoyed if any of them is unsupported.

Cite inline, as a normal Markdown link on the phrase making the claim:

```markdown
The IR keeps a `raw` escape hatch for storage-format constructs Markdown has no
equivalent for, so a roundtrip preserves them byte-for-byte
([S28](../spec/S28-document-ir-foundation.md)).
```

Not as a bibliography at the bottom. A reader who wants to check one sentence
should not have to guess which of eight entries covers it.

What does not need a citation: things a reader can verify by running a command,
definitions given earlier in the same article, and general background that is
not specific to this project.

**Density is a floor on coverage, not a target for frequency.** Applied
literally, this rule produces prose nobody can read — a link on every clause,
often landing mid-phrase on a verb, so the reader's eye leaves the sentence
several times per sentence. That has already happened once. Three limits:

- **At most one citation per sentence.** Where consecutive sentences draw on
  the same source, cite once and move on.
- **Put the link at the end of the sentence or clause it supports**, never on a
  verb or an arbitrary fragment inside it. A trailing
  `([S31](../spec/S31-ir-normalization-and-whitespace.md))` reads better than a
  link buried on the words "deliberately refuses".
- **Read a paragraph aloud.** If you stumble over where the links sit, move
  them.

A reviewer can check a claim that is cited at the end of its sentence just as
easily. Nothing is lost.

### 2. Preserve reversals

Dead ends, rejected options, and superseded recommendations are the payload.

A model synthesizing a corpus produces, by default, a tidy narrative in which
the right answer was reached directly. That narrative erases the most
interesting content in the corpus and yields prose with no opinions in it. It
is also false: the corpus is full of decisions that were made, tested, and
reversed.

Before you write a word, go looking for the reversals:

```bash
grep -rn -i -E "rejected|reversed|superseded|instead of|we tried|abandoned|does not work|turned out" docs/spec/ docs/research/
grep -rn "~~" docs/spec/            # struck-through open questions, i.e. resolved ones
git log --oneline -- docs/spec/<the-relevant-spec>.md
```

The resolved open questions at the bottom of a spec are the densest source:
each one is a fork where a decision was taken and the losing option is written
down. The research notes for a spike series (`R09` through `R13`, for example)
record what was measured and what failed.

An article that mentions no rejected option is almost certainly wrong. If you
genuinely find none, say so in your report and explain why.

### 3. Never overwrite

Drafts go to `site/src/content/docs/_drafts/_<slug>.md`. Note the underscore on
**both** the directory and the filename. `docsLoader()`'s glob is
`**/[^_]*.{md,mdx}`, and the `[^_]` applies to the filename, not to any
directory above it — so a file at `_drafts/foo.md` is still loaded, still fails
content-schema validation for having no `title`, and still breaks the build.
The underscore on the filename is what actually excludes it. The `_drafts/`
directory is for tidiness.

Drafts are tracked in git, so they can be reviewed in a pull request like
anything else.

Promotion is a `git mv`, done by a human, which drops both underscores:

```bash
git mv site/src/content/docs/_drafts/_<slug>.md docs/articles/<slug>.md
```

**Never write to `docs/articles/` directly.** If the user asks you to revise an
article that is already promoted, read it, write your revision to
`site/src/content/docs/_drafts/<slug>.md`, and show the user the diff:

```bash
diff -u docs/articles/<slug>.md site/src/content/docs/_drafts/<slug>.md
```

Then stop and let them decide. Propose; do not apply.

## Step 1 — Pick the story, not the spec

An article is organized by story. A spec-shaped article is a spec.

Ask what question a reader arrives with, and answer that. "Why does `mdd` have
its own document IR" is a story; "S28 explained" is not. Good articles usually
draw on several specs and notes, and often the interesting one is a research
note that a spec deliberately does not link to.

If the user named a topic, use it. If they asked for "the next article",
propose two or three candidates with a one-line pitch each and let them choose
before you write.

## Step 2 — Read the primary sources in full

Read every spec and note you intend to cite, end to end. Do not cite from a
grep hit or from a summary; the citation is a promise that the cited paragraph
says what you claim.

Read the ones you will not cite too, if they are adjacent — knowing what a
neighboring spec decided is often what stops an article from overstating.

Then check the code. Specs describe intent at the time of writing; `src/mdd/`
is what ships. Where they disagree, the code wins for any claim about current
behaviour, and the disagreement itself is worth a sentence.

## Step 3 — Write

Format and conventions:

- Plain `.md`. No YAML frontmatter — a build script derives the title from the
  single level-1 `# Heading` at the top and strips it from the body, so the
  file starts with exactly one `# ` heading.
- **Write every relative link as if the file already lived in
  `docs/articles/`** — `../spec/S28-document-ir-foundation.md`,
  `../research/R12-confluence-ir-comparison.md`,
  `../guide/03-concepts.md`. Those links are broken while the draft sits in
  `_drafts/`; that is expected, and nothing checks a draft. They resolve the
  moment it is promoted, and `scripts/sync-docs.py` fails the build on one that
  does not.
- Callouts use GitHub alert syntax (`> [!NOTE]`, `> [!WARNING]`, and so on),
  which renders on GitHub and maps to Starlight asides. Not `:::note`.
- No MDX components.
- Length: 800 to 2000 words. Below that it is a guide page; above it, nobody
  finishes it.

Voice — this repository has one writer with an established voice:

- Direct, specific, unhedged. Read a few specs and `README.md` to absorb it.
- Banned words: "simply", "seamlessly", "powerful", "robust", "easily", "just",
  "of course", "delve", "leverage".
- Much of the audience reads English as a second language. Prefer active voice
  and avoid idiom; Vale flags both.
- American spelling. Vale's dictionary is American English.
- No summary paragraph restating the article at the end. Stop when you are
  done.

Content rules:

- **Show something before you explain it.** An article about a conversion
  shows the input and the output; an article about a failure mode shows the
  failure. Use real bytes from a committed file — `tests/corpus/` and the
  fixtures under `tests/` exist for this — never an invented illustration.
  Three short blocks, not three screens.
- **Do not open in notation.** Metric codes, phase numbers and internal
  shorthand (`M1`, `R3`, `P03 phase 5`) are how the corpus talks to itself. A
  reader has not learned them and should not have to. If a number matters, say
  what it measures in words. One piece of shorthand, introduced once, is the
  most an article should ask for.
- **Lead with what is true now.** Superseded measurements belong in the
  reversal that explains them, in a sentence, not in a table the article then
  admits is historical.
- Never assert a fact a generator could state. An article does not enumerate
  flags or list command output; it explains why the design is the way it is.
- Do not invent numbers. If you quote a benchmark or a fidelity percentage, it
  comes from a note that recorded it, and you cite that note.
- If you are not sure, say what is uncertain rather than smoothing it over.

## Step 4 — Self-check before reporting

First, the question the other checks cannot ask: **would somebody who does not
already know this understand it?** Read the draft as an operator who runs
`mdd` and has never opened a spec. Where does it assume the corpus's
vocabulary? Where does it assert something it could have shown? An article
that is accurate, well cited, and impossible to follow has failed — this has
happened, and the author of the system being described was the one who could
not follow it.

Then read it against the three constraints, in this order:

1. **Reversals.** Which decisions in this article had a losing option? Is each
   one named? If the article reads as a straight line from problem to solution,
   go back to the corpus.
2. **Citations.** Take three claims at random. Open the cited file. Does the
   cited paragraph actually say that? Fix or drop anything that does not
   survive.
3. **Overwrite.** `git status --short` shows changes only under
   `site/src/content/docs/_drafts/`. Nothing under `docs/articles/`.

Then run the prose gate, which covers `_drafts/`:

```bash
vale site/src/content/docs/_drafts/<slug>.md
```

Vale runs at warning level, so its findings are advice, not a gate. Read them
and act where they are right.

## Step 5 — Report, do not commit

Report to the user:

- The draft path.
- Which specs and notes you cited, and which you read but did not cite.
- **The reversals you preserved**, listed explicitly. This is the part a
  reviewer checks first.
- Anything you could not verify, and any place the code and the specs disagree.

Do not commit and do not promote. Promotion is the human's `git mv`, and it is
the point at which somebody has read the thing.

## Where this skill does NOT apply

- Operator documentation — that is `docs/guide/`, written from the code and the
  commands rather than synthesized from the design record.
- Writing or extending a spec — use `/spec-extension`.
- Summarizing a spec for a reviewer in chat. This skill produces a published
  page; a summary is just a summary.
