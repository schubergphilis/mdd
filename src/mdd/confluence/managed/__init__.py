"""Detection cascade for externally-managed Confluence pages.

Provides :func:`classify_page` which evaluates five layers in priority order:

1. ``managed_spaces``  — page's space key is in configured list.
2. ``managed_subtrees`` — page's ancestor chain contains a configured root.
3. Publisher account ID — page's last-edit author is a known bot account.
4. Body marker regex  — storage XHTML matches a configured pattern.
5. Page restrictions  — current user is not in the "update" allow-list.

A match at any layer short-circuits the remaining checks.

Topic-grouped sub-modules: ``config``, ``classify``, ``headers``.
"""

from __future__ import annotations

from .classify import (
    ManagedClassification,
    ManagedReason,
    PageInfo,
    classify_page,
)
from .config import (
    ManagedConfig,
    ManagedSpaceEntry,
    ManagedSubtreeEntry,
    PublisherEntry,
    load_managed_config,
)
from .headers import build_page_info_from_page_data, managed_export_header, warn_managed

__all__ = [
    "ManagedClassification",
    "ManagedConfig",
    "ManagedReason",
    "ManagedSpaceEntry",
    "ManagedSubtreeEntry",
    "PageInfo",
    "PublisherEntry",
    "build_page_info_from_page_data",
    "classify_page",
    "load_managed_config",
    "managed_export_header",
    "warn_managed",
]
