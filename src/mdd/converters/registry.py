"""registry.py — CONVERTERS and REVERSE_CONVERTERS dicts plus lookup helpers."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from mdd.converters.protocol import Converter, ReverseConverter

# Keyed by lowercased extension with leading dot, e.g. ".docx".
CONVERTERS: dict[str, Converter] = {}

# Keyed by lowercased target extension, e.g. ".docx".
# Populated by spec S17 (Quarto reverse converters).
REVERSE_CONVERTERS: dict[str, ReverseConverter] = {}


def register(converter: Converter) -> None:
    """Register *converter* for each of its declared extensions.

    Raises ValueError if any extension is already registered.
    """
    for ext in converter.extensions:
        if ext in CONVERTERS:
            raise ValueError(
                f"Extension {ext!r} is already registered to "
                f"{type(CONVERTERS[ext]).__name__!r}; "
                f"cannot register {type(converter).__name__!r}"
            )
        CONVERTERS[ext] = converter


def register_reverse(reverse_converter: ReverseConverter) -> None:
    """Register *reverse_converter* for its declared target extension.

    Raises ValueError if that extension is already registered.
    """
    ext = reverse_converter.target_extension
    if ext in REVERSE_CONVERTERS:
        raise ValueError(
            f"Target extension {ext!r} is already registered to "
            f"{type(REVERSE_CONVERTERS[ext]).__name__!r}; "
            f"cannot register {type(reverse_converter).__name__!r}"
        )
    REVERSE_CONVERTERS[ext] = reverse_converter


def converter_for(path: Path) -> Converter | None:
    """Return the Converter for *path*'s extension, or None if unknown.

    The lookup is case-insensitive on the path's extension; keys in
    CONVERTERS are always lowercase with a leading dot.
    """
    return CONVERTERS.get(path.suffix.lower())


def reverse_for(target_extension: str) -> ReverseConverter | None:
    """Return the ReverseConverter for *target_extension*, or None if unknown."""
    return REVERSE_CONVERTERS.get(target_extension.lower())
