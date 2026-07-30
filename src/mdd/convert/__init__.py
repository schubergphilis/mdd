"""Input-format → Markdown helpers used by ``mdd convert`` and downstream syncs.

Exposes :class:`CorruptSourceError` as a converter-boundary signal for
source files that cannot be parsed at all (empty or non-Office-ZIP).
Callers in the SharePoint sync dispatch layer catch this and record a
soft skip instead of a hard error.
"""

from __future__ import annotations


class CorruptSourceError(Exception):
    """Raised by a converter when the source file is empty or not a valid Office package.

    Signals "no useful bytes here, give up cleanly" to the dispatcher.
    Distinct from generic conversion errors so the dispatch layer can
    route to a soft-skip counter rather than the hard-error counter.
    """


__all__ = ["CorruptSourceError"]
