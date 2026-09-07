# S08: Publish-friendly Markdown

**Purpose:** Let `mdd confluence create-page` / `update-page` publish a plain documentation repository as-is — frontmatter `title:` names the page, relative `.md` links become Confluence page links, and ```` ```mermaid ```` fences render to SVG and publish as images — without a preprocessing step.

**Status:** Implemented (2026-09-07)

## Introduction

A documentation repository — Markdown files with `title:` / `description:`
frontmatter, relative `.md` links between pages, and fenced ```` ```mermaid ````
diagrams — is to be published one-way into Confluence with
`mdd confluence create-page` and `mdd confluence update-page`. Three things
stood in the way:

- The page title came from `--title`, the first H1, or the file stem. The
  `title:` key every such repository already carries was ignored, so pages
  landed under their heading or their filename rather than their declared
  title.
- A relative link such as `[setup](../ops/setup.md)` was emitted as a plain
  `<a href="../ops/setup.md">`, which is dead in Confluence: there is no file
  at that path, only a page whose title happens to be "Setup".
- A ```` ```mermaid ```` fence became a code macro that shows the diagram
  source. Confluence Cloud has no native Mermaid rendering.

Each of these forced a preprocessing pass over the tree before publishing,
which then had to be kept out of git or reconciled back. The three
behaviours below remove that step: the source `.md` files are the input,
and only the sibling `<stem>-attachments/` directory gains files.

## Requirements

### Frontmatter `title` participates in title resolution

The page title for `create-page` and `update-page` is resolved in this
order:

1. the `--title` flag (`create-page` only);
2. a top-level frontmatter `title:` whose value is a non-empty string;
3. the first ATX H1 in the body;
4. the file stem.

Only the **top-level** key counts. The `confluence.title` field inside the
`confluence:` block is the mirror of the remote title that `export-page`
wrote and goes stale on rename; it stays out of the rule, as before.

A `title:` that is not a string (`title: 2026`), or is blank, falls
through to the H1 rule rather than being stringified — YAML parses both
shapes silently and neither is an authored title.

The leading-H1 strip on `update-page` ([confluence command](S09-confluence-command.md),
"Title H1 on export and update") keeps working against the resolved
title: when the title comes from frontmatter and the body's first H1
equals it, the H1 is stripped as today; when it differs, the H1 is left
in the body.

### Relative `.md` links resolve to Confluence page links

When rendering local Markdown for `create-page` / `update-page`, every
`Link` node whose `href`:

- has no URL scheme and no host, and does not start with `/`;
- is not a `confluence-*:` synthetic URI (those are already
  `ConfluenceLink` nodes after parsing);
- has a path component ending in `.md`, with an optional `#fragment`;

is resolved against the directory of the source `.md` file.

- **Target exists**: the link becomes a `ConfluenceLink` of `page` kind
  whose target is the target file's page title, derived with the same rule
  as above (frontmatter `title:` → first H1 → stem). The link's inline
  children are kept as the link body. A `#fragment` is carried as the
  `ac:anchor` attribute, so the storage writer emits
  `<ac:link ac:anchor="…"><ri:page ri:content-title="…" /></ac:link>`.
- **Target does not exist**: the link is left untouched and one warning is
  logged naming the source file, the line when it can be located, and the
  href.

Links inside code spans and code blocks are not `Link` nodes, so they are
never touched. Absolute URLs, `mailto:` links, root-relative paths and
`confluence-page:` URIs pass through unchanged.

`--no-resolve-links` on `create-page` and `update-page` turns the pass
off. Export and sync pull are unaffected: this runs only on the
local → Confluence rendering leg.

### ```` ```mermaid ```` fences render to SVG and publish as images

Before attachment sync in `create-page` / `update-page`, a preprocessing
step scans the body for fenced code blocks whose info string's first word
is `mermaid` (so `mermaid {title="x"}` also matches). Fences that open
inside another fenced block are not candidates.

For each fence:

- The content is hashed (`sha256`, first 12 hex characters) and rendered
  to `<stem>-attachments/mermaid-<sha>.svg` next to the source file. The
  content-addressed name is the cache: an existing file is reused without
  invoking the renderer, and two identical fences share one file.
- Rendering is an external command configured in the same config family
  as `svg:` (`configs/mdd.yaml`, then `~/.config/mdd/config.yaml`):

  ```yaml
  mermaid:
    renderer: mmdc
    args: ["-i", "{input}", "-o", "{output}", "-b", "transparent"]
  ```

  The fence content is written to a temporary `.mmd` input file,
  `{input}` / `{output}` are substituted, and the command runs with
  `subprocess.run`. The output is moved into the attachments directory
  only after a successful exit, so a failed render never poisons the
  cache.
- On success the fence is replaced in the body by
  `![Mermaid diagram](<stem>-attachments/mermaid-<sha>.svg)`. The existing
  SVG publish path ([SVG rasterization](S24-svg-rasterization.md);
  `attachments/svg_publish.py`) then rasterizes the SVG to PNG and uploads
  both, exactly as for a hand-placed SVG.
- If the renderer executable is not on `PATH`, one warning per page is
  logged — `mermaid renderer 'mmdc' not found; N diagram(s) left as code
  blocks; install @mermaid-js/mermaid-cli or set mermaid.renderer` — and
  every fence stays a code block.
- If the renderer exits non-zero or produces no output, that fence stays a
  code block and a warning names the fence and the renderer's stderr.

The rewritten body is what gets rendered and pushed. The source `.md` on
disk is never modified; only the attachments directory gains files. The
renderer is not run on export or sync pull.

## Design Approach

- **One title rule, one module.** `mdd.confluence.title.resolve_page_title`
  replaces the two divergent copies (`create.py` used a regex over the
  body, `update.py` a `startswith("# ")` line scan) and is what the link
  resolver calls for its targets, so a page and every link pointing at it
  agree on the title by construction.
- **Links are an IR transform, not a text rewrite.** The pass runs on the
  parsed `Document`, between `parse_markdown` and
  `render_confluence_storage` (and before `reattach` on update). Working
  on `Link` nodes means code spans, code blocks and reference-style
  links are handled by the parser rather than by a second regex grammar,
  and the existing `ConfluenceLink` → `<ac:link><ri:page/>` writer is
  reused unchanged. The tree walk reuses the normaliser's
  `transform_text_blocks`, which is promoted to the public
  `mdd.ir.normalize` surface for this.
- **Mermaid is a text rewrite, deliberately.** The SVG publish path is
  keyed on Markdown image syntax in the body (`scan_local_image_refs`,
  `rewrite_svg_refs_to_png`), so producing an image reference in the body
  is the shortest route to "behaves exactly like a hand-placed SVG" — one
  upload path, one rasterizer, one manifest shape. A dedicated fence
  scanner is used rather than the IR because the rewrite must happen
  before attachment sync, which itself works on the body text.
- **Content addressing over side-cars.** The SVG rasterizer keeps a
  `.meta.yaml` side-car because the source SVG is a file that changes in
  place. A mermaid fence has no file; the hash of its content *is* the
  identity, so the output filename doubles as the cache key and stale
  renders simply stop being referenced.
- **Missing renderer degrades, missing SVG renderer does not.** An absent
  `mmdc` leaves readable (if unrendered) code blocks on the page, so it
  warns and continues. That differs from the SVG rasterizer, which exits
  hard: an unrendered SVG image is a broken image, an unrendered mermaid
  fence is still the diagram source.

## Implementation Notes

- `src/mdd/confluence/title.py` — `first_h1`, `frontmatter_title`,
  `resolve_page_title`. Consumed by `create._resolve_inputs`,
  `update._build_local_spec` and `page_links`.
- `src/mdd/confluence/page_links.py` — `resolve_page_links(doc, md_path,
  body_md=…)`. Titles are cached per target path within one call. The
  warning's line number is best effort: the decoded href is searched for
  in the body text; when it is not found the line is omitted.
- `src/mdd/confluence/mermaid.py` — `render_mermaid_fences(body_md,
  md_path, config=…)`; `MermaidConfig` / `MermaidWrapper` live next to
  `SvgConfig` in `mdd.converters.models`. The fence scanner follows
  CommonMark: backtick or tilde fences of three or more characters, up to
  three spaces of indent, closed by a fence of the same character at least
  as long; an unterminated fence is left alone.
- Call order in `create._run_create` and `update._push_page`:
  `strip_export_header` (and `strip_export_title_h1` on update) →
  `render_mermaid_fences` → `sync_attachments_for_update` →
  `parse_markdown` → `resolve_page_links` → (`reattach`) →
  `render_confluence_storage`. The body-safety guard on update runs
  before the mermaid rewrite so it judges the author's body, not the
  rewritten one.
- `sync-space` push calls `update_page` and therefore inherits both
  passes with their defaults.
- The `--no-resolve-links` flag is `dest="resolve_links",
  action="store_false"` on both parsers and threads through
  `create_page(resolve_links=…)` / `update_page(resolve_links=…)`.
- Tests mock `shutil.which` and `subprocess.run`; the fake renderer writes
  a minimal `<svg/>` to the `{output}` path. No test needs `mmdc`.

## Related upstream specs

- [000-specs](000-specs.md) — shared conventions
- [confluence command](S09-confluence-command.md) — `create-page` / `update-page`, the title-H1 strip on update, and the attachment sync these features extend
- [SVG sibling rasterization](S24-svg-rasterization.md) — the SVG → PNG path a rendered mermaid diagram rides on publish
- [markdown IR conversion](S30-markdown-ir-conversion.md) — the `Link` / `ConfluenceLink` nodes and the `confluence-page:` URI form the link resolver targets
- [typed frontmatter layer](S40-typed-frontmatter.md) — `ConfluenceFrontmatter` allows extra top-level keys, which is what lets `title:` sit beside `confluence:`; `MermaidConfig` follows the same `FrontmatterModel` pattern as `SvgConfig`

## Open questions

1. Should `sync-space` push expose its own `--no-resolve-links`, or is the
   `update_page` default enough? Today it always resolves.
2. A `mermaid.renderer` that is an HTTP service (Kroki) instead of a local
   binary would avoid the Node dependency; the `args` template shape does
   not fit that. Worth a second renderer kind if the demand shows up.
3. Should a link to a `.md` file that exists but is not (yet) published be
   resolved anyway? Today it is — the page title is derived from the file,
   and Confluence renders a link to a non-existent page as a create link.

## Out of scope

- The export / sync pull direction: page links stay `confluence-page:` URIs
  and Confluence-side diagrams stay whatever macro they were.
- Editing the source `.md` files. Neither the rewritten links nor the image
  references are written back; only `<stem>-attachments/` changes.
- Diagram languages other than mermaid (PlantUML, D2, Graphviz). The
  fence scanner and renderer contract would fit them, but each needs its
  own tool and defaults.
- Resolving links to non-`.md` files (a relative `.pdf` or `.png` link).
  Those already ride the attachment path when written as
  `confluence-attachment:` links.
