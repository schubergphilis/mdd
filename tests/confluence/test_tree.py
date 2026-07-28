"""Tests for mdd.confluence.tree — page tree builder (spec 009b)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from mdd.confluence.client import ConfluenceClient, ConfluenceError
from mdd.confluence.tree import (
    AncestorStep,
    _extend_with_dict_results,  # pyright: ignore[reportPrivateUsage]
    _next_pagination_path,  # pyright: ignore[reportPrivateUsage]
    _node_from_folder,  # pyright: ignore[reportPrivateUsage]
    _node_from_page,  # pyright: ignore[reportPrivateUsage]
    _opt_int,  # pyright: ignore[reportPrivateUsage]
    _opt_str,  # pyright: ignore[reportPrivateUsage]
    ancestor_chain_for_move,
    build_tree,
    get_space_id,
    list_pages,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SPACE_RESPONSE: dict[str, Any] = {
    "results": [
        {"id": "space-001", "key": "ENG", "name": "Engineering"},
    ],
    "_links": {},
}

_PAGES_PAGE1: dict[str, Any] = {
    "results": [
        {
            "id": "p1",
            "title": "Root Page A",
            "parentId": None,
            "position": 10,
            "body": {"storage": {"value": "<p>A</p>"}},
            "version": {"number": 1, "createdAt": "2024-01-01T00:00:00Z"},
            "labels": {"results": []},
        },
        {
            "id": "p2",
            "title": "Root Page B",
            "parentId": None,
            "position": 20,
            "body": {"storage": {"value": "<p>B</p>"}},
            "version": {"number": 1, "createdAt": "2024-01-01T00:00:00Z"},
            "labels": {"results": []},
        },
        {
            "id": "p3",
            "title": "Child of A",
            "parentId": "p1",
            "position": 5,
            "body": {"storage": {"value": "<p>C</p>"}},
            "version": {"number": 1, "createdAt": "2024-01-01T00:00:00Z"},
            "labels": {"results": []},
        },
    ],
    "_links": {"next": "/wiki/api/v2/pages?cursor=page2"},
}

_PAGES_PAGE2: dict[str, Any] = {
    "results": [
        {
            "id": "p4",
            "title": "Child of A (second)",
            "parentId": "p1",
            "position": 15,
            "body": {"storage": {"value": "<p>D</p>"}},
            "version": {"number": 2, "createdAt": "2024-02-01T00:00:00Z"},
            "labels": {"results": []},
        },
        {
            "id": "p5",
            "title": "Child of folder",
            "parentId": "folder-001",
            "position": 1,
            "body": {"storage": {"value": "<p>E</p>"}},
            "version": {"number": 1, "createdAt": "2024-01-01T00:00:00Z"},
            "labels": {"results": []},
        },
        {
            "id": "p6",
            "title": "Another child of folder",
            "parentId": "folder-001",
            "position": None,
            "body": {"storage": {"value": "<p>F</p>"}},
            "version": {"number": 1, "createdAt": "2024-01-01T00:00:00Z"},
            "labels": {"results": []},
        },
    ],
    "_links": {},
}

_FOLDER_RESPONSE: dict[str, Any] = {
    "id": "folder-001",
    "title": "My Folder",
    "type": "folder",
    "parentId": None,
    "position": 30,
}

_FLAT_PAGES = _PAGES_PAGE1["results"] + _PAGES_PAGE2["results"]


def _make_folder_resolver(
    folder_data: dict[str, Any] | None = None,
) -> Any:
    """Return a folder_resolver callable that returns the given folder data."""
    if folder_data is None:
        folder_data = _FOLDER_RESPONSE

    def resolver(folder_id: str) -> dict[str, Any]:
        if folder_id == "folder-001":
            return folder_data
        raise ConfluenceError(f"Folder not found: {folder_id}")

    return resolver


# ---------------------------------------------------------------------------
# Tests for get_space_id
# ---------------------------------------------------------------------------


class TestGetSpaceId:
    def test_returns_space_id(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        client.get.return_value = _SPACE_RESPONSE

        space_id = get_space_id(client, "ENG")

        assert space_id == "space-001"
        client.get.assert_called_once_with(
            "/wiki/api/v2/spaces", params={"keys": "ENG", "limit": 1}
        )

    def test_raises_on_empty_results(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        client.get.return_value = {"results": [], "_links": {}}

        with pytest.raises(ConfluenceError, match="Space not found"):
            get_space_id(client, "MISSING")

    def test_raises_on_missing_id(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        client.get.return_value = {"results": [{"key": "ENG"}], "_links": {}}

        with pytest.raises(ConfluenceError, match="Missing 'id'"):
            get_space_id(client, "ENG")


# ---------------------------------------------------------------------------
# Tests for list_pages
# ---------------------------------------------------------------------------


class TestPaginationHelpers:
    """Unit tests for the helpers extracted from list_pages."""

    def test_extend_with_dict_results_appends_dicts(self) -> None:
        target: list[dict[str, Any]] = []
        _extend_with_dict_results(target, {"results": [{"a": 1}, {"b": 2}]})
        assert target == [{"a": 1}, {"b": 2}]

    def test_extend_with_dict_results_skips_non_dict_items(self) -> None:
        target: list[dict[str, Any]] = []
        _extend_with_dict_results(target, {"results": [{"a": 1}, "string", 42]})
        assert target == [{"a": 1}]

    def test_extend_with_dict_results_ignores_non_list_results(self) -> None:
        target: list[dict[str, Any]] = [{"existing": 1}]
        _extend_with_dict_results(target, {"results": "not a list"})
        assert target == [{"existing": 1}]

    def test_extend_with_dict_results_missing_results_key(self) -> None:
        target: list[dict[str, Any]] = []
        _extend_with_dict_results(target, {})
        assert target == []

    def test_next_pagination_path_returns_next(self) -> None:
        assert _next_pagination_path({"_links": {"next": "/wiki/api/v2/pages?cursor=x"}}) == (
            "/wiki/api/v2/pages?cursor=x"
        )

    def test_next_pagination_path_none_when_links_missing(self) -> None:
        assert _next_pagination_path({}) is None

    def test_next_pagination_path_none_when_next_missing(self) -> None:
        assert _next_pagination_path({"_links": {}}) is None

    def test_next_pagination_path_none_when_links_not_dict(self) -> None:
        assert _next_pagination_path({"_links": "nope"}) is None

    def test_next_pagination_path_empty_string_is_none(self) -> None:
        assert _next_pagination_path({"_links": {"next": ""}}) is None


class TestListPages:
    def test_fetches_all_pages_with_pagination(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        # First call returns page 1 with a next link; second call returns page 2
        client.get.side_effect = [_PAGES_PAGE1, _PAGES_PAGE2]

        pages = list_pages(client, "space-001")

        assert len(pages) == 6
        assert client.get.call_count == 2

        # First call should be with space-id param (kebab-case, per v2 API; #79)
        first_call_args = client.get.call_args_list[0]
        assert first_call_args[0][0] == "/wiki/api/v2/pages"
        params = first_call_args[1]["params"]
        assert params["space-id"] == "space-001"
        assert params["body-format"] == "storage"

        # Second call uses the next link
        second_call_args = client.get.call_args_list[1]
        assert second_call_args[0][0] == "/wiki/api/v2/pages?cursor=page2"

    def test_single_page_no_pagination(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        single: dict[str, Any] = {"results": [_PAGES_PAGE1["results"][0]], "_links": {}}
        client.get.return_value = single

        pages = list_pages(client, "space-001")

        assert len(pages) == 1
        assert client.get.call_count == 1


# ---------------------------------------------------------------------------
# Tests for build_tree
# ---------------------------------------------------------------------------


class TestBuildTree:
    def test_basic_tree_structure(self) -> None:
        roots = build_tree(_FLAT_PAGES, _make_folder_resolver())

        # Should have 3 roots: p1, p2, folder-001
        root_ids = {r["id"] for r in roots}
        assert root_ids == {"p1", "p2", "folder-001"}

    def test_children_linked_correctly(self) -> None:
        roots = build_tree(_FLAT_PAGES, _make_folder_resolver())

        root_by_id = {r["id"]: r for r in roots}

        # p1 should have 2 children: p3 and p4
        p1 = root_by_id["p1"]
        child_ids = {c["id"] for c in p1["children"]}
        assert child_ids == {"p3", "p4"}

        # folder-001 should have 2 children: p5 and p6
        folder = root_by_id["folder-001"]
        folder_child_ids = {c["id"] for c in folder["children"]}
        assert folder_child_ids == {"p5", "p6"}

    def test_position_then_title_sorting(self) -> None:
        roots = build_tree(_FLAT_PAGES, _make_folder_resolver())

        root_by_id = {r["id"]: r for r in roots}
        p1 = root_by_id["p1"]

        # p3 has position=5, p4 has position=15 -> p3 comes first
        children = p1["children"]
        assert children[0]["id"] == "p3"
        assert children[1]["id"] == "p4"

    def test_roots_sorted_by_position(self) -> None:
        roots = build_tree(_FLAT_PAGES, _make_folder_resolver())

        root_ids = [r["id"] for r in roots]
        # p1=10, p2=20, folder-001=30
        assert root_ids == ["p1", "p2", "folder-001"]

    def test_none_position_sorts_last(self) -> None:
        roots = build_tree(_FLAT_PAGES, _make_folder_resolver())
        root_by_id = {r["id"]: r for r in roots}

        # p5 has position=1, p6 has position=None -> p5 first, p6 second
        folder_children = root_by_id["folder-001"]["children"]
        assert folder_children[0]["id"] == "p5"
        assert folder_children[1]["id"] == "p6"

    def test_folder_fetched_lazily(self) -> None:
        resolver_calls: list[str] = []

        def counting_resolver(folder_id: str) -> dict[str, Any]:
            resolver_calls.append(folder_id)
            return _FOLDER_RESPONSE

        # Pages with no folder parents
        no_folder_pages = [p for p in _FLAT_PAGES if p["parentId"] != "folder-001"]
        build_tree(no_folder_pages, counting_resolver)

        # No folders fetched since no pages reference folder parents
        assert resolver_calls == []

    def test_folder_fetched_when_needed(self) -> None:
        resolver_calls: list[str] = []

        def counting_resolver(folder_id: str) -> dict[str, Any]:
            resolver_calls.append(folder_id)
            return _FOLDER_RESPONSE

        build_tree(_FLAT_PAGES, counting_resolver)

        # folder-001 should be fetched exactly once
        assert resolver_calls.count("folder-001") == 1

    def test_folder_node_type(self) -> None:
        roots = build_tree(_FLAT_PAGES, _make_folder_resolver())
        root_by_id = {r["id"]: r for r in roots}
        assert root_by_id["folder-001"]["type"] == "folder"

    def test_page_nodes_have_page_type(self) -> None:
        roots = build_tree(_FLAT_PAGES, _make_folder_resolver())
        root_by_id = {r["id"]: r for r in roots}
        assert root_by_id["p1"]["type"] == "page"
        assert root_by_id["p2"]["type"] == "page"

    def test_multiple_roots(self) -> None:
        # All pages at root level (no parents)
        pages: list[dict[str, Any]] = [
            {"id": "x1", "title": "X1", "parentId": None, "position": 1},
            {"id": "x2", "title": "X2", "parentId": None, "position": 2},
            {"id": "x3", "title": "X3", "parentId": None, "position": 3},
        ]
        roots = build_tree(pages, _make_folder_resolver())
        assert len(roots) == 3
        assert [r["id"] for r in roots] == ["x1", "x2", "x3"]

    def test_empty_pages_list(self) -> None:
        roots = build_tree([], _make_folder_resolver())
        assert roots == []

    def test_title_sorting_when_same_position(self) -> None:
        pages: list[dict[str, Any]] = [
            {"id": "a", "title": "Zebra", "parentId": None, "position": None},
            {"id": "b", "title": "Apple", "parentId": None, "position": None},
        ]
        roots = build_tree(pages, _make_folder_resolver())
        # Both have no position -> sort by title: Apple, Zebra
        assert roots[0]["title"] == "Apple"
        assert roots[1]["title"] == "Zebra"

    def test_folder_fetch_failure_promotes_page_to_root(self) -> None:
        # Pages with a parent that cannot be fetched should end up as roots
        pages: list[dict[str, Any]] = [
            {"id": "orphan", "title": "Orphan Page", "parentId": "missing-folder", "position": 1},
        ]

        def failing_resolver(folder_id: str) -> dict[str, Any]:
            raise ConfluenceError(f"Folder not found: {folder_id}")

        roots = build_tree(pages, failing_resolver)
        assert len(roots) == 1
        assert roots[0]["id"] == "orphan"

    def test_folder_fetch_failure_recorded_in_warnings(self) -> None:
        pages: list[dict[str, Any]] = [
            {"id": "p-warn", "title": "Warn Page", "parentId": "bad-folder", "position": 1},
        ]
        warnings: list[str] = []

        def failing_resolver(folder_id: str) -> dict[str, Any]:
            raise ConfluenceError("404")

        build_tree(pages, failing_resolver, warnings=warnings)
        assert len(warnings) >= 1
        assert any("bad-folder" in w for w in warnings)

    def test_no_warnings_on_clean_tree(self) -> None:
        warnings: list[str] = []
        build_tree(_FLAT_PAGES, _make_folder_resolver(), warnings=warnings)
        assert warnings == []


class TestListPagesSSRF:
    """list_pages must reject API-supplied absolute pagination URLs (SSRF guard)."""

    def test_absolute_next_url_raises(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        # First page has an absolute foreign URL as _links.next
        client.get.return_value = {
            "results": [{"id": "p1", "title": "Page 1", "parentId": None, "position": 0}],
            "_links": {"next": "https://attacker.example/steal?token=abc"},
        }
        from mdd.confluence.client import ConfluenceError

        with pytest.raises(ConfluenceError, match="non-relative URL"):
            list_pages(client, "space-001")

    def test_relative_next_url_accepted(self) -> None:
        client = MagicMock(spec=ConfluenceClient)
        page1: dict[str, Any] = {
            "results": [{"id": "p1", "title": "Page 1", "parentId": None, "position": 0}],
            "_links": {"next": "/wiki/api/v2/pages?cursor=abc123"},
        }
        page2: dict[str, Any] = {
            "results": [{"id": "p2", "title": "Page 2", "parentId": None, "position": 1}],
            "_links": {},
        }
        client.get.side_effect = [page1, page2]
        pages = list_pages(client, "space-001")
        assert len(pages) == 2


class TestNodeBuilderHelpers:
    """Unit tests for the per-node builder helpers extracted from build_tree."""

    def test_node_from_page_returns_none_for_no_id(self) -> None:
        assert _node_from_page({"title": "no id"}) is None

    def test_node_from_page_returns_none_for_non_string_id(self) -> None:
        assert _node_from_page({"id": 42, "title": "x"}) is None

    def test_node_from_page_minimal(self) -> None:
        node = _node_from_page({"id": "p1"})
        assert node is not None
        assert node["id"] == "p1"
        assert node["type"] == "page"
        assert node["title"] == ""
        assert node["position"] is None
        assert node["parent_id"] is None
        assert node["children"] == []

    def test_node_from_page_full(self) -> None:
        node = _node_from_page({"id": "p1", "title": "T", "parentId": "p0", "position": 5})
        assert node is not None
        assert node["title"] == "T"
        assert node["parent_id"] == "p0"
        assert node["position"] == 5

    def test_node_from_folder(self) -> None:
        node = _node_from_folder("f1", {"title": "Folder", "parentId": "f0", "position": 3})
        assert node["id"] == "f1"
        assert node["type"] == "folder"
        assert node["title"] == "Folder"
        assert node["parent_id"] == "f0"
        assert node["position"] == 3

    def test_opt_str(self) -> None:
        assert _opt_str("abc") == "abc"
        assert _opt_str("") is None
        assert _opt_str(None) is None
        assert _opt_str(42) is None

    def test_opt_int_accepts_int_rejects_bool(self) -> None:
        assert _opt_int(5) == 5
        assert _opt_int(0) == 0
        assert _opt_int(True) is None
        assert _opt_int(False) is None
        assert _opt_int(None) is None
        assert _opt_int("5") is None


# ---------------------------------------------------------------------------
# ancestor_chain_for_move (spec S27)
# ---------------------------------------------------------------------------


def _make_ancestor_client(
    *,
    ancestors: list[dict[str, Any]],
    parent_data: dict[str, Any],
) -> MagicMock:
    """Build a mock client that returns the given /ancestors and parent payloads."""
    client = MagicMock(spec=ConfluenceClient)
    client.get_page_ancestors.return_value = ancestors
    client.get_page.return_value = parent_data
    return client


class TestAncestorChainForMove:
    def test_parent_dir_already_exists(self, tmp_path: Path) -> None:
        """Direct parent has a children-dir already — single step, state=dir."""
        parent_dir = tmp_path / "Parent"
        parent_dir.mkdir()

        client = _make_ancestor_client(
            ancestors=[],
            parent_data={"id": "P", "title": "Parent", "spaceId": "S"},
        )
        chain = ancestor_chain_for_move(client, "P", "S", tmp_path)

        assert len(chain) == 1
        assert chain[0].page_id == "P"
        assert chain[0].title == "Parent"
        assert chain[0].state == "dir"
        assert chain[0].expected_dir == parent_dir
        assert chain[0].flat_md_path is None

    def test_flat_parent_no_directory(self, tmp_path: Path) -> None:
        """Parent exists as Parent.md but the directory does not."""
        (tmp_path / "Parent.md").write_text("---\n---\nbody\n")

        client = _make_ancestor_client(
            ancestors=[],
            parent_data={"id": "P", "title": "Parent", "spaceId": "S"},
        )
        chain = ancestor_chain_for_move(client, "P", "S", tmp_path)

        assert len(chain) == 1
        assert chain[0].state == "flat"
        assert chain[0].flat_md_path == tmp_path / "Parent.md"
        assert chain[0].expected_dir == tmp_path / "Parent"

    def test_absent_parent(self, tmp_path: Path) -> None:
        """Neither a flat Parent.md nor a directory exists."""
        client = _make_ancestor_client(
            ancestors=[],
            parent_data={"id": "P", "title": "Parent", "spaceId": "S"},
        )
        chain = ancestor_chain_for_move(client, "P", "S", tmp_path)

        assert len(chain) == 1
        assert chain[0].state == "absent"
        assert chain[0].flat_md_path is None

    def test_chain_grandparent_then_parent_top_to_bottom(self, tmp_path: Path) -> None:
        """Two-deep chain — root → parent — both absent; expected_dirs nested."""
        client = _make_ancestor_client(
            ancestors=[
                {"id": "G", "title": "Grandparent", "spaceId": "S"},
            ],
            parent_data={"id": "P", "title": "Parent", "spaceId": "S"},
        )
        chain = ancestor_chain_for_move(client, "P", "S", tmp_path)

        assert len(chain) == 2
        # results[0] is the topmost ancestor, parent comes last
        assert chain[0].page_id == "G"
        assert chain[0].expected_dir == tmp_path / "Grandparent"
        assert chain[1].page_id == "P"
        assert chain[1].expected_dir == tmp_path / "Grandparent" / "Parent"
        assert chain[0].state == "absent"
        assert chain[1].state == "absent"

    def test_mixed_chain_states(self, tmp_path: Path) -> None:
        """Grandparent already a directory, parent is flat."""
        (tmp_path / "Grandparent").mkdir()
        (tmp_path / "Grandparent" / "Parent.md").write_text("---\n---\nx\n")

        client = _make_ancestor_client(
            ancestors=[
                {"id": "G", "title": "Grandparent", "spaceId": "S"},
            ],
            parent_data={"id": "P", "title": "Parent", "spaceId": "S"},
        )
        chain = ancestor_chain_for_move(client, "P", "S", tmp_path)
        assert chain[0].state == "dir"
        assert chain[1].state == "flat"
        assert chain[1].flat_md_path == tmp_path / "Grandparent" / "Parent.md"

    def test_cross_space_ancestor_raises(self, tmp_path: Path) -> None:
        """An ancestor in a different space is a hard failure."""
        client = _make_ancestor_client(
            ancestors=[
                {"id": "G", "title": "Foreign", "spaceId": "OTHER"},
            ],
            parent_data={"id": "P", "title": "Parent", "spaceId": "S"},
        )
        with pytest.raises(ConfluenceError, match="different space"):
            ancestor_chain_for_move(client, "P", "S", tmp_path)

    def test_missing_space_id_on_ancestor_is_tolerated(self, tmp_path: Path) -> None:
        """A missing spaceId on the ancestor entry does not fail the walk."""
        client = _make_ancestor_client(
            ancestors=[
                {"id": "G", "title": "Grandparent"},  # no spaceId
            ],
            parent_data={"id": "P", "title": "Parent", "spaceId": "S"},
        )
        chain = ancestor_chain_for_move(client, "P", "S", tmp_path)
        assert len(chain) == 2


class TestAncestorStep:
    def test_frozen(self) -> None:
        step = AncestorStep(
            page_id="P",
            title="Parent",
            expected_dir=Path("/tmp/x"),  # noqa: S108  # literal path string for a parsing/path test; no temp file created
            state="absent",
        )
        with pytest.raises(FrozenInstanceError):
            step.page_id = "Q"  # pyright: ignore[reportAttributeAccessIssue]
