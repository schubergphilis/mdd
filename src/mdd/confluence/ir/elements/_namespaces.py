"""Confluence storage XML namespace constants and tag sets.

Lives in its own module so every sibling can import these without
risking a circular import with the package's ``__init__.py``.
"""

from __future__ import annotations

AC = "http://atlassian.com/content"
RI = "http://atlassian.com/repository/confluence/1.0"

AC_LAYOUT = f"{{{AC}}}layout"
AC_LAYOUT_SECTION = f"{{{AC}}}layout-section"
AC_LAYOUT_CELL = f"{{{AC}}}layout-cell"
AC_STRUCTURED_MACRO = f"{{{AC}}}structured-macro"
AC_TASK_LIST = f"{{{AC}}}task-list"
AC_TASK = f"{{{AC}}}task"
AC_TASK_ID = f"{{{AC}}}task-id"
AC_TASK_STATUS = f"{{{AC}}}task-status"
AC_TASK_BODY = f"{{{AC}}}task-body"
AC_LINK = f"{{{AC}}}link"
AC_IMAGE = f"{{{AC}}}image"
AC_EMOTICON = f"{{{AC}}}emoticon"
AC_PLACEHOLDER = f"{{{AC}}}placeholder"

HEADING_TAGS: dict[str, int] = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

LAYOUT_TAGS = frozenset({AC_LAYOUT, AC_LAYOUT_SECTION, AC_LAYOUT_CELL})
