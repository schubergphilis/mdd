"""Finding punctuation beside a closing quote, and telling literal quotes from prose."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mdd.prose.classify import Line
    from mdd.prose.config import LintConfig

_QUOTES = "\"'“”‘’"
_LITERAL_PREFIXES = ("-", "--", "/", "$", "<")


def quoted_interior(text: str, quote_at: int, quote: str) -> str | None:
    """Return the interior of the quoted span closing at *quote_at*, or ``None``."""
    opener = text.rfind(quote, 0, quote_at)
    if quote in "”’":
        opener = text.rfind("“" if quote == "”" else "‘", 0, quote_at)
    if opener == -1:
        return None
    return text[opener + 1 : quote_at]


def looks_literal(interior: str | None, config: LintConfig) -> bool:
    """True when a quoted span looks like a literal rather than like prose.

    Deliberately conservative: a false skip loses a finding, a false flag
    corrupts text.
    """
    if interior is None:
        return True
    if not interior or not interior.strip():
        return True
    if " " not in interior and "\t" not in interior:
        return True
    if interior.startswith(_LITERAL_PREFIXES):
        return True
    return any(pattern.search(interior) for pattern in config.literal_quote_patterns)


def quote_candidates(line: Line, config: LintConfig) -> Iterable[tuple[int, int]]:
    """Yield ``(quote_index, mark_index)`` pairs the configured convention rejects."""
    if config.quote_punctuation == "off":
        return
    inside = config.quote_punctuation == "inside"
    for index in range(len(line.text) - 1):
        first, second = line.text[index], line.text[index + 1]
        if inside and first in _QUOTES and second in ",.":
            yield index, index + 1
        elif not inside and first in ",." and second in _QUOTES:
            yield index + 1, index
