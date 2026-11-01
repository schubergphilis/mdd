"""Read a file's front matter the way the sync readers see it.

The prose runner reads files with ``newline=""`` so a writer can keep the
file's line endings. The sync readers use ``read_text()``, which turns CRLF
and CR-only line endings into LF. The mirror guard and the freshness check
must see the same front matter the sync does, so they normalise the line
endings, and drop a leading byte order mark, before splitting.

Front matter that is there but cannot be read is reported as such, not as
"no front matter": the mirror guard has to refuse such a file rather than
assume it is authored content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mdd.utils.frontmatter import parse_yaml_mapping, split_frontmatter

if TYPE_CHECKING:
    from collections.abc import Mapping

_BOM = "\ufeff"
_FENCE = "---"


@dataclass(frozen=True)
class FrontMatter:
    """What a file's front matter holds.

    ``present`` is False when the file does not open with a ``---`` line.
    ``mapping`` is ``None`` when the block is there but is not a readable YAML
    mapping; an empty block reads as an empty mapping.
    """

    present: bool
    mapping: Mapping[str, object] | None

    @property
    def malformed(self) -> bool:
        """True when a front matter block is there but could not be read."""
        return self.present and self.mapping is None


def normalise(text: str) -> str:
    """Return *text* without a leading BOM and with every line ending as LF."""
    return text.removeprefix(_BOM).replace("\r\n", "\n").replace("\r", "\n")


def read(text: str) -> FrontMatter:
    """Read the front matter of *text*, whatever its line endings."""
    normal = normalise(text)
    lines = normal.split("\n", 2)
    if lines[0].rstrip(" \t") != _FENCE:
        return FrontMatter(present=False, mapping=None)
    if len(lines) > 1 and lines[1].rstrip(" \t") == _FENCE:
        return FrontMatter(present=True, mapping={})
    split = split_frontmatter(normal)
    if split is None:
        return FrontMatter(present=True, mapping=None)
    block = split[0]
    if not block.strip():
        return FrontMatter(present=True, mapping={})
    return FrontMatter(present=True, mapping=parse_yaml_mapping(block))
