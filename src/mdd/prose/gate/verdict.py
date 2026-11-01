"""The gate's verdict, and the reason it gives when two item streams differ."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mdd.prose.gate.stream import Item

#: Human-readable names for token types, for the reason a user is shown.
_NOUNS: dict[str, str] = {
    "blockquote": "block quote",
    "bullet_list": "bulleted list",
    "code_block": "indented code block",
    "code_inline": "code span",
    "em": "emphasis",
    "fence": "fenced code block",
    "front_matter": "front matter",
    "hardbreak": "hard line break",
    "hr": "thematic break",
    "html_block": "HTML block",
    "html_inline": "inline HTML",
    "html_literal_text": "run of preformatted HTML text",
    "math_block": "math block",
    "math_inline": "inline math",
    "ordered_list": "numbered list",
    "s": "strikethrough",
    "strong": "strong emphasis",
    "td": "table cell",
    "th": "table header cell",
    "tr": "table row",
}


@dataclass(frozen=True)
class Verdict:
    """Whether a rewrite passed the gate and, if not, where and why it failed.

    ``line`` is 1-based and counts lines of the text *before* the rewrite; it
    is ``0`` when the difference has no single position. ``reason`` is shown
    to users, so it names the construct that changed but never quotes content.
    """

    passed: bool
    line: int = 0
    reason: str = ""


PASSED = Verdict(passed=True)


def _noun(token_type: str) -> str:
    base = token_type.removesuffix("_open").removesuffix("_close")
    return _NOUNS.get(base, base.replace("_", " "))


def _noun_phrase(token_type: str) -> str:
    noun = _noun(token_type)
    article = "an" if noun.startswith(("a", "e", "i", "o", "u", "HTML")) else "a"
    return f"{article} {noun}"


def _differing_field(before: Item, after: Item) -> str:
    names = ("type", "nesting", "tag", "marker", "info string", "attributes", "hidden", "meta")
    for name, left, right in zip(names, before.key, after.key, strict=False):
        if left != right:
            return name
    return "shape"


def _hard_breaks(items: Sequence[Item]) -> int:
    return sum(item.type == "hardbreak" for item in items)


def _structural_reason(
    before: Item, after: Item, left: Sequence[Item], right: Sequence[Item]
) -> str:
    """Say how the shape of *after* differs from *before*.

    A lost hard break surfaces as a hard break lined up against whatever
    followed it, so the break count is consulted before blaming that token.
    """
    lost = _hard_breaks(left) - _hard_breaks(right)
    if lost > 0:
        return "a hard line break was lost"
    if lost < 0:
        return "a hard line break was added"
    if before.type != after.type:
        return f"{_noun_phrase(before.type)} became {_noun_phrase(after.type)}"
    field = _differing_field(before, after)
    if field == "hidden" and before.type == "paragraph_open":
        return "a tight list became loose" if before.key[6] else "a loose list became tight"
    return f"the {field} of {_noun_phrase(before.type)} changed"


def structure(left: Sequence[Item], right: Sequence[Item]) -> Verdict:
    """The first difference in shape, ignoring content."""
    for old, new in zip(left, right, strict=False):
        if old.key != new.key:
            reason = _structural_reason(old, new, left, right)
            return Verdict(passed=False, line=old.line, reason=reason)
    if len(left) > len(right):
        missing = left[len(right)]
        reason = f"{_noun_phrase(missing.type)} was removed"
        return Verdict(passed=False, line=missing.line, reason=reason)
    if len(right) > len(left):
        extra = right[len(left)]
        line = left[-1].line if left else 1
        return Verdict(passed=False, line=line, reason=f"{_noun_phrase(extra.type)} was added")
    return PASSED


def content(left: Sequence[Item], right: Sequence[Item]) -> Verdict:
    """The first difference in content, for two streams of the same shape."""
    for old, new in zip(left, right, strict=True):
        if old.literal == new.literal:
            continue
        if old.type == "text":
            reason = "the text changed by more than whitespace"
        elif old.type == "html_literal_text":
            reason = "the text inside a whitespace-preserving HTML element changed"
        else:
            reason = f"the content of {_noun_phrase(old.type)} changed"
        return Verdict(passed=False, line=old.line, reason=reason)
    return PASSED
