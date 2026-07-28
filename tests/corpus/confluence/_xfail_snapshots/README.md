# `_xfail_snapshots/` — round-trip reproducers awaiting fixes

Real-world Confluence storage snapshots whose R3 round-trip is currently
broken. Each subdirectory mirrors the `_snapshots/` layout
(`storage.xhtml`, `metadata.json`) but is consumed by a dedicated
known-failures test rather than the main R1/R2/R3 gate suites.

Each snapshot's test is marked `pytest.mark.xfail(strict=True)`. When
a fix lands and the round-trip becomes byte-perfect, the test reports
XPASS, CI fails, and the snapshot must be moved into `_snapshots/`
(where it joins the main gate).

`metadata.json` carries an `issue:` link to the GitLab issue tracking
the fix.

This directory is currently empty — there are no outstanding R3
reproducers awaiting a fix.
