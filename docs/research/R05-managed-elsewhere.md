# 005 - Externally-managed Confluence pages

**Status:** Research notes. Not an implementation spec.

> This note was originally written against two concrete in-house
> publishing systems. The organisation-specific evidence stayed
> behind; what follows is the generic detection model those two
> cases produced. Where an example needs a name, it uses
> `docs-pipeline` (a Sphinx publisher) and `technical-documentation`
> (an external markdown sync), matching the vocabulary of
> [spec 026](../spec/S26-managed-elsewhere.md).

**Problem brief.** Automation systems publish content into
Confluence directly. Two shapes are common:

1. **A Sphinx-based publisher.** Source of truth is RST + Jinja2
   templates in a git repo; a CI job runs
   `sphinxcontrib-confluencebuilder` to publish into a space. Each
   published page carries a "View source" link footer pointing at
   the upstream repo, and (on acceptance environments) a banner
   macro.

2. **An external markdown sync.** Source of truth is plain markdown
   in a git repo; some sync tool *outside* that repo pushes it into
   a page subtree. The repo itself has **no** publishing code, and
   the published pages carry **no** detectable markers.

Pages published this way are sometimes also **read-only restricted**
at the Confluence permission layer — non-publisher users can't
update them even if they tried.

If `mdd confluence sync` (spec 014) attempts to push to either of
these, it would clobber the upstream automation's output. The
`mdd` push would land, then the next publish run would overwrite our
changes, and the round-trip would oscillate forever. We must detect
these pages and **refuse to push** with a useful error.

This document maps the detection surface, proposes a generalised
config-driven detection model, and recommends how `mdd` handles a
managed page on both pull (export) and push (sync update) paths.
It deliberately stops short of CLI flags and exact YAML schema —
those go in a follow-up impl spec.

## Round-trip risks

What `mdd` would lose if it pushed to a Sphinx-published page:

- RST-specific syntax (custom directives, `sphinx_design`
  containers, role substitutions) doesn't round-trip through
  markdown cleanly.
- Generated content from Jinja templates wouldn't survive any
  manual markdown edit; the next publish run would overwrite it.
- The "View source" footer would be stripped and re-added in
  inconsistent positions.

The external-markdown-sync case is the more fragile of the two:
there are no markers at all, so if `mdd` doesn't know about the
system it'll happily round-trip the page and the external sync will
overwrite the changes on its next run. Hardcoded Confluence URLs in
such a markdown body also break if pages are renamed or moved.

## Common pattern

Both shapes share a few invariants we can exploit:

1. **A specific publishing identity** writes the page (a service
   account). The Confluence v2 API exposes `version.authorId`
   on the page metadata.
2. **A known source repo** is the actual master. We can detect
   this via a body marker (the Sphinx publisher's source link), a
   page property / label (if the publisher sets one), or by user
   declaration in `mdd` config (the marker-free case).
3. **Read-only restrictions** (sometimes) are set on the
   Confluence side via the page restrictions API.

Detection should layer these signals so that any of them is
sufficient to classify a page as managed-elsewhere.

## Detection mechanisms in priority order

### 1. Confluence page restrictions (read-only)

Always check, for every push attempt:

- `GET /wiki/rest/api/content/{pageId}/restriction` (v1; v2 has
  partial coverage) returns the restriction list. If the current
  user is not in the "update" allow-list, the push will 403
  anyway. We pre-flight to fail with a clearer message:
  `"Page is read-only restricted. Cannot update via mdd."`
- The check is cheap (one GET per page about to push) and
  load-bearing for the sphinx-published pages where the publisher
  is the only allowed updater.

### 2. Publishing identity match

For every page about to push, compare `version.authorId` (or
`version.by.accountId` in v2) against a configured list of
"known external publisher account IDs":

```yaml
confluence:
  external_publishers:
    - account_id: "5e3f...docs-pipeline-bot"
      name: docs-pipeline
      source_url: https://gitlab.example.com/tat/docs-pipeline
      message: |
        This page is published by the docs-pipeline Sphinx
        automation. Edit the source RST in <source_url>; the next
        CI run will republish.
    - account_id: "5e3f...techdocs-bot"
      name: technical-documentation
      source_url: https://gitlab.example.com/SaaS/technical-documentation
      message: |
        This page is part of the Technical Documentation bundle,
        synced from git. Edit the markdown in <source_url>; the
        sync tool will republish.
```

If the page's last-update author matches a configured external
publisher, refuse to push, print the configured `message` (with
`<source_url>` substituted). This gives both systems a clean
detection path even when no body marker exists.

The user maintains the `account_id` list once. The IDs can be
discovered with `mdd confluence whoami` (proposed helper) or by
asking the publishing-team owner.

### 3. Body markers

Pattern-matching the rendered page body for known footers.
Fallback for cases where the publisher account ID isn't yet known
or has rotated.

```yaml
confluence:
  external_publishers:
    - name: docs-pipeline
      body_marker_patterns:
        - 'View source on GitLab.*docs-pipeline'
      source_url: ...
      message: ...
```

The matcher runs against the storage XHTML body. Cheap (one regex
pass per push). One match is sufficient.

### 4. Spaces / page-tree blanket rules

Coarsest level: declare an entire space (or page subtree) as
managed-elsewhere.

```yaml
confluence:
  managed_spaces:
    - space_key: DOCS
      name: docs-pipeline
      source_url: ...
      message: ...
  managed_subtrees:
    - space_key: saas
      root_page_id: "844137445"      # Technical Documentation
      name: technical-documentation
      source_url: ...
      message: ...
```

Useful when:

- A space is *entirely* managed by one publisher.
- A subtree is *entirely* managed (the Technical Documentation page
  tree).

This gives the user a fast, fingerprint-free way to lock down a
known external system. Anyone running `mdd confluence sync`
against that space refuses by default; the user must override
explicitly per page.

### 5. Page labels (optional, future)

If a publisher applies a Confluence label (e.g.
`managed-externally`, `published-by-sphinx`), `mdd` can detect
it. Neither of the two systems we inspected does this today, but
it's a clean signal worth supporting:

```yaml
external_publishers:
  - name: any-system-with-labels
    label: managed-externally
    message: ...
```

## Recommended detection cascade

For every page, on push attempt:

1. Is the page in a `managed_spaces` entry? → refuse, show that
   publisher's `message`.
2. Is the page in a `managed_subtrees` entry? → refuse, show
   message.
3. Does `version.authorId` match any `external_publishers[*].account_id`? → refuse, show message.
4. Does the body match any `external_publishers[*].body_marker_patterns`? → refuse, show message.
5. Does the page carry any `external_publishers[*].label`? → refuse, show message.
6. Is the page restricted such that the current user cannot
   update? → refuse with a "read-only restriction" message.
7. Otherwise: push as normal.

`--force-managed` would override checks 1-5 (but not 6 — restriction
is enforced server-side anyway). Useful for the rare case of
manually fixing a stuck managed page outside of the upstream
automation; logged with a warning.

## Pull-side behaviour

Pulling (export / sync) a managed page is fine — we always have
read access. Two refinements worth making:

1. **Stamp `confluence.managed_by` on the exported markdown's
   frontmatter** when detection fired. Future pushes from the
   same mirror clone re-detect immediately without consulting
   config:

   ```yaml
   confluence:
     page_id: "12345"
     managed_by: docs-pipeline
     managed_source_url: https://gitlab.example.com/tat/docs-pipeline
   ```

   This is belt-and-braces — the per-page push check
   re-runs the detection against current API state too — but it
   makes the markdown mirror self-describing.

2. **Augment the export header** to mention the source repo
   prominently. Spec 009's existing export header gets a
   conditional extra line:

   ```
   > **Confluence export (managed by docs-pipeline)**
   >
   > This page is published from
   > <https://gitlab.example.com/tat/docs-pipeline>.
   > Edit there; this mirror is read-only.
   > Exported on 2026-05-08.
   ```

   This signals to anyone reading the mirror that local edits will
   bounce when push runs. It also serves as an "edit source" link,
   which is what the user wants.

## Push-side behaviour

When a managed-elsewhere page is detected on push attempt:

- `mdd confluence update-page` exits 1 with the configured
  message. Single-page case.
- `mdd confluence sync` records the page in the run summary as
  "skipped: managed elsewhere" and continues with other pages.
  Sync exits 0 if nothing else failed (a managed page being
  skipped is the expected steady state, not an error).
- The run summary at the end of sync explicitly groups managed-
  page skips:

  ```
  Skipped (managed elsewhere):
    - 23 pages from docs-pipeline
    - 4 pages from technical-documentation
  ```

## Other systems we may want to anticipate

The two above are the ones we inspected; others exist in any
sizeable Confluence tenant. The config schema should make it
trivial to add more without code changes. Plausible future entries:

- **Internal wiki bots** (HR, finance, legal automations).
- **Doc-generation pipelines** for tools that publish status
  pages.
- **External integrations** (Jira → Confluence sync, git forge
  pages → Confluence).

The `external_publishers` list is the right shape for this:
declarative, multi-fingerprint per entry, no code changes per
new system.

## Where the config lives

Two reasonable places, with different sharing properties:

1. **In the user's per-tool config**:
   `configs/confluence.yaml` (committed in the user's local
   config repo or similar). Per-user but easy to share via
   that repo.
2. **In a shared config** committed to the `mdd` repo itself
   (e.g. `configs/external-publishers.yaml`), so the pattern
   library is canonical and grows over time. New entries get
   PR-reviewed; everyone benefits.

Recommendation: **option 2 for the global pattern library**
(canonical fingerprints for known systems), with **option 1
overrides** for per-user tweaks. Same pattern as the spec 007
blacklist + the spec 010 SharePoint repo mapping.

## Refinements worth pursuing later

- **Auto-discover external publisher account IDs** by analysing
  recent versions of pages in a space. If 80% of pages in a space
  were last edited by the same `accountId`, surface that as a
  candidate `external_publisher` entry. Useful for onboarding new
  spaces.
- **Auto-generate the body-marker patterns** by sampling a few
  pages and extracting common footer / header strings. Same idea.
- **Periodic re-check**: pages can change ownership over time. If
  a page that *was* managed becomes human-edited (publisher hands
  off control), the detection should reflect that. Probably falls
  out naturally — version.authorId moves off the bot — but worth
  testing.
- **Markdown-side "edit source" prompt**: when a user opens a
  managed-page markdown file in their IDE, an `mdd` LSP or hook
  could pop a banner reminding them to edit upstream. Out of
  scope for v1.

## Open questions for the implementation spec

1. **Default detection strictness.** Default to "fail closed"
   (refuse push if any signal matches) or "fail open" (push but
   warn)? Recommend fail closed; safer.
2. **Are there managed-but-still-mdd-pushable pages?** I.e. cases
   where mdd should be the canonical pusher but a body marker
   exists from a prior tool. Probably yes; need a per-page
   override frontmatter flag (`mdd_managed_override: true`) for
   migration scenarios.
3. **Does spec 014's `--push-edits` (proposed in research 003's
   bidirectional model)** also gate on managed-page detection?
   Yes — managed detection is symmetric with the spec 014
   conflict-skip behaviour.
4. **How does spec 016's office attachment publishing
   (publish_office) interact with managed pages?** Probably
   refuse: don't upload an office attachment to a sphinx-managed
   page, since the next publish run would either ignore it or
   overwrite. Aligns with the broader "don't write to managed
   pages" rule.
5. **Detecting unrestricted pages within a managed space.**
   Sometimes a single page in a managed space is meant to be
   human-editable (e.g. a community-contributed appendix).
   Per-page override flag is enough; no need for fancier rules.
6. **`mdd confluence whoami` helper.** Useful one-liner to print
   the user's `accountId` and (optionally) the configured
   external publishers' IDs side by side. Cheap to add.

## Useful references

- Spec 007 — confidentiality blacklist (similar shape, different
  purpose)
- Spec 009 — Confluence command (current update push semantics)
- Spec 014 — Confluence sync (where the new check belongs)
- `sphinxcontrib-confluencebuilder`:
  <https://sphinxcontrib-confluencebuilder.readthedocs.io/>
- Confluence v2 page metadata (author, version):
  <https://developer.atlassian.com/cloud/confluence/rest/v2/api-group-page/>
- Confluence v1 page restrictions:
  <https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content-restrictions/>
