"""Typed frontmatter / config / JSON parsing layer.

Three small parsing helpers and a base class:

- :class:`FrontmatterModel` — shared base class for every typed
  frontmatter / config / API-payload model.  Sets ``extra="forbid"``
  so unknown keys raise loudly, while leaving type coercion at
  pydantic v2's lax default so ``version: "5"`` still decodes into
  ``int`` for users who quoted the value.
- :func:`split_frontmatter` — split a markdown file's YAML frontmatter
  block from its body.
- :func:`parse_yaml_mapping` — decode YAML text into a mapping, or
  return ``None`` if the decoded value isn't one.
- :func:`parse_json_mapping` — symmetric to :func:`parse_yaml_mapping`
  for the API-response and on-disk-cache call sites.

The two parsing helpers handle all four "decoded into something that
wasn't a mapping" cases (``None``, list, scalar, parse error)
uniformly: they return ``None`` rather than raising.  Callers decide
whether a missing/non-mapping payload is a soft "no metadata" or a
hard error.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping


class FrontmatterModel(BaseModel):
    """Base class for every typed frontmatter / config / API-payload model.

    Sets ``extra="forbid"`` so unknown keys raise loudly.  Concrete
    models inherit this config; they do not respecify it.  Models that
    represent third-party API responses where unknown fields are
    legitimate (the response surface evolves) override the config to
    ``extra="ignore"`` at the model level.

    Leaves type coercion at pydantic v2's lax default so
    ``version: "5"`` still decodes into ``int`` for users who quoted
    the value in YAML.  Frontmatter models MUST NOT use
    ``StrictInt`` / ``StrictBool`` / ``StrictStr`` and MUST NOT set
    ``ConfigDict(strict=True)``.
    """

    model_config = ConfigDict(extra="forbid")


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return ``(yaml_block, body)`` if *text* opens with ``---``, else ``None``.

    Accepts both LF (``\\n---\\n``) and CRLF (``\\r\\n---\\r\\n``) line
    endings on the opening fence; the closing fence is matched as
    ``\\n---\\n`` (or a trailing ``\\n---`` at end-of-file).
    """
    if not text.startswith(("---\n", "---\r\n")):
        return None
    rest = text[4:] if text.startswith("---\n") else text[5:]
    end = rest.find("\n---\n")
    if end == -1:
        # Tolerate trailing ``---`` without the newline (some Confluence exports).
        if not rest.endswith("\n---"):
            return None
        return rest[: len(rest) - 4], ""
    return rest[:end], rest[end + 5 :]


def parse_yaml_mapping(text: str) -> Mapping[str, object] | None:
    """Decode YAML *text* into a mapping, or ``None`` if it isn't one.

    Returns ``None`` on: empty text, parse error, decoded ``None``,
    decoded list, decoded scalar.  Callers that want a hard error on
    "expected a mapping" should validate the return and raise.
    """
    if not text.strip():
        return None
    try:
        parsed: Any = yaml.safe_load(text)  # pyright: ignore[reportAny]
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed  # pyright: ignore[reportUnknownVariableType]


def parse_json_mapping(text: str) -> Mapping[str, object] | None:
    """Decode JSON *text* into a mapping, or ``None`` if it isn't one.

    Symmetric to :func:`parse_yaml_mapping`: returns ``None`` on parse
    error, empty input, decoded ``None``, decoded list, or decoded scalar.
    """
    if not text.strip():
        return None
    try:
        parsed: Any = json.loads(text)  # pyright: ignore[reportAny]
    except json.JSONDecodeError, ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed  # pyright: ignore[reportUnknownVariableType]
