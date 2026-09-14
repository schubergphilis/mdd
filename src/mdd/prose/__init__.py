"""Deterministic, model-free prose checks and fixers over a Markdown corpus.

Every check here is a pure function of the bytes on disk plus the project's
configuration: no network, no credentials, no model. That is what makes the
group usable as a merge gate — a gate that can disagree with itself on a
rerun is a flaky test that blames the author.
"""

from __future__ import annotations
