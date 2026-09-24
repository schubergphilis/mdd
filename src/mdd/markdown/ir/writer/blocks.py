"""Block-level rendering for the IR → markdown writer."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, cast

from mdd.ir.nodes import (
    Block,
    BlockQuote,
    BulletList,
    Callout,
    CodeBlock,
    ConfluenceMacro,
    Heading,
    HorizontalRule,
    Layout,
    OrderedList,
    Paragraph,
    RawBlock,
    Table,
)

from .escape import escape_attr, render_attr_dict
from .inlines import render_inlines
from .table import render_table

if TYPE_CHECKING:
    from mdd.ir.nodes import LayoutCell, LayoutSection


# A run of ``#`` at the end of an ATX heading line, preceded by whitespace
# (or standing alone), is the optional closing sequence and is dropped by
# the reader. Escaping its first ``#`` keeps it as heading text.
_HEADING_CLOSE_RE = re.compile(r"(?:(?<=\s)|^)(#+)\s*$")


def _render_heading(
    block: Heading,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    out.append(f"{indent}{'#' * block.level} ")
    body: list[str] = []
    render_inlines(block.inlines, body, mode=mode)
    out.append(_HEADING_CLOSE_RE.sub(r"\\\1", "".join(body), count=1))


def _render_paragraph(
    block: Paragraph,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    out.append(indent)
    render_inlines(block.inlines, out, mode=mode, line_start=True)


def _render_bullet_list(
    block: BulletList,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    for i, item in enumerate(block.items):
        if i > 0:
            out.append("\n")
        task = item.attributes.get("task")
        if task == "done":
            out.append(f"{indent}- [x] ")
        elif task == "open":
            out.append(f"{indent}- [ ] ")
        else:
            out.append(f"{indent}- ")
        render_list_item_children(item.children, out, indent=indent + "  ", mode=mode)


def _render_ordered_list(
    block: OrderedList,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    for i, item in enumerate(block.items):
        if i > 0:
            out.append("\n")
        num = block.start + i
        marker = f"{num}. "
        out.append(f"{indent}{marker}")
        render_list_item_children(item.children, out, indent=indent + " " * len(marker), mode=mode)


def _render_blockquote(
    block: BlockQuote,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    inner: list[str] = []
    for i, child in enumerate(block.children):
        if i > 0:
            inner.append("\n\n")
        render_block(child, inner, indent="", mode=mode)
    body = "".join(inner)
    for j, line in enumerate(body.split("\n")):
        if j > 0:
            out.append("\n")
        out.append(f"{indent}> {line}" if line else f"{indent}>")


def _render_horizontal_rule(
    block: HorizontalRule,  # noqa: ARG001
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    out.append(f"{indent}---")


def fence_for(body: str, char: str, *, minimum: int = 3) -> str:
    """Return a run of *char* that no line of *body* can be mistaken for.

    A line whose leading run of *char* (after optional indentation) is at
    least as long as the opening fence would close it early, so the fence
    is made one longer than the longest such run in the body.
    """
    longest = 0
    for line in body.splitlines():
        m = re.match(rf"\s*({re.escape(char)}+)", line)
        if m:
            longest = max(longest, len(m.group(1)))
    return char * max(minimum, longest + 1)


def _container_fence(body: list[str], fence_depth: int) -> str:
    """Return the ``:`` fence for a container whose rendered body is *body*.

    The reader closes a fenced div on the first line that is exactly its
    opening fence, so the fence is the shortest run of at least
    ``3 + fence_depth`` colons that no body line consists of. Nested
    containers keep their longer depth-based fences; only a colon line
    inside a code fence or plain-text body pushes the parent further.
    """
    taken = {
        len(stripped)
        for line in "".join(body).split("\n")
        if (stripped := line.strip()) and not stripped.strip(":")
    }
    length = 3 + fence_depth
    while length in taken:
        length += 1
    return ":" * length


# A code fence whose info string is ``confluence-xml`` is read back as
# raw storage markup, never as a code block.
_RAW_FENCE_INFO = "confluence-xml"


def _fence_info(language: str | None) -> str:
    """Reduce *language* to a single word that cannot alter the fence line.

    The info string ends at the first whitespace, and a backtick fence's
    info string may not contain backticks. The word reserved for raw
    storage fences is dropped so a code block stays a code block.
    """
    if not language:
        return ""
    words = language.split()
    word = words[0].replace("`", "") if words else ""
    return "" if word == _RAW_FENCE_INFO else word


def _render_code_block(
    block: CodeBlock,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",  # noqa: ARG001
) -> None:
    fence = fence_for(block.content, "`")
    out.append(f"{indent}{fence}{_fence_info(block.language)}\n")
    for line in block.content.splitlines():
        out.append(f"{indent}{line}\n")  # noqa: PERF401
    # `splitlines()` drops the trailing newline if present, so a
    # content that ends in `\n` and one that doesn't both produce the
    # same body. Emit an extra blank line when content ends in `\n`
    # to keep the round-trip distinguishable — the markdown reader
    # sees the trailing blank as part of the code body.
    if block.content.endswith("\n"):
        out.append(f"{indent}\n")
    out.append(f"{indent}{fence}")


def _render_table(
    block: Table,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    render_table(block, out, indent=indent, mode=mode)


def _render_callout(
    block: Callout,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
    fence_depth: int = 0,
) -> None:
    param_str = render_attr_dict(block.params)
    body: list[str] = []
    for i, child in enumerate(block.body):
        if i > 0:
            body.append("\n\n")
        render_block(child, body, indent=indent, mode=mode, fence_depth=fence_depth + 1)
    fence = _container_fence(body, fence_depth)
    head = f"{fence}callout-{block.kind}"
    if param_str:
        head += f" {{{param_str}}}"
    out.append(f"{indent}{head}\n")
    out.extend(body)
    # Blank line before the close fence so the markdown reader's
    # fenced-div plugin terminates the block cleanly instead of
    # absorbing the literal close fence into the trailing paragraph.
    out.append(f"\n\n{indent}{fence}")


def _render_confluence_macro(
    block: ConfluenceMacro,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
    fence_depth: int = 0,
) -> None:
    params = dict(block.params)
    params["name"] = block.name
    param_str = render_attr_dict(params)
    body: list[str] = []
    if block.rich_body:
        for i, child in enumerate(block.body):
            if i > 0:
                body.append("\n\n")
            render_block(child, body, indent=indent, mode=mode, fence_depth=fence_depth + 1)
    elif block.plain_body is not None:
        for line in block.plain_body.splitlines():
            body.append(f"{indent}{line}\n")  # noqa: PERF401
    fence = _container_fence(body, fence_depth)
    out.append(f"{indent}{fence}confluence-macro {{{param_str}}}\n")
    out.extend(body)
    # Same blank-line-before-close-fence as Callout — see comment there.
    out.append(f"\n\n{indent}{fence}")


def _render_raw_block(
    block: RawBlock,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    # If the reader truncated raw_bytes (it exceeded ORIGIN_RAW_BYTES_CAP),
    # fall through to the canonical render below.
    if (
        mode == "preserving"
        and block.origin is not None
        and block.origin.raw_bytes
        and not block.origin.raw_bytes_truncated
    ):
        out.append(block.origin.raw_bytes.decode("utf-8"))
        return
    if block.format == "markdown":
        out.append(block.content)
        return
    if block.format == "html":
        out.append(block.content)
        return
    # confluence-storage and any other format → confluence-xml fence
    fence = fence_for(block.content, "`")
    out.append(f"{indent}{fence}confluence-xml\n")
    for line in block.content.splitlines():
        out.append(f"{indent}{line}\n")  # noqa: PERF401
    out.append(f"{indent}{fence}")


def _render_layout(
    block: Layout,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
    fence_depth: int = 0,
) -> None:
    body: list[str] = []
    for sec in block.sections:
        body.append("\n")
        render_layout_section(sec, body, indent=indent, mode=mode, fence_depth=fence_depth + 1)
    fence = _container_fence(body, fence_depth)
    out.append(f"{indent}{fence}layout")
    out.extend(body)
    out.append(f"\n{indent}{fence}")


# Dispatch table mirroring the peer Confluence-storage writer
# (``mdd/confluence/ir/writer/blocks.py``): one ``_render_<kind>`` helper
# per ``Block`` subtype. Adding a new ``Block`` kind is a one-line table
# entry plus a per-kind helper — the dispatcher itself never changes.
_BLOCK_RENDERERS: dict[type, object] = {
    Heading: _render_heading,
    Paragraph: _render_paragraph,
    BulletList: _render_bullet_list,
    OrderedList: _render_ordered_list,
    BlockQuote: _render_blockquote,
    HorizontalRule: _render_horizontal_rule,
    CodeBlock: _render_code_block,
    Table: _render_table,
    Callout: _render_callout,
    ConfluenceMacro: _render_confluence_macro,
    RawBlock: _render_raw_block,
    Layout: _render_layout,
}


# Block types whose renderer accepts a ``fence_depth`` kwarg. Other (leaf)
# renderers have a plain ``(block, out, *, indent, mode)`` signature.
_CONTAINER_BLOCKS: frozenset[type] = frozenset({Callout, ConfluenceMacro, Layout})


def render_block(
    block: Block,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
    fence_depth: int = 0,
) -> None:
    renderer = _BLOCK_RENDERERS.get(type(block))
    if renderer is None:
        # By exhaustion no Block subtype is missing from _BLOCK_RENDERERS;
        # this branch exists only for defensive parity with the Confluence
        # writer's RawBlock-fallthrough shape.
        _render_raw_block(cast("RawBlock", block), out, indent=indent, mode=mode)
        return
    # Only container-shaped renderers accept fence_depth; pass it via a
    # kwarg so the leaf renderers (heading, paragraph, etc.) can ignore it.
    if type(block) in _CONTAINER_BLOCKS:
        renderer(block, out, indent=indent, mode=mode, fence_depth=fence_depth)  # pyright: ignore[reportCallIssue]
    else:
        renderer(block, out, indent=indent, mode=mode)  # pyright: ignore[reportCallIssue]


def render_layout_section(
    section: LayoutSection,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
    fence_depth: int = 1,
) -> None:
    body: list[str] = []
    for cell in section.cells:
        body.append("\n")
        render_layout_cell(cell, body, indent=indent, mode=mode, fence_depth=fence_depth + 1)
    fence = _container_fence(body, fence_depth)
    out.append(f'{indent}{fence}layout-section layout_type="{escape_attr(section.layout_type)}"')
    out.extend(body)
    out.append(f"\n{indent}{fence}")


def render_layout_cell(
    cell: LayoutCell,
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
    fence_depth: int = 2,
) -> None:
    body: list[str] = []
    for i, child in enumerate(cell.children):
        if i > 0:
            body.append("\n\n")
        render_block(child, body, indent=indent, mode=mode, fence_depth=fence_depth + 1)
    fence = _container_fence(body, fence_depth)
    # Blank lines around the inner block content keep the cell content from
    # being lazily absorbed into a paragraph that swallows the closing fence.
    out.append(f"{indent}{fence}layout-cell\n\n")
    out.extend(body)
    out.append(f"\n\n{indent}{fence}")


def render_list_item_children(
    children: list[Block],
    out: list[str],
    *,
    indent: str,
    mode: Literal["normalising", "preserving"] = "normalising",
) -> None:
    for i, child in enumerate(children):
        if i == 0:
            render_block(child, out, indent="", mode=mode)
        else:
            out.append("\n\n")
            render_block(child, out, indent=indent, mode=mode)
