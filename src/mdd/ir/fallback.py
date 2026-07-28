"""Fallback contract — `RawBlock` / `RawInline` plus `IRContext`.

`RawBlock` and `RawInline` are defined in `nodes.py`. This module
re-exports them and adds:

- `IRContext` — a small mutable container readers populate with
  `FallbackEmitted` events as they fall back. Writers don't read
  it. Pass an instance into `parse_*` to surface fidelity loss to
  the caller; pass `None` (the default) if you don't care.
- `emit_block_fallback` / `emit_inline_fallback` — small helpers
  that construct the `RawBlock` / `RawInline` *and* append the
  event to the context in one call, so reader code stays readable.

Per spec S28 §"Fallback contract" the IR layer itself only defines
the mechanism. Per-format policy (which shapes count as
recognised vs. fall through) lives in the converter specs 029 and
030.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .errors import FallbackEmitted
from .nodes import RawBlock, RawInline

__all__ = [
    "FallbackEmitted",
    "IRContext",
    "RawBlock",
    "RawInline",
    "emit_block_fallback",
    "emit_inline_fallback",
]


@dataclass
class IRContext:
    """Mutable per-parse context: collects `FallbackEmitted` events.

    Not frozen — readers append to `fallbacks` as they go. The
    caller can read the list once the parse returns.
    """

    fallbacks: list[FallbackEmitted] = field(default_factory=list)

    def record(self, event: FallbackEmitted) -> None:
        self.fallbacks.append(event)


def _preview(content: str, *, limit: int = 80) -> str:
    """Trim content for the `content_preview` field on a `FallbackEmitted`."""
    flat = " ".join(content.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def emit_block_fallback(
    content: str,
    *,
    source_format: str,
    reason: str,
    ctx: IRContext | None = None,
    path: tuple[str, ...] = (),
    format_override: str | None = None,
) -> RawBlock:
    """Construct a `RawBlock` and optionally record a `FallbackEmitted`.

    `format_override` defaults to `source_format` (the most common case —
    the writer's escape hatch shape matches the reader's source).
    """
    if ctx is not None:
        ctx.record(
            FallbackEmitted(
                kind="block",
                source_format=source_format,
                reason=reason,
                content_preview=_preview(content),
                path=path,
            )
        )
    return RawBlock(content=content, format=format_override or source_format)


def emit_inline_fallback(
    content: str,
    *,
    source_format: str,
    reason: str,
    ctx: IRContext | None = None,
    path: tuple[str, ...] = (),
    format_override: str | None = None,
) -> RawInline:
    """Construct a `RawInline` and optionally record a `FallbackEmitted`."""
    if ctx is not None:
        ctx.record(
            FallbackEmitted(
                kind="inline",
                source_format=source_format,
                reason=reason,
                content_preview=_preview(content),
                path=path,
            )
        )
    return RawInline(content=content, format=format_override or source_format)


# Re-exports of literal types so converters can annotate with them.
FallbackKind = Literal["block", "inline"]
