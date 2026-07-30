"""Normalisation pipeline for the IR.

Each pass is a pure function ``Document -> Document``. The IR is frozen
(all dataclasses have ``frozen=True``) so every transformation uses
``dataclasses.replace`` — never in-place mutation.

The full pipeline is exposed as:

- ``NORMALISING_PIPELINE`` — a tuple of the 9 pass functions in order.
- ``normalise(doc)`` — apply the full pipeline and return the result.

Individual passes can be called in isolation for testing or for composing
custom sub-pipelines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .attrs import dedupe_attrs, sort_attrs
from .callouts import attach_callout_kind
from .entities import normalise_entities
from .lists import default_ordered_start, tighten_lists
from .whitespace import collapse_soft_breaks, drop_empty_paragraphs, normalise_whitespace

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..document import Document

__all__ = [
    "NORMALISING_PIPELINE",
    "attach_callout_kind",
    "collapse_soft_breaks",
    "dedupe_attrs",
    "default_ordered_start",
    "drop_empty_paragraphs",
    "normalise",
    "normalise_entities",
    "normalise_whitespace",
    "sort_attrs",
    "tighten_lists",
]


NORMALISING_PIPELINE: tuple[Callable[[Document], Document], ...] = (
    collapse_soft_breaks,
    tighten_lists,
    default_ordered_start,
    normalise_entities,
    normalise_whitespace,
    drop_empty_paragraphs,
    attach_callout_kind,
    dedupe_attrs,
    sort_attrs,
)


def normalise(doc: Document) -> Document:
    """Apply the full normalising pipeline to *doc* and return the result."""
    result = doc
    for pass_fn in NORMALISING_PIPELINE:
        result = pass_fn(result)
    return result
