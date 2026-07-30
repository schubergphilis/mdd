"""Tests for mdd.ai.bm25 — BM25 index wrapper."""

from __future__ import annotations

from pathlib import Path

import pytest

from mdd.ai.bm25 import Bm25Index, _strip_markup, _tokenise  # pyright: ignore[reportPrivateUsage]

# ---------------------------------------------------------------------------
# Text pre-processing
# ---------------------------------------------------------------------------


class TestStripMarkup:
    def test_strips_frontmatter(self) -> None:
        text = "---\ntitle: Test\n---\n\nBody text here."
        result = _strip_markup(text)
        assert "title" not in result
        assert "Body text here" in result

    def test_strips_code_blocks(self) -> None:
        text = "Before\n\n```python\nx = 1\n```\n\nAfter"
        result = _strip_markup(text)
        assert "x = 1" not in result
        assert "Before" in result
        assert "After" in result

    def test_strips_tilde_code_blocks(self) -> None:
        text = "Before\n\n~~~\ncode here\n~~~\n\nAfter"
        result = _strip_markup(text)
        assert "code here" not in result

    def test_no_frontmatter_or_code_unchanged(self) -> None:
        text = "Simple text with no special markup."
        assert _strip_markup(text) == text

    def test_strips_confluence_fenced_block(self) -> None:
        text = "Prose\n\n```{=confluence}\n<ac:macro/>\n```\n\nMore prose"
        result = _strip_markup(text)
        assert "<ac:macro/>" not in result
        assert "Prose" in result
        assert "More prose" in result


class TestTokenise:
    def test_returns_lowercase_words(self) -> None:
        tokens = _tokenise("Hello World")
        assert tokens == ["hello", "world"]

    def test_ignores_frontmatter(self) -> None:
        text = "---\ntitle: Secret\n---\n\nBody content."
        tokens = _tokenise(text)
        assert "secret" not in tokens
        assert "body" in tokens
        assert "content" in tokens

    def test_empty_text_returns_empty(self) -> None:
        assert _tokenise("") == []


# ---------------------------------------------------------------------------
# Bm25Index
# ---------------------------------------------------------------------------


class TestBm25Index:
    @pytest.fixture
    def sample_docs(self) -> list[tuple[Path, str]]:
        return [
            (
                Path("Engineering/Onboarding.md"),
                "Laptop provisioning IT portal access software setup Slack channels.",
            ),
            (
                Path("Engineering/New Hire Setup.md"),
                "Laptop provisioning IT portal access tools install Homebrew Git Docker Slack.",
            ),
            (
                Path("Process/Deployment.md"),
                "Blue-green deployment strategy rollout traffic switch pre-deployment checklist.",
            ),
            (
                Path("Unrelated/Security.md"),
                "Password requirements VPN vulnerability reporting security policy.",
            ),
        ]

    def test_build_nonempty(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        assert len(index) == 4

    def test_top_k_for_returns_neighbours(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        onboarding = Path("Engineering/Onboarding.md")
        results = index.top_k_for(onboarding, k=3)
        assert len(results) <= 3
        # The most similar should be New Hire Setup (same topic)
        paths = [p for p, _ in results]
        assert Path("Engineering/New Hire Setup.md") in paths

    def test_top_k_for_excludes_self(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        path = Path("Engineering/Onboarding.md")
        results = index.top_k_for(path, k=10)
        assert all(p != path for p, _ in results)

    def test_top_k_for_unknown_path_returns_empty(
        self, sample_docs: list[tuple[Path, str]]
    ) -> None:
        index = Bm25Index.build(sample_docs)
        results = index.top_k_for(Path("nonexistent.md"), k=5)
        assert results == []

    def test_top_k_for_with_restrict_to(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        allowed = {Path("Process/Deployment.md")}
        results = index.top_k_for(Path("Engineering/Onboarding.md"), k=5, restrict_to=allowed)
        assert all(p in allowed for p, _ in results)

    def test_top_k_pairs_deduplicates_symmetric(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        pairs = index.top_k_pairs(k=3, min_score=0.0)
        # Check no duplicate pairs (A,B) == (B,A)
        seen: set[tuple[Path, Path]] = set()
        for pair in pairs:
            key = (min(str(pair.path_a), str(pair.path_b)), max(str(pair.path_a), str(pair.path_b)))
            assert key not in seen, f"Duplicate pair: {pair}"
            seen.add(key)  # type: ignore[arg-type]

    def test_top_k_pairs_sorted_by_score(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        pairs = index.top_k_pairs(k=5, min_score=0.0)
        scores = [p.score for p in pairs]
        assert scores == sorted(scores, reverse=True)

    def test_top_k_pairs_min_score_filter(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        pairs_high = index.top_k_pairs(k=5, min_score=100.0)
        # With a very high threshold, no pairs should pass
        assert pairs_high == []

    def test_build_empty_corpus(self) -> None:
        index = Bm25Index.build([])
        assert len(index) == 0
        assert index.top_k_pairs(k=5) == []
        assert index.top_k_for(Path("anything.md"), k=5) == []

    def test_build_single_document(self) -> None:
        index = Bm25Index.build([(Path("only.md"), "some content here")])
        assert len(index) == 1
        assert index.top_k_for(Path("only.md"), k=5) == []
        assert index.top_k_pairs(k=5) == []

    def test_paths_property(self, sample_docs: list[tuple[Path, str]]) -> None:
        index = Bm25Index.build(sample_docs)
        assert len(index.paths) == 4
        assert Path("Engineering/Onboarding.md") in index.paths

    def test_all_shares_index_no_double_build(self, sample_docs: list[tuple[Path, str]]) -> None:
        """Building once and querying twice produces consistent results."""
        index = Bm25Index.build(sample_docs)
        pairs1 = index.top_k_pairs(k=3, min_score=0.0)
        pairs2 = index.top_k_pairs(k=3, min_score=0.0)
        # Same index, same results
        assert [(str(p.path_a), str(p.path_b)) for p in pairs1] == [
            (str(p.path_a), str(p.path_b)) for p in pairs2
        ]
