"""Public dataclasses for the sync package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mdd.confluence.managed import ManagedConfig
    from mdd.utils.mddignore import MddIgnore


@dataclass
class SyncOptions:
    """Bundle of ``sync_space`` options that aren't core positional args.

    Created so the public signature stays under the PLR0913 ``max-args``
    limit. ``dry_run`` is the only frequently-used flag in tests; the rest are
    knobs for the CLI / orchestrator.
    """

    dry_run: bool = False
    no_delete: bool = False
    push: bool = False
    message: str | None = None
    head: int | None = None
    max_attachment_size_bytes: int | None = None
    managed_config: ManagedConfig | None = None
    skip_attachments: bool = False
    read_only: bool = False
    # Source-side ``.mddignore`` matcher. ``None`` (the default) disables
    # filtering entirely; sync behaviour is byte-identical to the unfiltered
    # path. When set, pages whose rel-path (built from the page-title chain
    # that produces the on-disk markdown filename) matches the matcher are
    # skipped before download. Already-tracked pages are NEVER deleted on
    # the basis of a newly-added pattern — the matcher only blocks new pulls.
    matcher: MddIgnore | None = None
    # Opt-in cleanup. When True, ``sync_space`` walks the mirror
    # tree once via ``matcher.walk_prunable`` BEFORE the normal sync and
    # deletes every file the matcher flags. Mutually exclusive with
    # ``read_only`` (the CLI rejects the combination at parse time). Under
    # ``dry_run`` the walk still runs, paths are logged, but nothing is
    # removed.
    prune_ignored: bool = False


@dataclass
class SyncSummary:
    """Counts and notes from a sync run."""

    renamed: int = 0
    moved: int = 0
    archived: int = 0
    unarchived: int = 0
    new_from_confluence: int = 0
    content_pulled: int = 0
    deleted: int = 0
    cross_space: list[str] = field(default_factory=list)
    new_pushed: int = 0
    content_pushed: int = 0
    conflicts: list[str] = field(default_factory=list)
    skipped_manual: int = 0
    skipped_attachment_derived: int = 0
    failures: list[str] = field(default_factory=list)
    head_skipped: int = 0
    committed: bool = False
    commit_sha: str = ""
    office_uploaded: int = 0
    office_cache_hits: int = 0
    # managed-elsewhere skips: {publisher_name: count}
    managed_skips: dict[str, int] = field(default_factory=dict)
    # Pages dropped by the ``.mddignore`` matcher before download.
    # ``skipped_ignored_paths`` records POSIX-style rel-paths (directories
    # carry a trailing ``/`` so dry-run output distinguishes prunes from
    # per-page skips, matching the SharePoint summary shape).
    skipped_ignored: int = 0
    skipped_ignored_paths: list[str] = field(default_factory=list)
    # Already-synced files deleted by the ``--prune-ignored``
    # flag. ``skipped`` is source-side filtering; ``pruned`` is local
    # cleanup of already-synced content; the two never overlap. Under
    # ``--dry-run`` the counter still ticks up but no file is removed
    # and ``pruned_ignored_dry_run`` flips to True so the summary log
    # switches phrasing.
    pruned_ignored: int = 0
    pruned_ignored_paths: list[str] = field(default_factory=list)
    pruned_ignored_dry_run: bool = False

    def has_changes(self) -> bool:
        return any(
            [
                self.renamed,
                self.moved,
                self.archived,
                self.unarchived,
                self.new_from_confluence,
                self.content_pulled,
                self.deleted,
                self.new_pushed,
                self.content_pushed,
                self.office_uploaded,
            ]
        )

    def _pull_parts(self) -> list[str]:
        fields: list[tuple[int, str]] = [
            (self.renamed, "renamed"),
            (self.moved, "moved"),
            (self.archived, "archived"),
            (self.unarchived, "unarchived"),
            (self.content_pulled, "content updates"),
            (self.deleted, "deleted"),
        ]
        return [f"{n} {label}" for n, label in fields if n]

    def _push_parts(self) -> list[str]:
        fields: list[tuple[int, str]] = [
            (self.new_pushed, "new pages created"),
            (self.content_pushed, "pages updated"),
        ]
        return [f"{n} {label}" for n, label in fields if n]

    def _managed_skip_lines(self) -> list[str]:
        return [
            f"  - {count} pages read-only restricted"
            if publisher == "_read_only"
            else f"  - {count} pages from {publisher}"
            for publisher, count in self.managed_skips.items()
        ]

    def format_commit_message(self, space_key: str, *, message_override: str | None = None) -> str:
        lines: list[str] = [
            message_override or f"chore(mirror): sync from Confluence space {space_key}",
            "",
        ]

        sections: list[tuple[str, list[str]]] = [
            ("Confluence → mirror:", [", ".join(self._pull_parts())] if self._pull_parts() else []),
            ("Mirror → Confluence:", [", ".join(self._push_parts())] if self._push_parts() else []),
            (
                "Skipped:",
                [f"1 conflict (local + remote both edited): {p}" for p in self.conflicts],
            ),
            ("Skipped (managed elsewhere):", self._managed_skip_lines()),
            ("Cross-space moves detected:", [f"- {note}" for note in self.cross_space]),
        ]
        for header, body in sections:
            if not body:
                continue
            lines.append(header)
            lines.extend(f"  {item}" if not item.startswith("  ") else item for item in body)
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"
