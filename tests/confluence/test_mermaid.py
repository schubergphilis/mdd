"""Tests for mdd.confluence.mermaid — fences render to SVG and become image refs.

No test needs ``mermaidx`` or ``mmdc``: the in-process path gets a fake
``mermaidx`` module injected into ``sys.modules``; the external-command path
mocks ``shutil.which`` and ``subprocess.run`` with a fake that writes a minimal
SVG to the ``{output}`` path.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import types
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from mdd.confluence.create import create_page
from mdd.confluence.mermaid import (
    MermaidFence,
    find_mermaid_fences,
    load_mermaid_config,
    load_mermaid_config_from,
    render_mermaid_fences,
)
from mdd.converters.models import MermaidConfig
from mdd.converters.protocol import ConvertResult

if TYPE_CHECKING:
    from collections.abc import Iterator

_WHICH = "mdd.confluence.mermaid.shutil.which"
_RUN = "mdd.confluence.mermaid.subprocess.run"
_LOAD = "mdd.confluence.mermaid.load_mermaid_config"
_MMDC = MermaidConfig(renderer="mmdc")
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'

_FENCE_A = "```mermaid\ngraph TD\n  A --> B\n```"
_FENCE_B = "```mermaid\nsequenceDiagram\n  A->>B: hi\n```"


def _sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _output_arg(argv: list[str]) -> Path:
    return Path(argv[argv.index("-o") + 1])


def _fake_run_ok(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
    """Stand-in for mmdc: write an SVG to the ``-o`` path and exit 0."""
    _output_arg(argv).write_bytes(_SVG)
    return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def _fake_run_fail(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Parse error on line 2")


@pytest.fixture
def md_path(tmp_path: Path) -> Path:
    path = tmp_path / "page.md"
    path.write_text("# Page\n", encoding="utf-8")
    return path


@pytest.fixture
def renderer_present() -> Iterator[MagicMock]:
    with (
        patch(_WHICH, return_value="/usr/local/bin/mmdc"),
        patch(_RUN, side_effect=_fake_run_ok) as run,
    ):
        yield run


def _fake_mermaidx(render: Any = None) -> types.ModuleType:
    """A stand-in ``mermaidx`` module: ``render(source).svg()`` returns a tiny SVG."""
    module = types.ModuleType("mermaidx")

    def default_render(source: str, backend: str | None = None, **_: Any) -> Any:
        diagram = MagicMock()
        diagram.svg.return_value = _SVG.decode("utf-8")
        return diagram

    module.render = render if render is not None else default_render  # pyright: ignore[reportAttributeAccessIssue]
    return module


class TestFindMermaidFences:
    def test_finds_backtick_and_tilde_fences(self) -> None:
        body = "intro\n\n```mermaid\ngraph TD\n```\n\n~~~mermaid\npie\n~~~\n"
        fences = find_mermaid_fences(body)
        assert [(f.start, f.end, f.content) for f in fences] == [
            (2, 4, "graph TD"),
            (6, 8, "pie"),
        ]

    def test_info_string_attributes_match_on_first_word(self) -> None:
        body = '```mermaid {title="Flow"}\ngraph TD\n```\n'
        assert len(find_mermaid_fences(body)) == 1

    @pytest.mark.parametrize("info", ["mermaidjs", "python", "", " Mermaid"])
    def test_other_languages_are_ignored(self, info: str) -> None:
        assert find_mermaid_fences(f"```{info}\ngraph TD\n```\n") == []

    def test_fence_inside_larger_code_block_is_not_a_candidate(self) -> None:
        body = "````markdown\n```mermaid\ngraph TD\n```\n````\n"
        assert find_mermaid_fences(body) == []

    def test_closing_fence_must_be_at_least_as_long(self) -> None:
        body = "````mermaid\ngraph TD\n```\nstill inside\n````\n"
        fences = find_mermaid_fences(body)
        assert len(fences) == 1
        assert fences[0].content == "graph TD\n```\nstill inside"

    def test_unterminated_fence_is_left_alone(self) -> None:
        assert find_mermaid_fences("```mermaid\ngraph TD\n") == []

    def test_indented_fences_within_three_spaces(self) -> None:
        body = "   ```mermaid\n   graph TD\n   ```\n"
        assert len(find_mermaid_fences(body)) == 1

    def test_four_space_indent_is_not_a_fence(self) -> None:
        assert find_mermaid_fences("    ```mermaid\n    graph TD\n    ```\n") == []

    def test_backtick_in_info_string_is_not_a_fence(self) -> None:
        # CommonMark: a backtick fence's info string may not contain a backtick.
        assert find_mermaid_fences("```mermaid `x`\ngraph TD\n```\n") == []

    def test_closing_fence_indented_four_spaces_does_not_close(self) -> None:
        body = "```mermaid\ngraph TD\n    ```\n```\n"
        fences = find_mermaid_fences(body)
        assert len(fences) == 1
        assert fences[0].content == "graph TD\n    ```"

    def test_sha_is_content_addressed(self) -> None:
        fence = MermaidFence(start=0, end=2, content="graph TD")
        assert fence.sha == _sha("graph TD")


class TestRenderWithExternalCommand:
    """``mermaid.renderer`` naming an executable: the mermaid-cli shape."""

    @pytest.fixture(autouse=True)
    def _mmdc_config(self) -> Iterator[None]:
        with patch(_LOAD, return_value=_MMDC):
            yield

    def test_one_fence_rendered_and_replaced(
        self, md_path: Path, renderer_present: MagicMock
    ) -> None:
        body = f"# Page\n\n{_FENCE_A}\n\nAfter.\n"
        out = render_mermaid_fences(body, md_path)
        sha = _sha("graph TD\n  A --> B")
        svg = md_path.parent / "page-attachments" / f"mermaid-{sha}.svg"
        assert (
            out == f"# Page\n\n![Mermaid diagram](page-attachments/mermaid-{sha}.svg)\n\nAfter.\n"
        )
        assert svg.read_bytes() == _SVG
        assert renderer_present.call_count == 1
        # The renderer was fed the fence content through a temporary .mmd file.
        argv: list[str] = renderer_present.call_args.args[0]
        assert argv[0] == "/usr/local/bin/mmdc"
        assert argv[argv.index("-i") + 1].endswith(".mmd")
        assert argv[-2:] == ["-b", "transparent"]
        # The source file on disk is untouched.
        assert md_path.read_text(encoding="utf-8") == "# Page\n"

    def test_two_identical_fences_share_one_file(
        self, md_path: Path, renderer_present: MagicMock
    ) -> None:
        out = render_mermaid_fences(f"{_FENCE_A}\n\ntext\n\n{_FENCE_A}\n", md_path)
        assert out.count("![Mermaid diagram](page-attachments/mermaid-") == 2
        assert renderer_present.call_count == 1
        assert len(list((md_path.parent / "page-attachments").glob("*.svg"))) == 1

    def test_two_different_fences_render_separately(
        self, md_path: Path, renderer_present: MagicMock
    ) -> None:
        out = render_mermaid_fences(f"{_FENCE_A}\n\n{_FENCE_B}\n", md_path)
        assert "```" not in out
        assert renderer_present.call_count == 2

    def test_cache_hit_skips_renderer(self, md_path: Path) -> None:
        sha = _sha("graph TD\n  A --> B")
        cached = md_path.parent / "page-attachments" / f"mermaid-{sha}.svg"
        cached.parent.mkdir()
        cached.write_bytes(b"<svg/>")
        with patch(_WHICH) as which, patch(_RUN) as run:
            out = render_mermaid_fences(f"{_FENCE_A}\n", md_path)
        assert out == f"![Mermaid diagram](page-attachments/mermaid-{sha}.svg)\n"
        which.assert_not_called()
        run.assert_not_called()
        assert cached.read_bytes() == b"<svg/>"

    def test_renderer_missing_leaves_fences_and_warns_once(
        self, md_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = f"{_FENCE_A}\n\n{_FENCE_B}\n"
        with (
            patch(_WHICH, return_value=None),
            patch(_RUN) as run,
            caplog.at_level(logging.WARNING),
        ):
            out = render_mermaid_fences(body, md_path)
        assert out == body
        run.assert_not_called()
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [
            "mermaid renderer 'mmdc' not found; 2 diagram(s) left as code blocks; "
            "install @mermaid-js/mermaid-cli or set mermaid.renderer"
        ]
        assert not (md_path.parent / "page-attachments").exists()

    def test_renderer_failure_leaves_that_fence_and_warns(
        self, md_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
            src = Path(argv[argv.index("-i") + 1]).read_text(encoding="utf-8")
            if "sequenceDiagram" in src:
                return _fake_run_fail(argv, **kw)
            return _fake_run_ok(argv, **kw)

        with (
            patch(_WHICH, return_value="/usr/local/bin/mmdc"),
            patch(_RUN, side_effect=run),
            caplog.at_level(logging.WARNING),
        ):
            out = render_mermaid_fences(f"{_FENCE_A}\n\n{_FENCE_B}\n", md_path)
        assert out.startswith("![Mermaid diagram](page-attachments/mermaid-")
        assert _FENCE_B in out
        msgs = [r.getMessage() for r in caplog.records]
        assert any("exit 1" in m and "Parse error on line 2" in m for m in msgs)
        # A failed render leaves no file behind to be mistaken for a cache hit.
        assert len(list((md_path.parent / "page-attachments").glob("*.svg"))) == 1

    def test_renderer_exit_zero_without_output_is_a_failure(
        self, md_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        def run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

        with (
            patch(_WHICH, return_value="/usr/local/bin/mmdc"),
            patch(_RUN, side_effect=run),
            caplog.at_level(logging.WARNING),
        ):
            out = render_mermaid_fences(f"{_FENCE_A}\n", md_path)
        assert out == f"{_FENCE_A}\n"
        assert any("exit 0" in r.getMessage() for r in caplog.records)

    def test_renderer_oserror_is_a_failure(
        self, md_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            patch(_WHICH, return_value="/usr/local/bin/mmdc"),
            patch(_RUN, side_effect=subprocess.TimeoutExpired("mmdc", 120)),
            caplog.at_level(logging.WARNING),
        ):
            out = render_mermaid_fences(f"{_FENCE_A}\n", md_path)
        assert out == f"{_FENCE_A}\n"
        assert any("could not run" in r.getMessage() for r in caplog.records)

    def test_fence_inside_code_block_is_not_touched(
        self, md_path: Path, renderer_present: MagicMock
    ) -> None:
        body = "````markdown\n```mermaid\ngraph TD\n```\n````\n"
        assert render_mermaid_fences(body, md_path) == body
        renderer_present.assert_not_called()

    def test_info_string_with_attributes_is_rendered(
        self, md_path: Path, renderer_present: MagicMock
    ) -> None:
        out = render_mermaid_fences('```mermaid {title="Flow"}\ngraph TD\n```\n', md_path)
        assert out.startswith("![Mermaid diagram](")
        assert renderer_present.call_count == 1

    def test_no_fences_is_a_no_op_without_config_lookup(self, md_path: Path) -> None:
        with patch(_LOAD) as load:
            assert render_mermaid_fences("just prose\n", md_path) == "just prose\n"
        load.assert_not_called()

    def test_custom_config_drives_argv(self, md_path: Path) -> None:
        cfg = MermaidConfig(renderer="my-mmd", args=["render", "{input}", "--to", "{output}"])
        seen: list[list[str]] = []

        def run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
            seen.append(argv)
            Path(argv[-1]).write_bytes(_SVG)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        with patch(_WHICH, return_value="/opt/my-mmd") as which, patch(_RUN, side_effect=run):
            render_mermaid_fences(f"{_FENCE_A}\n", md_path, config=cfg)
        which.assert_called_once_with("my-mmd")
        assert seen[0][0] == "/opt/my-mmd"
        assert seen[0][1] == "render"
        assert seen[0][2].endswith(".mmd")
        assert seen[0][3] == "--to"
        assert seen[0][4].endswith(".svg")

    def test_stem_with_space_is_percent_encoded(
        self, tmp_path: Path, renderer_present: MagicMock
    ) -> None:
        md = tmp_path / "Some Page.md"
        md.write_text("", encoding="utf-8")
        out = render_mermaid_fences(f"{_FENCE_A}\n", md)
        assert out.startswith("![Mermaid diagram](Some%20Page-attachments/mermaid-")
        assert (tmp_path / "Some Page-attachments").is_dir()


class TestRenderWithMermaidx:
    """The default renderer: the optional in-process ``mermaidx`` package."""

    def test_default_config_is_in_process(self) -> None:
        assert MermaidConfig().renderer == "mermaidx"

    def test_fence_rendered_in_process_and_replaced(self, md_path: Path) -> None:
        seen: list[str] = []

        def render(source: str, backend: str | None = None, **_: Any) -> Any:
            seen.append(source)
            diagram = MagicMock()
            diagram.svg.return_value = "<svg xmlns='http://www.w3.org/2000/svg'/>"
            return diagram

        with (
            patch.dict(sys.modules, {"mermaidx": _fake_mermaidx(render)}),
            patch(_WHICH) as which,
            patch(_RUN) as run,
        ):
            out = render_mermaid_fences(f"# Page\n\n{_FENCE_A}\n", md_path)
        sha = _sha("graph TD\n  A --> B")
        svg = md_path.parent / "page-attachments" / f"mermaid-{sha}.svg"
        assert out == f"# Page\n\n![Mermaid diagram](page-attachments/mermaid-{sha}.svg)\n"
        assert svg.read_text(encoding="utf-8") == "<svg xmlns='http://www.w3.org/2000/svg'/>"
        assert seen == ["graph TD\n  A --> B"]
        # No PATH lookup and no subprocess on the in-process path.
        which.assert_not_called()
        run.assert_not_called()
        assert md_path.read_text(encoding="utf-8") == "# Page\n"

    def test_identical_fences_share_one_render(self, md_path: Path) -> None:
        render = MagicMock(side_effect=_fake_mermaidx().render)  # pyright: ignore[reportAttributeAccessIssue]
        with patch.dict(sys.modules, {"mermaidx": _fake_mermaidx(render)}):
            out = render_mermaid_fences(f"{_FENCE_A}\n\n{_FENCE_A}\n\n{_FENCE_B}\n", md_path)
        assert out.count("![Mermaid diagram](") == 3
        assert render.call_count == 2

    def test_cache_hit_skips_import_and_render(self, md_path: Path) -> None:
        sha = _sha("graph TD\n  A --> B")
        cached = md_path.parent / "page-attachments" / f"mermaid-{sha}.svg"
        cached.parent.mkdir()
        cached.write_bytes(b"<svg/>")
        # ``None`` in sys.modules makes ``import mermaidx`` raise ImportError,
        # so a cache hit that still imported would fail loudly here.
        with patch.dict(sys.modules, {"mermaidx": None}):
            out = render_mermaid_fences(f"{_FENCE_A}\n", md_path)
        assert out == f"![Mermaid diagram](page-attachments/mermaid-{sha}.svg)\n"
        assert cached.read_bytes() == b"<svg/>"

    def test_not_installed_leaves_fences_and_warns_once(
        self, md_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        body = f"{_FENCE_A}\n\n{_FENCE_B}\n"
        with patch.dict(sys.modules, {"mermaidx": None}), caplog.at_level(logging.WARNING):
            out = render_mermaid_fences(body, md_path)
        assert out == body
        warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings == [
            "mermaid renderer 'mermaidx' is not installed; 2 diagram(s) left as code blocks; "
            "install with `uv add mdd[mermaid]` (or `pip install mermaidx`) or set "
            "mermaid.renderer to an external command"
        ]
        assert not (md_path.parent / "page-attachments").exists()

    def test_render_error_leaves_that_fence_and_warns(
        self, md_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        def render(source: str, backend: str | None = None, **_: Any) -> Any:
            if "sequenceDiagram" in source:
                raise ValueError("Parse error on line 2")
            return _fake_mermaidx().render(source)  # pyright: ignore[reportAttributeAccessIssue]

        with (
            patch.dict(sys.modules, {"mermaidx": _fake_mermaidx(render)}),
            caplog.at_level(logging.WARNING),
        ):
            out = render_mermaid_fences(f"{_FENCE_A}\n\n{_FENCE_B}\n", md_path)
        assert out.startswith("![Mermaid diagram](page-attachments/mermaid-")
        assert _FENCE_B in out
        msgs = [r.getMessage() for r in caplog.records]
        assert any("'mermaidx' failed" in m and "Parse error on line 2" in m for m in msgs)
        # The failed diagram left no file behind to be mistaken for a cache hit.
        assert len(list((md_path.parent / "page-attachments").glob("*.svg"))) == 1


class TestMermaidConfigLoader:
    def test_block_round_trips(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text('mermaid:\n  renderer: kroki-cli\n  args: ["{input}", "{output}"]\n')
        cfg = load_mermaid_config_from(cfg_path)
        assert cfg is not None
        assert cfg.renderer == "kroki-cli"
        assert cfg.args == ["{input}", "{output}"]

    def test_empty_block_yields_defaults(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("mermaid: {}\n")
        cfg = load_mermaid_config_from(cfg_path)
        assert cfg is not None
        assert cfg == MermaidConfig()
        assert cfg.args == ["-i", "{input}", "-o", "{output}", "-b", "transparent"]

    def test_other_blocks_are_tolerated_on_the_envelope(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("svg:\n  renderer: resvg\nmermaid:\n  renderer: mmdc\n")
        cfg = load_mermaid_config_from(cfg_path)
        assert cfg is not None
        assert cfg.renderer == "mmdc"

    def test_no_block_returns_none(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("svg:\n  renderer: resvg\n")
        assert load_mermaid_config_from(cfg_path) is None

    def test_unreadable_or_non_mapping_returns_none(self, tmp_path: Path) -> None:
        assert load_mermaid_config_from(tmp_path / "absent.yaml") is None
        listy = tmp_path / "list.yaml"
        listy.write_text("- a\n- b\n")
        assert load_mermaid_config_from(listy) is None

    def test_unknown_key_logs_and_returns_none(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cfg_path = tmp_path / "mdd.yaml"
        cfg_path.write_text("mermaid:\n  rendrer: mmdc\n")
        with caplog.at_level(logging.WARNING):
            assert load_mermaid_config_from(cfg_path) is None
        assert any("rendrer" in r.getMessage() for r in caplog.records)

    def test_search_order_and_defaults(self, tmp_path: Path) -> None:
        first = tmp_path / "configs" / "mdd.yaml"
        with patch("mdd.confluence.mermaid._config_candidates", return_value=[first]):
            assert load_mermaid_config() == MermaidConfig()
            first.parent.mkdir()
            first.write_text("mermaid:\n  renderer: other\n")
            assert load_mermaid_config().renderer == "other"


# ---------------------------------------------------------------------------
# End to end: create-page renders, uploads SVG + PNG, never edits the source
# ---------------------------------------------------------------------------


def _make_config() -> MagicMock:
    cfg = MagicMock()
    cfg.url = "https://example.atlassian.net"
    cfg.username = "user@example.com"
    cfg.api_token = "tok"
    return cfg


def _make_client() -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get_space.return_value = {"id": "SPACE1"}
    client.post_page.return_value = {"id": "42", "title": "x", "status": "current"}
    client.put_page.return_value = {
        "id": "42",
        "title": "x",
        "status": "current",
        "version": {"number": 2, "authorId": "uid1", "createdAt": "2024-01-01T00:00:00Z"},
    }
    client.get_user.return_value = {"displayName": "Alice"}
    client.upload_attachment.return_value = {"results": [{"version": {"number": 1}}]}
    return client


class TestCreatePageEndToEnd:
    def test_mermaid_fence_publishes_as_image(self, tmp_path: Path) -> None:
        md = tmp_path / "page.md"
        source = f"# Page\n\n{_FENCE_A}\n"
        md.write_text(source, encoding="utf-8")
        sha = _sha("graph TD\n  A --> B")

        def fake_convert(src: Path) -> ConvertResult:
            png = src.with_name(src.name + ".png")
            png.write_bytes(b"\x89PNG fake")
            return ConvertResult(output_path=png, attachments_dir=None, metadata={}, warnings=[])

        converter = MagicMock()
        converter.convert.side_effect = fake_convert
        client = _make_client()
        with (
            patch.dict(sys.modules, {"mermaidx": _fake_mermaidx()}),
            patch(
                "mdd.confluence.attachments.svg_publish.SvgToPngConverter",
                return_value=converter,
            ),
            patch("mdd.confluence.create.ConfluenceClient", return_value=client),
            patch("mdd.confluence.create.get_mirror_url", return_value=None),
        ):
            assert create_page(md, _make_config(), space_key="S") == 0

        uploaded = sorted(c.args[1].name for c in client.upload_attachment.call_args_list)
        assert uploaded == [f"mermaid-{sha}.svg", f"mermaid-{sha}.svg.png"]
        body_xhtml: str = client.put_page.call_args.args[2]
        assert f'<ri:attachment ri:filename="mermaid-{sha}.svg.png"' in body_xhtml
        assert "graph TD" not in body_xhtml
        # Frontmatter was written back, but the body still holds the fence.
        text = md.read_text(encoding="utf-8")
        assert text.endswith(source)
        assert "Mermaid diagram" not in text
