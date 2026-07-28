"""Errors and events for the IR layer.

`IRError` is the base for anything raised by the IR layer.
`ValidationError` is raised by `serialize.from_json` on malformed
payloads or unknown schema versions. `FallbackEmitted` is *not* an
exception — it is a structured event surfaced through `IRContext`
when a reader had to fall back to `RawBlock` / `RawInline`. See
[spec S28](../../../docs/spec/S28-document-ir-foundation.md)
section "Fallback contract".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


class IRError(Exception):
    """Base class for IR-layer errors."""


class ValidationError(IRError):
    """Raised by `from_json` for malformed payloads or unknown versions."""


@dataclass(frozen=True)
class FallbackEmitted:
    """Event emitted whenever a reader produces a `RawBlock` / `RawInline`.

    Carried on `Document.fallbacks` so callers can surface fidelity loss
    without parsing the IR a second time. The IR layer itself never
    inspects this list; it's purely informational.
    """

    kind: Literal["block", "inline"]
    source_format: str
    reason: str
    content_preview: str = ""
    path: tuple[str, ...] = field(default_factory=tuple)
