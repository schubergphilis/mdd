# S40: Typed frontmatter layer

**Purpose:** Replace the ~5 per-module, hand-rolled YAML/JSON coercer kits in `mdd` with a single typed layer built on pydantic v2 models. Deletes a class of silent-failure bugs (typos in hand-edited frontmatter keys are silently ignored today), removes ~100 `# pyright: ignore[reportAny]` suppressions, and gives every consumer of frontmatter / API JSON / config files the same idiom for going from raw text to a fully typed value.

**Status:** Implemented (2026-05-24)

## Introduction

Several modules in `mdd` independently re-invent the same three-step pattern when reading YAML or JSON:

1. Decode raw text into a generic `Any` (`yaml.safe_load`, `json.loads`, `response.json()`).
2. Manually check `isinstance(parsed, dict)` and bail to a default on the negative branch.
3. Pull individual fields out with hand-rolled coercers (`_str_field`, `_int_field`, `_str_list_field`, `dict_field`, …) that each silently substitute a default when the value has the wrong shape.

Today this pattern is implemented at least five times across the codebase:

- [`src/mdd/confluence/_yaml_coerce.py`](../../src/mdd/confluence/_yaml_coerce.py) — **value-taking** helpers (`str_field`, `int_field`, `str_list`, `dict_list`, `bool_field`, `str_or_none_field`).
- [`src/mdd/confluence/managed/config.py`](../../src/mdd/confluence/managed/config.py) — a **second**, **dict+key-taking** set (`_str_field(d, key)`, `_str_list_field(d, key)`, `dict_field(d, key)`, `_iter_dicts(d, key)`) used by the externally-managed-publishers config loader. So confluence already has two parallel coercer sets with different signatures.
- [`src/mdd/lucid/state.py`](../../src/mdd/lucid/state.py) — private `_str_field` / `_int_field` for Lucid's `<title>.json` API responses.
- [`src/mdd/converters/svg.py`](../../src/mdd/converters/svg.py) — `_load_svg_block` reads YAML and picks the top-level `svg` key.
- [`src/mdd/ai/cache.py`](../../src/mdd/ai/cache.py) — `_read_entry` reads a JSON cache envelope inline.

The SharePoint sync stack repeats the surrounding boilerplate eight times (`split_frontmatter` + `yaml.safe_load` + `isinstance(parsed, dict)` + `dict(cast(...))`) without a shared helper at all.

### Why this is more than a cleanup

The hand-rolled coercers don't just produce duplicate code — they make **silent failures the default**. Concrete failure modes that exist today:

- A user hand-edits a Confluence markdown file and writes `spcae_key: ENG` (typo). `_local_page_from_conf` looks up `conf.get("space_key")` (the correct key), gets `None`, `_is_publish_candidate` returns `False`, and the page mysteriously fails to sync. There is no warning anywhere in the logs that the typo'd key was seen and ignored.
- A user writes `attachments_skipped: yes` in frontmatter (a YAML 1.1 truthy). `bool_field` returns `False` because the parsed value is the string `"yes"`, not a real bool. The page resyncs every attachment forever.
- A Confluence v2 API response changes shape (e.g. `parentId` becomes nested under `parent.id`). Every per-module reader silently falls back to `None`; no error surfaces.

These bugs are individually small but they are **invisible**. A typed layer with strict unknown-key handling converts each of them from "silent corruption" to a loud `ValidationError` with a path into the offending document.

## Requirements

### Library choice: pydantic v2

The frontmatter layer is built on **pydantic v2** `BaseModel` subclasses.

- pydantic v2 is **already installed** in this repository as a transitive dependency of `openai`, `docling`, and other ML/LLM packages (`uv.lock:1508` pins `pydantic==2.13.4`, with `pydantic-core` and `pydantic-settings` also locked). Adding it as a direct `pyproject.toml` dependency has **zero install cost**.
- pydantic is the de-facto standard for typed data modelling in modern Python. The on-ramp for a new contributor is effectively zero — the codebase gains no new framework to learn beyond what every Python developer already knows.
- pydantic v2 cleanly separates the **two** strictness axes that matter for YAML coming out of a user's text editor (see [Strictness posture](#strictness-posture)).

Other libraries considered and rejected for this iteration:

- **msgspec** — strictly stricter, faster, smaller, and has a built-in YAML decoder. The leading non-pydantic candidate. Rejected for v1 on three grounds: (1) it would be a new direct dep with no transitive presence in the lock file; (2) it has a much smaller user base, so the bus-factor and the per-contributor onboarding cost are both higher; (3) the rough edges in msgspec's defaults (strict-by-default type coercion is the wrong posture for hand-edited YAML, see below) cost as much to work around as pydantic's per-class config. A re-evaluation of this decision is tracked as a separate post-Sep-2026 follow-up, by which time msgspec's ecosystem maturity should be clearer and the pydantic adoption in this repo will have settled.
- **`TypedDict` + `TypeIs` guards** (stdlib only, PEP 742) — gives static narrowing but **zero runtime validation**, so the silent-failure bug class above stays unchanged. The whole point of S40 is killing those bugs, not just satisfying pyright.
- **Lightweight value-taking coercers** (the original P03 first-pass recommendation) — minimum-churn but again only rearranges the `Any`; the silent-failure behaviour stays.
- **Code generation from JSON Schema** (`datamodel-code-generator`) — overkill for ~10 frontmatter shapes that are all owned in-house. The output target would have been pydantic models in any case.

### Strictness posture

YAML coercion failure modes split into two **separable** axes. The layer treats them differently:

- **Type coercion: flexible (pydantic v2 default).** A user who writes `version: "5"` (string) when the schema expects `version: 5` (int) gets the int they meant. YAML is stringly-typed in user heads; failing on missing quotes is the wrong cliff to fall off, and pydantic v2's default (lax) type coercion is the right posture for hand-edited frontmatter. Models MUST NOT use `StrictInt` / `StrictBool` / `StrictStr` for frontmatter fields, and MUST NOT set `ConfigDict(strict=True)`.
- **Unknown keys: strict (`ConfigDict(extra="forbid")`).** A user who writes `spcae_key: ENG` (typo) gets a `ValidationError` naming the offending key. Every frontmatter / API / config model in this layer MUST set `model_config = ConfigDict(extra="forbid")`.

These two settings are independent. Setting `extra="forbid"` does not change type-coercion behaviour. Combining flexible type coercion with strict extras is the canonical pydantic-for-YAML recipe in projects that consume hand-edited config.

### Public API

The new module is `src/mdd/utils/frontmatter.py`. Its public surface is intentionally small:

- A **base class** — `class FrontmatterModel(BaseModel)` — that sets `model_config = ConfigDict(extra="forbid")` once. Every concrete model in the layer subclasses `FrontmatterModel` and inherits the strict-extras config; concrete models do not respecify it.
- A **YAML decode helper** — `parse_yaml_mapping(text: str) -> Mapping[str, object] | None` — that handles the four "decoded into something that wasn't a mapping" cases (None, list, scalar, parse error) uniformly. Returns `None` on all of them rather than raising; callers decide whether a missing/non-mapping frontmatter is a soft "no metadata" or a hard error.
- A **`---`-delimited frontmatter splitter** — `split_frontmatter(text: str) -> tuple[str, str] | None` — that returns `(yaml_block, body)` or `None` when the text doesn't open with `---`. This consolidates the eight near-identical implementations currently in `src/mdd/sharepoint/diff.py`, `src/mdd/sharepoint/export.py`, `src/mdd/sharepoint/apply/sync_block.py`, `src/mdd/sharepoint/apply/actions.py`, and `src/mdd/confluence/state.py`.
- A **JSON load helper** — `parse_json_mapping(text: str) -> Mapping[str, object] | None` — symmetric to `parse_yaml_mapping` for the API-response and on-disk-cache call sites.

Concrete models live with their domain — `src/mdd/confluence/models.py` for Confluence frontmatter, `src/mdd/lucid/models.py` for Lucid `DocMeta`, etc. — and import `FrontmatterModel` from `mdd.utils.frontmatter`. This keeps each model close to the code that uses it and avoids growing a centralised "all models" file.

### Concrete model coverage (v1 scope)

The first wave of S40 work adds models for the densest shapes:

1. **`ConfluenceFrontmatter`** — the `confluence:` block in `.md` files: `space_key`, `space_id`, `page_id`, `parent_id`, `title`, `status`, `version`, `labels`, `attachments`, `attachments_skipped`. Replaces the dual `_yaml_coerce` + `_str_field` reader sets in `confluence/state.py`, `confluence/mutate.py`, and `confluence/create.py`.
2. **`ExternalPublishersConfig`** and its sub-models — `PublisherEntry`, `ManagedSpaceEntry`, `ManagedSubtreeEntry` (these dataclasses already exist in `confluence/managed/config.py`; they migrate to `BaseModel` and the parser collapses to a single `model_validate` call).
3. **`SharepointSync`** — the `sharepoint.sync` block from `sharepoint/diff.py`. The repeated `split_frontmatter` + `dict(cast(...))` envelope in the sharepoint stack collapses into a single helper call.
4. **`LucidDocMeta`** — replaces the dataclass in `lucid/state.py`. The `<title>.json` JSON envelope is validated end-to-end on parse.
5. **`SvgConfig`** — replaces `_load_svg_block` in `converters/svg.py`.
6. **`AICacheEntry`** — replaces `_read_entry` in `ai/cache.py`.

Out of scope for v1 (see [Out of scope](#out-of-scope)): emit-only paths (`convert/pdf.py`, `convert/pptx.py`) which just dump a `dict[str, object]` to YAML; raw Confluence v2 API response models (separate effort, larger surface).

### Error handling

When `model_validate` raises `ValidationError`:

- For **frontmatter readers** consuming a user-edited file, the caller MUST log the `ValidationError` with the file path and treat the file as "no parseable metadata" (the same outcome as today's `isinstance` fallthrough), so a single corrupt file does not crash an entire sync. The classification used today (`state.manual.append(md_path)` in `confluence/state.py`, equivalent in sharepoint) MUST also fire — these files keep their existing "untracked" handling.
- For **API response readers**, the caller MUST propagate the `ValidationError` outward. An unexpected API shape is a real bug, not a soft fallback case.
- For **config files** loaded once at startup (e.g. `external-publishers.yaml`, `~/.config/mdd/config.yaml`), the caller MUST propagate the `ValidationError` outward. A broken config should fail the command, not silently fall back to defaults.

Each consumer surfaces `ValidationError`s in its existing error-reporting convention (stderr line in CLI commands; raised exception in library code).

### No `# pyright: ignore[reportAny]` allowed in migrated code

A migrated module MUST NOT carry `# pyright: ignore[reportAny]` or `# pyright: ignore[reportUnknownVariableType]` suppressions on lines that the new layer covers. The point of S40 is precisely to delete those. Existing suppressions on un-migrated lines (third-party API responses elsewhere in the module, `argparse.Namespace` accesses tracked by issue #126, etc.) are left untouched.

### Coexistence during migration

The migration touches five modules; each is one MR. During the rollout:

- The new `mdd.utils.frontmatter` module and `mdd.confluence.models.ConfluenceFrontmatter` land in MR 1 together with the confluence migration. The old `_yaml_coerce.py` is deleted in the same MR — there is no parallel coexistence window inside confluence.
- Other modules (`sharepoint`, `lucid`, `converters/svg`, `ai/cache`) keep their existing private helpers until their own migration MR lands. The new module is additive at first; it doesn't break anything until each consumer opts in.
- Once a module migrates, its private helpers (`_str_field`, `_int_field`, …) are deleted in the same MR. No deprecation aliases, no re-exports — per the repo's no-back-compat-before-1.0 stance.

## Design Approach

**Pick pydantic for boring infrastructure reasons.** It's already installed transitively, it's the broadly-known typed-data library in Python, and msgspec's advantages (speed, smaller dep, builtin YAML) don't outweigh the familiarity and "already there" arguments for *this* codebase. The msgspec re-eval is filed for later; if msgspec's adoption curve continues upward it can swap in with a localised refactor — `FrontmatterModel` is the only seam every concrete model goes through.

**Split the strictness axes.** Strict-by-default type coercion is the wrong posture for YAML in user editors; flexible-by-default unknown keys is the wrong posture for catching typos in user-authored config. pydantic v2 lets these two axes be set independently, and the right combination is well-trodden in the pydantic-for-config ecosystem. Bundling both together (msgspec's default) trades one bug class for another.

**One small `utils/` module, concrete models in their domain.** The shared layer is small enough to live in a single file (`mdd/utils/frontmatter.py`); the concrete models are big enough that putting them all in one place would create cross-domain noise. Putting `ConfluenceFrontmatter` next to the confluence pull/push code keeps the domain knowledge co-located.

**Migrate confluence first; it's the densest and most painful module.** Confluence already has TWO parallel coercer kits — collapsing them is a measurable LoC reduction independent of anything S40 does elsewhere. It also has the most safety-critical surface (page IDs, parent IDs, version numbers) where strict validation is most useful.

**Delete the old helpers; do not re-export.** Consistent with this repository's pre-1.0 refactor-mercilessly posture. Concrete models replace the helpers entirely in their domain; un-migrated modules keep their old helpers verbatim until their own MR.

**Co-locate `split_frontmatter` in the new utility module.** The eight near-identical reimplementations are duplication for no reason. Hoisting it into `mdd/utils/frontmatter.py` and switching callers to import from there is a free win delivered alongside the typed models.

## Implementation Notes

### Sketch of `mdd/utils/frontmatter.py`

```python
"""Typed frontmatter / config / JSON parsing layer (spec S40)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict


class FrontmatterModel(BaseModel):
    """Base class for every typed frontmatter / config / API-payload model.

    Sets ``extra="forbid"`` so unknown keys raise loudly. Leaves type
    coercion at pydantic v2's lax default so ``version: "5"`` still
    decodes into ``int`` for users who quoted the value in YAML.
    """

    model_config = ConfigDict(extra="forbid")


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return ``(yaml_block, body)`` if *text* opens with ``---``, else ``None``."""
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    end = rest.find("\n---\n")
    if end == -1:
        # Tolerate trailing ``---`` without the newline (some Confluence exports).
        end = rest.find("\n---")
        if end == -1 or rest[end + 4 :].strip():
            return None
        return rest[:end], ""
    return rest[:end], rest[end + 5 :]


def parse_yaml_mapping(text: str) -> Mapping[str, object] | None:
    """Decode YAML text into a mapping, or ``None`` if it isn't one.

    Returns ``None`` on: empty text, parse error, decoded ``None``,
    decoded list, decoded scalar. Callers that want a hard error on
    "expected a mapping" should validate the return and raise.
    """
    if not text.strip():
        return None
    try:
        parsed: Any = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed  # already a dict[str, object] in practice


def parse_json_mapping(text: str) -> Mapping[str, object] | None:
    """Decode JSON text into a mapping, or ``None`` if it isn't one."""
    try:
        parsed: Any = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed
```

### Sketch of `mdd/confluence/models.py`

```python
from __future__ import annotations

from pydantic import ConfigDict, Field

from mdd.utils.frontmatter import FrontmatterModel


class ConfluenceAttachment(FrontmatterModel):
    # Machine-written manifest data (export.py regenerates it every
    # sync) whose field set grows over time, so override to
    # extra="ignore" — an older mdd reading a newer file (or vice
    # versa) tolerates unmodelled keys instead of raising mid-sync.
    model_config = ConfigDict(extra="ignore")

    filename: str = ""
    media_type: str = ""
    size: int = 0
    sha256: str = ""
    version: int = 0
    # Converter cache (spec S16).
    converted_to: str | None = None
    converter: str | None = None
    converter_version: str | None = None


class ConfluenceBlock(FrontmatterModel):
    """The ``confluence:`` block in a markdown file's YAML frontmatter."""

    space_key: str = ""
    space_id: str = ""
    page_id: str | None = None
    parent_id: str | None = None
    title: str = ""
    status: str = "CURRENT"
    version: int = 0
    labels: list[str] = Field(default_factory=list)
    attachments: list[ConfluenceAttachment] = Field(default_factory=list)
    attachments_skipped: bool = False


class ConfluenceFrontmatter(FrontmatterModel):
    """The whole frontmatter dict (only the ``confluence:`` block is typed today)."""

    confluence: ConfluenceBlock | None = None
```

### Migration mechanics for confluence

The confluence migration MR (P07 wave 1) rewrites `confluence/state.py:_read_frontmatter` from:

```python
parsed: Any = yaml.safe_load(yaml_block)
if not isinstance(parsed, dict):
    return None
result: dict[str, Any] = dict(parsed.items())
return result, body
```

to:

```python
from pydantic import ValidationError
from mdd.confluence.models import ConfluenceFrontmatter
from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter

split = split_frontmatter(text)
if split is None:
    return None
yaml_block, body = split
mapping = parse_yaml_mapping(yaml_block)
if mapping is None:
    return None
try:
    fm = ConfluenceFrontmatter.model_validate(mapping)
except ValidationError as exc:
    log.warning("invalid frontmatter in %s: %s", md_path, exc)
    return None
return fm, body
```

Every downstream `conf.get("space_key")` call in `state.py`, `mutate.py`, and `create.py` becomes `fm.confluence.space_key` (or equivalent), and the `# pyright: ignore[reportAny]` chain on each line disappears.

### CI / quality gates

The migration MRs land under the existing CI: `mise run ci` (which runs `lint`, `typecheck`, `test`, `complexipy`). No new gates are introduced. The complexipy snapshot is expected to drop slightly as each migrated module's coercer functions disappear.

## Related upstream specs

- [000-specs](000-specs.md) — shared spec conventions.
- [S07](S07-data-protection.md) — `utils/blacklist.py` shares the `src/mdd/utils/` location; both are package-wide utilities. No functional interaction.
- [S14](S14-confluence-sync.md) — `confluence sync` is the largest consumer (densest helper kit, most fields).
- [S18](S18-sharepoint-sync.md) — sharepoint sync is the second consumer (split-frontmatter consolidation).
- S25 — `lucid sync-folder` consumes `LucidDocMeta`.
- [S26](S26-managed-elsewhere.md) — externally-managed-publishers config is one of the migrated models.
- [S34](S34-code-quality-gates.md) — strict-typing posture; no new `# pyright: ignore[reportAny]` in migrated code.

## Open questions

1. Does `ConfluenceFrontmatter` keep a permissive top-level shape (only the `confluence:` block is typed; arbitrary other top-level keys are allowed) or does it lock down to `{confluence: ...}` only? Current call sites do not consume other top-level keys, but users may legitimately add their own (e.g. for unrelated tooling). The current sketch keeps it permissive via a separate envelope model; revisit during MR 1 review with a concrete example.
2. Does the `version` field on `ConfluenceBlock` default to `0` (today's behaviour from `int_field`) or `1` (Confluence's "first version" semantic)? Today's code uses `0` as a sentinel for "unknown"; check whether anything actually depends on `0`-vs-`None` before choosing.
3. Should `parse_yaml_mapping` use C-loader (`yaml.CSafeLoader`) when available for a small speedup on large mirrors? Probably yes; defer to first MR.

## Out of scope

- **Emit-only paths.** `src/mdd/convert/pdf.py:_build_frontmatter` and `src/mdd/convert/pptx.py` write YAML from a known `dict[str, object]`; they do not coerce. No `BaseModel` is introduced for emit-only code in v1.
- **Confluence v2 API response models.** The full v2 API surface is much larger than what this spec covers; carving it up into pydantic models is a separate effort. Today's per-call-site `dict_field` / `str_field` access on API responses keeps working until that effort lands.
- **argparse Namespace adapter.** Tracked separately as P03 session D / issue #126; that work may pick pydantic too (informed by this spec's outcome) or stay with vanilla argparse.
- **Replacing the existing `dataclass` models in `mdd.ir.nodes` or similar IR-layer types.** Those are not external-data shapes and have different design constraints.
- **Migrating un-listed shapes** that occasionally surface (e.g. ad-hoc JSON dumps in tests). The v1 scope is the six models listed in [Concrete model coverage](#concrete-model-coverage-v1-scope). Other shapes migrate opportunistically when their domain is next touched.
- **Switching to msgspec.** Filed as a separate post-Sep-2026 re-evaluation issue; not part of S40.
