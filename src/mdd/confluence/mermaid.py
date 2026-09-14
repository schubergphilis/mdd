"""Render ```` ```mermaid ```` fences to SVG so they publish as images.

Confluence Cloud has no native Mermaid rendering: a ```` ```mermaid ```` fence
pushed as-is becomes a code macro showing the diagram source. This module runs
on the body text before attachment sync and, for every such fence, renders the
diagram into ``<stem>-attachments/mermaid-<sha>.svg`` next to the source file,
then swaps the fence for a Markdown image reference to that file.

Two renderers. The default is in-process: the optional ``mermaidx`` package
(``mdd[mermaid]`` extra) runs the real mermaid.js in an embedded JavaScript
engine — no Node, no browser, same output on every machine, which is what a
CI publish step wants. Alternatively ``mermaid.renderer`` names an external
command (``mmdc`` from ``@mermaid-js/mermaid-cli``) for teams that already
ship mermaid-cli; ``mermaid.args`` is its argument template. From
there the existing SVG publish path takes over — rasterize to PNG, upload
both, rewrite the reference — exactly as it does for a hand-placed SVG.

The output name is the first twelve hex characters of the SHA-256 of the fence
content, which makes the filename the cache: an unchanged diagram is never
re-rendered, two identical fences share one file, and a changed diagram simply
stops being referenced. Nothing here touches the source ``.md``; only the
attachments directory gains files.

A missing renderer degrades rather than fails — the fences stay code blocks,
which still show the diagram source — because that is a readable page, unlike
the broken image an unrendered SVG would be.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from mdd.converters.models import MERMAIDX_RENDERER, MermaidConfig, MermaidWrapper
from mdd.utils.frontmatter import parse_yaml_mapping
from mdd.utils.logging import get_logger

log = get_logger(__name__)

# Seconds a single render may take before it is abandoned. mmdc starts a
# headless browser, so the first call on a cold machine is slow; anything
# beyond this is a hang.
_RENDER_TIMEOUT_S = 120

_IMAGE_ALT = "Mermaid diagram"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _config_candidates() -> list[Path]:
    # Same search order as the ``svg:`` block, so one file configures both
    # halves of the diagram pipeline.
    return [Path("configs") / "mdd.yaml", Path.home() / ".config" / "mdd" / "config.yaml"]


def load_mermaid_config_from(path: Path) -> MermaidConfig | None:
    """Load and validate the ``mermaid:`` block from *path*.

    ``None`` when the file is unreadable, is not a YAML mapping, or has no
    ``mermaid:`` block; a default-valued config when the block is present
    but empty. A typo'd key logs and returns ``None`` so the search falls
    through to the next candidate rather than aborting the push.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    mapping = parse_yaml_mapping(text)
    if mapping is None or "mermaid" not in mapping:
        return None
    try:
        wrapper = MermaidWrapper.model_validate(dict(mapping))
    except ValidationError as exc:
        log.warning("Ignoring invalid mermaid config in %s: %s", path, exc)
        return None
    return wrapper.mermaid if wrapper.mermaid is not None else MermaidConfig()


def load_mermaid_config() -> MermaidConfig:
    """Return the typed ``mermaid:`` config from the first mdd config file found."""
    for path in _config_candidates():
        if not path.exists():
            continue
        cfg = load_mermaid_config_from(path)
        if cfg is not None:
            return cfg
    return MermaidConfig()


# ---------------------------------------------------------------------------
# Fence scanning
# ---------------------------------------------------------------------------

# CommonMark fenced code block opener: up to three spaces of indent, then a
# run of three or more backticks or tildes, then the info string.
_FENCE_OPEN_RE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$")


@dataclass(frozen=True)
class MermaidFence:
    """One ```` ```mermaid ```` block: line span (inclusive, 0-based) and content."""

    start: int
    end: int
    content: str

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class _OpenFence:
    char: str
    length: int
    start: int
    mermaid: bool


def _open_fence(line: str, idx: int) -> _OpenFence | None:
    m = _FENCE_OPEN_RE.match(line)
    if m is None:
        return None
    fence = m.group("fence")
    info = m.group("info").strip()
    # A backtick fence's info string may not contain a backtick (CommonMark);
    # such a line is inline code, not a fence.
    if fence[0] == "`" and "`" in info:
        return None
    # Only the first word of the info string is the language, so
    # ``mermaid {title="x"}`` still qualifies.
    is_mermaid = info.split()[:1] == ["mermaid"]
    return _OpenFence(char=fence[0], length=len(fence), start=idx, mermaid=is_mermaid)


def _closes(line: str, fence: _OpenFence) -> bool:
    """CommonMark closing fence: same char, at least as long, up to three spaces indent."""
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3:
        return False
    run = stripped.rstrip()
    return len(run) >= fence.length and set(run) == {fence.char}


def find_mermaid_fences(body_md: str) -> list[MermaidFence]:
    """Return every top-level ```` ```mermaid ```` fence in *body_md*.

    Fences that open inside another fenced block are part of that block's
    content and are not reported. An unterminated fence runs to end of
    input per CommonMark, but is not reported either: rewriting it would
    swallow the rest of the document.
    """
    lines = body_md.split("\n")
    fences: list[MermaidFence] = []
    current: _OpenFence | None = None
    for idx, line in enumerate(lines):
        if current is None:
            current = _open_fence(line, idx)
        elif _closes(line, current):
            if current.mermaid:
                content = "\n".join(lines[current.start + 1 : idx])
                fences.append(MermaidFence(start=current.start, end=idx, content=content))
            current = None
    return fences


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _argv(exe: str, cfg: MermaidConfig, src: Path, out: Path) -> list[str]:
    # Plain substitution rather than ``str.format`` so a literal brace in a
    # user-supplied argument (``--configFile {…}``) cannot blow up the call.
    return [
        exe,
        *(a.replace("{input}", str(src)).replace("{output}", str(out)) for a in cfg.args),
    ]


def _run_command(exe: str, cfg: MermaidConfig, fence: MermaidFence, out: Path) -> bool:
    """Run the external renderer, writing *out*; ``False`` (with a warning) on failure."""
    src = out.with_name("diagram.mmd")
    src.write_text(fence.content + "\n", encoding="utf-8")
    try:
        proc = subprocess.run(
            _argv(exe, cfg, src, out),
            capture_output=True,
            text=True,
            check=False,
            timeout=_RENDER_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("mermaid renderer %r could not run for diagram %s: %s", exe, fence.sha, exc)
        return False
    if proc.returncode != 0 or not out.is_file():
        log.warning(
            "mermaid renderer %r failed for diagram %s (exit %d); leaving the fence as a "
            "code block: %s",
            exe,
            fence.sha,
            proc.returncode,
            proc.stderr.strip() or proc.stdout.strip(),
        )
        return False
    return True


def _run_mermaidx(fence: MermaidFence, out: Path) -> bool:
    """Render in-process with ``mermaidx``, writing *out*; ``False`` on failure.

    The import is deferred to here so the module loads without the optional
    extra; :class:`_Renderer` has already established that it is importable.
    mermaidx raises on a syntax error in the diagram, which is the per-fence
    failure that leaves that one fence as a code block.
    """
    import mermaidx  # noqa: PLC0415  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]

    try:
        diagram = mermaidx.render(fence.content)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        svg = str(diagram.svg())  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    except Exception as exc:  # a JS engine surfaces arbitrary error types
        log.warning(
            "mermaid renderer %r failed for diagram %s; leaving the fence as a code block: %s",
            MERMAIDX_RENDERER,
            fence.sha,
            exc,
        )
        return False
    out.write_text(svg, encoding="utf-8")
    return True


def _mermaidx_available() -> bool:
    try:
        import mermaidx  # noqa: F401, PLC0415  # pyright: ignore[reportMissingImports, reportMissingTypeStubs, reportUnusedImport]
    except ImportError:
        return False
    return True


class _Renderer:
    """Renders the unique diagrams of one page, resolving the renderer once.

    Every render goes through a temporary directory and the result is moved
    into place only on success, so a crash halfway never leaves a partial
    file that a later run would take for a cache hit.
    """

    def __init__(self, cfg: MermaidConfig, attachments_dir: Path) -> None:
        self._cfg = cfg
        self._dir = attachments_dir
        self._in_process = cfg.renderer == MERMAIDX_RENDERER
        self._exe: str | None = None
        self._looked_up = False
        self.missing = 0

    def _available(self) -> bool:
        """Whether the configured renderer can be used at all; looked up once."""
        if not self._looked_up:
            self._looked_up = True
            if self._in_process:
                self._exe = MERMAIDX_RENDERER if _mermaidx_available() else None
            else:
                self._exe = shutil.which(self._cfg.renderer)
        return self._exe is not None

    def _render(self, fence: MermaidFence, out: Path) -> bool:
        if self._in_process:
            return _run_mermaidx(fence, out)
        assert self._exe is not None  # noqa: S101 — guarded by _available()
        return _run_command(self._exe, self._cfg, fence, out)

    def svg_for(self, fence: MermaidFence) -> Path | None:
        """Path of the rendered SVG for *fence*, rendering on a cache miss."""
        dest = self._dir / f"mermaid-{fence.sha}.svg"
        if dest.is_file():
            return dest
        if not self._available():
            self.missing += 1
            return None
        with tempfile.TemporaryDirectory(prefix="mdd-mermaid-") as tmp:
            out = Path(tmp) / dest.name
            if not self._render(fence, out):
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            _ = shutil.move(out, dest)
        return dest

    def warn_if_missing(self) -> None:
        if not self.missing:
            return
        if self._in_process:
            log.warning(
                "mermaid renderer %r is not installed; %d diagram(s) left as code blocks; "
                "install with `uv add mdd[mermaid]` (or `pip install mermaidx`) or set "
                "mermaid.renderer to an external command",
                MERMAIDX_RENDERER,
                self.missing,
            )
            return
        log.warning(
            "mermaid renderer %r not found; %d diagram(s) left as code blocks; "
            "install @mermaid-js/mermaid-cli or set mermaid.renderer",
            self._cfg.renderer,
            self.missing,
        )


def _image_ref(svg_path: Path) -> str:
    # Relative to the source file's directory, which is what attachment sync
    # resolves image sources against. Percent-encoded so a page stem with a
    # space still parses as a single link destination.
    rel = f"{svg_path.parent.name}/{svg_path.name}"
    return f"![{_IMAGE_ALT}]({urllib.parse.quote(rel, safe='/')})"


def render_mermaid_fences(
    body_md: str,
    md_path: Path,
    *,
    config: MermaidConfig | None = None,
) -> str:
    """Return *body_md* with every renderable ```` ```mermaid ```` fence replaced by an image.

    Diagrams render into ``<stem>-attachments/`` beside *md_path*, named by
    content hash. Fences the renderer cannot handle — executable missing,
    non-zero exit, no output — are left exactly as written. The input text
    is never written back to *md_path*.
    """
    fences = find_mermaid_fences(body_md)
    if not fences:
        return body_md
    cfg = config if config is not None else load_mermaid_config()
    renderer = _Renderer(cfg, md_path.parent / f"{md_path.stem}-attachments")

    rendered: dict[str, Path | None] = {}
    lines = body_md.split("\n")
    # Splice back to front so earlier line indices stay valid.
    for fence in reversed(fences):
        if fence.sha not in rendered:
            rendered[fence.sha] = renderer.svg_for(fence)
        svg_path = rendered[fence.sha]
        if svg_path is not None:
            lines[fence.start : fence.end + 1] = [_image_ref(svg_path)]
    renderer.warn_if_missing()
    return "\n".join(lines)
