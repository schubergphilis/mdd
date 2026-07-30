"""JSON serialization for the IR.

Four invariants hold:

1. `from_json(to_json(d)) == d` for every valid IR.
2. The top-level dict carries `mdd_ir_version: int` (see
   ``MDD_IR_VERSION`` below);
   loaders refuse unknown major versions with a `ValidationError`.
3. Stable key order — output keys are sorted so `git diff` on the
   on-disk sidecar is sensible.
4. Human-readable — two-space indent, `ensure_ascii=False`.

The schema is intentionally verbose (`{"type": "Heading", ...}`)
so the JSON form is useful as a diff target outside of Python.
"""

from __future__ import annotations

import base64
import json
from dataclasses import MISSING, Field, fields, is_dataclass
from typing import TYPE_CHECKING, Any, cast

from .document import Document
from .errors import FallbackEmitted, ValidationError
from .nodes import ALL_CLASSES, Origin

if TYPE_CHECKING:
    from collections.abc import Callable

MDD_IR_VERSION = 2

_DOCUMENT_FIELDS = {f.name for f in fields(Document)}
_FALLBACK_FIELDS = {f.name for f in fields(FallbackEmitted)}

# JSON-compatible plain-Python value tree.
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def _origin_to_dict(origin: Origin) -> dict[str, JsonValue]:
    """Serialize an ``Origin`` with special handling for ``raw_bytes`` and ``entity_form``.

    Empty fields are omitted entirely: `Origin` is omitted when null and
    individual fields stay terse when empty, to keep the sidecar JSON well
    under the 10× source-markdown size gate.
    """
    out: dict[str, JsonValue] = {
        "type": "Origin",
        "source_format": origin.source_format,
    }
    if origin.leading_ws:
        out["leading_ws"] = origin.leading_ws
    if origin.trailing_ws:
        out["trailing_ws"] = origin.trailing_ws
    if origin.raw_bytes:
        out["raw_bytes"] = {"@base64": base64.b64encode(origin.raw_bytes).decode("ascii")}
    if origin.raw_bytes_truncated:
        out["raw_bytes_truncated"] = True
    if origin.entity_form:
        pairs: list[JsonValue] = [
            [offset, entity]  # type: ignore[list-item]
            for offset, entity in sorted(origin.entity_form.items())
        ]
        out["entity_form"] = pairs
    return out


def _str_or(data: dict[str, JsonValue], key: str, default: str) -> str:
    """Return ``data[key]`` if it is a string, else *default*.

    Both for-input-validation (the JSON came from an external file) and
    type-narrowing (callers want a `str`, not `JsonValue`).
    """
    value = data.get(key, default)
    return value if isinstance(value, str) else default


def _decode_base64_field(data: dict[str, JsonValue], key: str) -> bytes:
    """Decode a ``{key: {"@base64": "..."}}`` value, or return ``b""``."""
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        return b""
    b64 = raw.get("@base64", "")
    if not isinstance(b64, str) or not b64:
        return b""
    return base64.b64decode(b64)


def _decode_entity_form(data: dict[str, JsonValue]) -> dict[int, str]:
    """Decode the ``entity_form`` pair-list back into ``{offset: entity}``."""
    raw = data.get("entity_form", [])
    if not isinstance(raw, list):
        return {}
    out: dict[int, str] = {}
    for pair in raw:
        if not (isinstance(pair, list) and len(pair) == 2):
            continue
        offset_raw, entity_raw = pair
        if isinstance(offset_raw, (int, float)) and isinstance(entity_raw, str):
            out[int(offset_raw)] = entity_raw
    return out


def _origin_from_dict(data: dict[str, JsonValue]) -> Origin:
    """Deserialize an ``Origin`` from its JSON form."""
    return Origin(
        source_format=_str_or(data, "source_format", "confluence-storage"),  # pyright: ignore[reportArgumentType]
        raw_bytes=_decode_base64_field(data, "raw_bytes"),
        leading_ws=_str_or(data, "leading_ws", ""),
        trailing_ws=_str_or(data, "trailing_ws", ""),
        entity_form=_decode_entity_form(data),
        raw_bytes_truncated=bool(data.get("raw_bytes_truncated", False)),
    )


def _is_field_default(f: Field[Any], val: object) -> bool:
    """True iff *val* equals the dataclass-declared default for field *f*.

    Fields with no declared default are required and never match — they are
    always emitted.
    """
    if f.default is not MISSING:
        return val == f.default
    if f.default_factory is not MISSING:
        return val == f.default_factory()
    return False


def _dataclass_to_dict(node: object) -> dict[str, JsonValue]:
    """Serialize a dataclass node, omitting fields equal to their declared default.

    The dataclass default is the round-trip contract: `from_dict` restores
    omitted fields from the same defaults, so equality is preserved by
    construction. Compaction is what keeps
    the benchmark gate's 10× sidecar-size ratio reachable on real content.
    """
    out: dict[str, JsonValue] = {"type": type(node).__name__}
    for f in fields(node):  # pyright: ignore[reportArgumentType]
        val = getattr(node, f.name)
        if _is_field_default(f, val):
            continue
        out[f.name] = to_dict(val)
    return out


def to_dict(node: object) -> JsonValue:  # noqa: PLR0911
    """Serialize an IR node (or list / dict / primitive) to plain JSON data."""
    if isinstance(node, Origin):
        return _origin_to_dict(node)
    if isinstance(node, list):
        return [to_dict(x) for x in cast("list[object]", node)]
    if isinstance(node, tuple):
        return [to_dict(x) for x in cast("tuple[object, ...]", node)]
    if isinstance(node, dict):
        return {str(k): to_dict(v) for k, v in cast("dict[object, object]", node).items()}
    if is_dataclass(node) and not isinstance(node, type):
        return _dataclass_to_dict(node)
    if node is None or isinstance(node, (bool, int, float, str)):
        return node
    if isinstance(node, bytes):
        return {"@base64": base64.b64encode(node).decode("ascii")}
    raise ValidationError(f"cannot serialize {type(node).__name__} to JSON")


def _node_from_typed_dict(data: dict[str, JsonValue]) -> object:
    """Decode a `{"type": "<Name>", ...}` envelope to its dataclass instance."""
    type_name = data["type"]
    if not isinstance(type_name, str):
        raise ValidationError(f"invalid IR JSON: non-string 'type' {type_name!r}")
    special = _SPECIAL_FROM_DICT.get(type_name)
    if special is not None:
        return special(data)
    cls = ALL_CLASSES.get(type_name)
    if cls is None:
        raise ValidationError(f"unknown IR node type: {type_name!r}")
    kwargs: dict[str, object] = {
        f.name: from_dict(data[f.name]) for f in fields(cls) if f.name in data
    }
    # `origin` absent → None (preserving-mode sidecar compat).
    return cls(**kwargs)


def _maybe_decode_base64_dict(data: dict[str, JsonValue]) -> bytes | None:
    """Return decoded bytes for a bare ``{"@base64": "..."}`` dict, else None."""
    if "@base64" not in data or len(data) != 1:
        return None
    b64_val = data["@base64"]
    if not isinstance(b64_val, str):
        return None
    return base64.b64decode(b64_val)


def from_dict(data: JsonValue) -> object:
    """Inverse of `to_dict`. Raises `ValidationError` on unknown types."""
    if isinstance(data, list):
        return [from_dict(x) for x in data]
    if isinstance(data, dict):
        if "type" in data:
            return _node_from_typed_dict(data)
        decoded = _maybe_decode_base64_dict(data)
        if decoded is not None:
            return decoded
    return data


def _document_from_dict(data: dict[str, JsonValue]) -> Document:
    kwargs: dict[str, object] = {}
    for name in _DOCUMENT_FIELDS:
        if name in data:
            kwargs[name] = from_dict(data[name])
    return Document(**kwargs)  # pyright: ignore[reportArgumentType]


def _fallback_from_dict(data: dict[str, JsonValue]) -> FallbackEmitted:
    kwargs: dict[str, object] = {}
    for name in _FALLBACK_FIELDS:
        if name in data:
            value: object = from_dict(data[name])
            if name == "path" and isinstance(value, list):
                value = tuple(cast("list[object]", value))
            kwargs[name] = value
    return FallbackEmitted(**kwargs)  # pyright: ignore[reportArgumentType]


# Type names that need a hand-rolled constructor — either because the class
# isn't in ALL_CLASSES (Document, FallbackEmitted) or because its fields
# require post-processing the generic dataclass loader can't perform (Origin's
# base64 + entity_form codecs). Everything else goes through the generic
# field-loop in `_node_from_typed_dict`.
_SPECIAL_FROM_DICT: dict[str, Callable[[dict[str, JsonValue]], object]] = {
    "Document": _document_from_dict,
    "FallbackEmitted": _fallback_from_dict,
    "Origin": _origin_from_dict,
}


def to_json(doc: Document, *, indent: int = 2) -> str:
    """Canonical JSON form. Stable across runs (keys sorted)."""
    payload: dict[str, JsonValue] = {
        "mdd_ir_version": MDD_IR_VERSION,
        "root": _document_to_dict(doc),
    }
    return json.dumps(payload, indent=indent, sort_keys=True, ensure_ascii=False)


def _document_to_dict(doc: Document) -> dict[str, JsonValue]:
    out: dict[str, JsonValue] = {"type": "Document"}
    for f in fields(doc):
        out[f.name] = to_dict(getattr(doc, f.name))
    return out


def from_json(text: str) -> Document:
    """Inverse of `to_json`. Refuses unknown schema versions."""
    try:
        raw: Any = json.loads(text)  # pyright: ignore[reportExplicitAny]
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid IR JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValidationError("invalid IR JSON: top-level value is not an object")
    payload = cast("dict[str, JsonValue]", raw)
    if "mdd_ir_version" not in payload:
        raise ValidationError("invalid IR JSON: missing 'mdd_ir_version'")
    version = payload["mdd_ir_version"]
    if version != MDD_IR_VERSION:
        raise ValidationError(
            f"unsupported mdd_ir_version: {version!r} (this build expects {MDD_IR_VERSION})"
        )
    if "root" not in payload:
        raise ValidationError("invalid IR JSON: missing 'root'")
    doc = from_dict(payload["root"])
    if not isinstance(doc, Document):
        raise ValidationError(f"invalid IR JSON: 'root' is not a Document but {type(doc).__name__}")
    return doc
