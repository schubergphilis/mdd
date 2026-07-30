# Mutate-orchestrator test fixtures

The mutate orchestrator tests build their working trees programmatically in
``tmp_path`` (see ``tests/confluence/test_mutate.py``) rather than relying on
on-disk before/after layouts.  This keeps the fixtures lightweight and lets
us reuse the same git-init helper across tests.

If a future test grows beyond a single ``tmp_path`` working-tree (e.g. a
collision scenario with several siblings), drop the before/after Markdown
files here following the shape used by ``tests/confluence/sync/fixtures/``.
