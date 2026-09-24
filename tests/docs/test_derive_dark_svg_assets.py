"""Tests for the active-content check in scripts/derive-dark-svg-assets.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "derive-dark-svg-assets.py"


def _load_derive_dark_svg_assets() -> ModuleType:
    spec = importlib.util.spec_from_file_location("derive_dark_svg_assets", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["derive_dark_svg_assets"] = module
    spec.loader.exec_module(module)
    return module


# Keep the module reference untyped rather than rebinding its members with
# explicit annotations; ModuleType attribute access resolves to Any, and a
# hand-written annotation here would declare the wrong type.
derive_dark_svg_assets = _load_derive_dark_svg_assets()

SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'
XLINK_NS = 'xmlns:xlink="http://www.w3.org/1999/xlink"'


def svg(body: str, extra: str = "") -> str:
    return f'<svg {SVG_NS} {XLINK_NS} {extra} viewBox="0 0 10 10">{body}</svg>'


def check(text: str) -> None:
    derive_dark_svg_assets.check_no_active_content(text, "test.svg")  # pyright: ignore[reportAny]


@pytest.mark.parametrize(
    "path",
    sorted((REPO_ROOT / "assets").glob("*.svg")),
    ids=lambda path: path.name,  # pyright: ignore[reportAny]
)
def test_the_committed_assets_pass(path: Path) -> None:
    check(path.read_text(encoding="utf-8"))


def test_plain_drawing_with_links_passes() -> None:
    check(
        svg(
            '<defs><path id="p" d="M0 0h1"/></defs>'
            '<use href="#p"/><use xlink:href="#p"/>'
            '<a href="https://example.com/"><text>ok</text></a>'
            '<animate attributeName="opacity" from="0" to="1"/>'
            "<style>.ink { fill: #333A40; }</style><!-- a comment -->"
        )
    )


def test_xml_declaration_passes() -> None:
    check('<?xml version="1.0" encoding="UTF-8"?>' + svg("<rect/>"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(svg("<script>alert(1)</script>"), "<script> element", id="script"),
        pytest.param(svg("<SCRIPT>alert(1)</SCRIPT>"), "<script> element", id="script-upper"),
        pytest.param(
            '<svg xmlns="http://www.w3.org/2000/svg"><s:script'
            ' xmlns:s="http://www.w3.org/2000/svg"/></svg>',
            "<script> element",
            id="script-prefixed",
        ),
        pytest.param(
            svg("<foreignObject><div>hi</div></foreignObject>"),
            "<foreignobject> element",
            id="foreign-object",
        ),
        pytest.param(svg("", extra='onload="go()"'), "event handler attribute onload", id="root"),
        pytest.param(
            svg("<rect onClick='go()'/>"), "event handler attribute onclick", id="mixed-case"
        ),
        pytest.param(
            svg('<a href="javascript:go()"><text>x</text></a>'), "links to a", id="href-js"
        ),
        pytest.param(
            svg('<a xlink:href="  JavaScript:go()"><text>x</text></a>'),
            "links to a",
            id="xlink-href-js-spaced",
        ),
        pytest.param(
            svg('<a href="java&#9;script:go()"><text>x</text></a>'),
            "links to a",
            id="href-js-tab",
        ),
        pytest.param(
            svg('<image href="data:image/svg+xml;base64,AAAA"/>'), "links to a", id="href-data"
        ),
        pytest.param(
            svg('<image xlink:href="DATA:text/html,x"/>'), "links to a", id="xlink-href-data"
        ),
        pytest.param(
            svg('<a><set attributeName="href" to="javascript:go()"/></a>'),
            "animates a link target",
            id="set-href",
        ),
        pytest.param(
            svg('<a><animate attributeName="xlink:href" values="#a;#b"/></a>'),
            "animates a link target",
            id="animate-xlink-href",
        ),
        pytest.param(
            svg('<a href="vbscript:go()"><text>x</text></a>'), "links to a", id="href-vbscript"
        ),
        pytest.param(svg('<image src="javascript:go()"/>'), "src links to a", id="src-js"),
        pytest.param(
            svg('<a xml:base="javascript:go()//" href="x"><text>x</text></a>'),
            "base links to a",
            id="xml-base-js",
        ),
        pytest.param(
            svg('<a><set attributeName="title" to=" javascript:go()"/></a>'),
            "to links to a",
            id="set-to-js",
        ),
        pytest.param(
            svg('<rect><set attributeName="onmouseover" to="go()"/></rect>'),
            "animates the event handler attribute onmouseover",
            id="set-event-handler",
        ),
        pytest.param(
            svg('<h:iframe xmlns:h="http://www.w3.org/1999/xhtml" src="page.html"/>'),
            "<iframe> element",
            id="xhtml-iframe",
        ),
        pytest.param(svg('<embed src="x"/>'), "<embed> element", id="embed"),
        pytest.param(svg('<object data="x"/>'), "<object> element", id="object"),
        pytest.param(svg("<handler>go()</handler>"), "<handler> element", id="handler"),
        pytest.param(
            '<?xml-stylesheet type="text/xsl" href="x.xsl"?>' + svg(""),
            "<?xml-stylesheet?> processing instruction",
            id="xml-stylesheet",
        ),
        pytest.param(svg("<?php echo 1 ?>"), "<?php?> processing instruction", id="nested-pi"),
        pytest.param(
            '<!DOCTYPE svg [<!ENTITY e "x">]>' + svg("<text>&e;</text>"),
            "<!DOCTYPE svg> declaration",
            id="doctype",
        ),
    ],
)
def test_active_content_is_refused(text: str, expected: str) -> None:
    with pytest.raises(SystemExit) as raised:
        check(text)
    message = str(raised.value)
    assert "test.svg" in message
    assert expected in message


def test_every_problem_is_listed() -> None:
    with pytest.raises(SystemExit) as raised:
        check(svg('<script/><rect onclick="x"/>'))
    message = str(raised.value)
    assert "<script> element" in message
    assert "onclick" in message


def test_malformed_input_fails_as_not_well_formed() -> None:
    with pytest.raises(SystemExit, match=r"test\.svg is not well-formed XML"):
        check("<svg><rect></svg>")


def test_derive_refuses_a_source_with_active_content(tmp_path: Path) -> None:
    source = tmp_path / "bad.svg"
    source.write_text(svg('<rect fill="#333A40" onclick="x"/>'), encoding="utf-8")
    with pytest.raises(SystemExit, match=r"bad\.svg contains content that runs code"):
        derive_dark_svg_assets.derive(source)  # pyright: ignore[reportAny]
    assert not (tmp_path / "bad-dark.svg").exists()


def test_derive_writes_a_clean_source(tmp_path: Path) -> None:
    source = tmp_path / "ok.svg"
    source.write_text(svg('<rect fill="#333A40"/>'), encoding="utf-8")
    written: list[Path] = derive_dark_svg_assets.derive(source)  # pyright: ignore[reportAny]
    assert written == [source, tmp_path / "ok-dark.svg"]
    assert "#FFEBD2" in (tmp_path / "ok-dark.svg").read_text(encoding="utf-8")
