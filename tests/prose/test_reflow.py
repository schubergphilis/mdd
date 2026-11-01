"""Tests for sentence segmentation, clause packing and the reflow itself."""

from __future__ import annotations

from pathlib import Path

from mdd.prose.classify import Classified, classify
from mdd.prose.config import ProseConfig, ReflowConfig
from mdd.prose.gate import verify
from mdd.prose.inline import mask_flags, scan
from mdd.prose.reflow.apply import findings, reflow_text
from mdd.prose.reflow.clauses import Unit, pack, split_units
from mdd.prose.reflow.sentences import segment
from mdd.prose.rules import RULES

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "prose"


def ok(text: str) -> Classified:
    result = classify(text)
    assert isinstance(result, Classified)
    return result


def sentences(text: str, config: ReflowConfig | None = None) -> list[str]:
    flags = mask_flags(len(text), scan(text).masks)
    return [text[s.start : s.end] for s in segment(text, flags, config or ReflowConfig())]


def units(text: str) -> list[str]:
    flags = mask_flags(len(text), scan(text).masks)
    return [unit.text for unit in split_units(text, flags, 0, len(text))]


def packed(texts: list[str], **kwargs: int) -> list[str]:
    """Pack *texts* as units separated by single spaces, returning the line texts."""
    given = [Unit(gap="" if index == 0 else " ", text=t) for index, t in enumerate(texts)]
    return [line.text for line in pack(given, **kwargs)]


def reflow(text: str, **kwargs: int) -> str:
    return reflow_text(ok(text), ReflowConfig(**kwargs)).text  # pyright: ignore[reportArgumentType]


# --- sentence segmentation -------------------------------------------------


def test_two_plain_sentences() -> None:
    assert sentences("One thing. Two things.") == ["One thing.", "Two things."]


def test_abbreviation_does_not_end_a_sentence() -> None:
    assert sentences("Tools, e.g. rg, are fast. Done.") == ["Tools, e.g. rg, are fast.", "Done."]


def test_project_abbreviation_is_merged_in() -> None:
    config = ReflowConfig(abbreviations=ReflowConfig().abbreviations | {"Sect."})
    assert sentences("See Sect. 4 now.", config) == ["See Sect. 4 now."]


def test_initial_does_not_end_a_sentence() -> None:
    assert sentences("W. Somerset Maugham wrote it.") == ["W. Somerset Maugham wrote it."]


def test_single_letter_word_does_end_a_sentence() -> None:
    config = ReflowConfig(single_letter_words=frozenset({"A"}))
    assert sentences("The grade was A. Next term.", config) == ["The grade was A.", "Next term."]


def test_version_number_does_not_end_a_sentence() -> None:
    assert sentences("Use v1.2.3 now. Done.") == ["Use v1.2.3 now.", "Done."]


def test_ellipsis_does_not_end_a_sentence() -> None:
    assert sentences("Wait... then go.") == ["Wait... then go."]


def test_lowercase_next_word_is_not_a_boundary() -> None:
    assert sentences("a.b. still one") == ["a.b. still one"]


def test_terminator_inside_a_masked_span_is_ignored() -> None:
    assert sentences("Run `a. b` now. Done.") == ["Run `a. b` now.", "Done."]


def test_exclamation_and_question_marks() -> None:
    assert sentences("Really?! Yes.") == ["Really?!", "Yes."]


def test_empty_text_has_no_sentences() -> None:
    assert sentences("") == []


def test_no_sentence_break_inside_straight_quotes() -> None:
    text = 'He said "Stop. Now." and left. Next.'
    assert sentences(text) == ['He said "Stop. Now." and left.', "Next."]


def test_no_sentence_break_inside_curly_quotes() -> None:
    text = "He said \u201cStop. Now.\u201d and left. Next."
    assert sentences(text) == ["He said \u201cStop. Now.\u201d and left.", "Next."]


def test_no_sentence_break_inside_guillemets() -> None:
    text = "Il dit \u00abStop. Maintenant.\u00bb et part. Fin."
    assert sentences(text) == ["Il dit \u00abStop. Maintenant.\u00bb et part.", "Fin."]


def test_no_sentence_break_inside_parentheses() -> None:
    text = "It works (see the guide. It is short) as shown. Next."
    assert sentences(text) == ["It works (see the guide. It is short) as shown.", "Next."]


def test_apostrophes_are_not_quote_delimiters() -> None:
    text = "It's done. The tools\u2019 output is fine. Next."
    assert sentences(text) == ["It's done.", "The tools\u2019 output is fine.", "Next."]


def test_an_unclosed_quote_does_not_suppress_breaks() -> None:
    assert sentences("One. He said \u201cStop. Now.") == ["One.", "He said \u201cStop.", "Now."]


def test_an_unopened_quote_does_not_suppress_breaks() -> None:
    text = "Stop. Now.\u201d He left. Next."
    assert sentences(text) == ["Stop.", "Now.\u201d He left.", "Next."]


def test_a_stray_straight_quote_does_not_suppress_breaks() -> None:
    text = 'Start. The screen is 5" wide. He said "Stop. Now." and left. Next.'
    assert sentences(text) == [
        "Start.",
        'The screen is 5" wide.',
        'He said "Stop. Now." and left.',
        "Next.",
    ]


def test_an_unclosed_straight_quote_does_not_suppress_breaks() -> None:
    text = 'A "b. C" d. E "f. G.'
    assert sentences(text) == ['A "b. C" d.', 'E "f.', "G."]


def test_an_enumeration_closer_does_not_suppress_breaks() -> None:
    text = "Pick a) the first. Or b) the second. Done."
    assert sentences(text) == ["Pick a) the first.", "Or b) the second.", "Done."]


def test_a_closer_of_another_kind_does_not_close_a_pair() -> None:
    text = "It works (see a] here. It is short) as shown. Next."
    assert sentences(text) == ["It works (see a] here. It is short) as shown.", "Next."]


def test_quote_inside_a_masked_span_does_not_open_a_quotation() -> None:
    assert sentences('Run `"` now. Done.') == ['Run `"` now.', "Done."]


def test_reflow_keeps_a_quoted_passage_on_one_line() -> None:
    text = 'Intro sentence here. He said "Stop. Now." and left.\n'
    assert reflow(text) == 'Intro sentence here.\nHe said "Stop. Now." and left.\n'


def test_reflow_keeps_whitespace_between_units_on_one_line() -> None:
    text = "A short line,  with two spaces;\tand a tab.\n"
    assert reflow(text) == text


def test_reflow_keeps_whitespace_where_a_block_starter_is_merged_back() -> None:
    text = "First sentence.\n\nSecond sentence.  - not a list item.\n"
    assert reflow(text) == text


def test_reflow_replaces_only_the_whitespace_at_a_break() -> None:
    long = "word " * 18
    text = f"{long.strip()},  then  more words here to finish.\n"
    assert reflow(text, width=60, min_line=1) == (
        f"{long.strip()},\nthen  more words here to finish.\n"
    )


def test_reflow_with_wide_gaps_is_idempotent() -> None:
    long = "word " * 18
    text = f"{long.strip()},  then  more words,   and a tail that runs on. Next.\n"
    once = reflow(text, width=60, min_line=1)
    assert reflow(once, width=60, min_line=1) == once


def test_reflow_joins_lazy_and_indented_continuation_lines() -> None:
    cases = {
        "> quoted text\nlazy continuation.\n": "> quoted text lazy continuation.\n",
        "- item one\n      continued here.\n": "- item one continued here.\n",
    }
    for source, expected in cases.items():
        assert reflow(source) == expected
        assert verify(source, expected).passed


# --- clause units ----------------------------------------------------------


def test_units_split_at_top_level_commas() -> None:
    assert units("a, b; c: d") == ["a,", "b;", "c:", "d"]


def test_units_ignore_commas_inside_brackets() -> None:
    assert units("a (b, c) d") == ["a (b, c) d"]


def test_units_ignore_commas_inside_quotes() -> None:
    assert units('a "b, c" d') == ['a "b, c" d']


def test_units_ignore_commas_inside_masked_spans() -> None:
    assert units("a `b, c` d") == ["a `b, c` d"]


def test_units_ignore_commas_inside_curly_quotes() -> None:
    assert units("a \u201cb, c\u201d, d") == ["a \u201cb, c\u201d,", "d"]


def test_units_ignore_an_unmatched_quote() -> None:
    assert units("a, b\u201d c, d") == ["a,", "b\u201d c,", "d"]


def test_spaced_dash_is_a_boundary() -> None:
    assert units("a — b") == ["a —", "b"]


def test_unspaced_dash_is_not_a_boundary() -> None:
    assert units("a—b") == ["a—b"]


# --- packing ---------------------------------------------------------------


def test_a_sentence_that_fits_stays_on_one_line() -> None:
    assert packed(["a,", "b"], width=100, min_line=32, first_indent=0, cont_indent=0) == ["a, b"]


def test_packing_breaks_when_the_next_unit_would_overflow() -> None:
    long = "x" * 60
    assert packed(
        [f"{long},", f"{long},", long], width=100, min_line=1, first_indent=0, cont_indent=0
    ) == [f"{long},", f"{long},", long]


def test_a_unit_longer_than_the_width_is_not_broken() -> None:
    long = "x" * 200
    assert packed([long], width=100, min_line=32, first_indent=0, cont_indent=0) == [long]


def test_min_line_keeps_a_short_tail_attached() -> None:
    long = "x" * 99
    lines = packed([f"{long},", "too."], width=100, min_line=32, first_indent=0, cont_indent=0)
    assert lines == [f"{long}, too."]


def test_packing_keeps_the_gap_between_units_on_one_line() -> None:
    given = [Unit(gap="", text="a,"), Unit(gap="\t ", text="b")]
    lines = pack(given, width=100, min_line=1, first_indent=0, cont_indent=0)
    assert [(line.gap, line.text) for line in lines] == [("", "a,\t b")]


def test_units_carry_the_whitespace_before_them() -> None:
    text = "a,  b;\tc"
    flags = mask_flags(len(text), scan(text).masks)
    found = split_units(text, flags, 0, len(text))
    assert [(unit.gap, unit.text) for unit in found] == [("", "a,"), ("  ", "b;"), ("\t", "c")]


def test_packing_nothing_yields_nothing() -> None:
    assert pack([], width=100, min_line=32, first_indent=0, cont_indent=0) == []


# --- whole-file reflow -----------------------------------------------------


def test_one_sentence_per_line() -> None:
    assert reflow("One thing. Two things.\n") == "One thing.\nTwo things.\n"


def test_hard_wrapped_paragraph_is_rejoined() -> None:
    assert reflow("One\nthing.\n") == "One thing.\n"


def test_headings_are_never_broken() -> None:
    heading = "# " + "word " * 40
    assert reflow(heading + "\n") == heading + "\n"


def test_code_and_tables_are_untouched() -> None:
    text = "```\na. b. c.\n```\n\n| a. b. | c |\n|---|---|\n| 1 | 2 |\n"
    assert reflow(text) == text


def test_hard_break_block_is_left_alone() -> None:
    text = "a  \nb. c.\n"
    assert reflow(text) == text


def test_final_newline_absence_is_preserved() -> None:
    assert reflow("One thing. Two.") == "One thing.\nTwo."


def test_crlf_is_preserved() -> None:
    assert reflow("One thing. Two.\r\n") == "One thing.\r\nTwo.\r\n"


def test_changed_lines_are_reported() -> None:
    result = reflow_text(ok("a\n\nOne. Two.\n"), ReflowConfig())
    assert result.changed == (3,)


def test_findings_name_the_block_start() -> None:
    doc = ok("One. Two.\n")
    result = reflow_text(doc, ReflowConfig())
    config = ProseConfig(severities={rule.rule: rule.default for rule in RULES.values()})
    found = findings(Path("a.md"), doc, config, result)
    assert [(f.rule, f.line, f.fixable) for f in found] == [("reflow", 1, True)]


def test_equivalence_holds_for_a_reflow() -> None:
    text = "One thing, with a clause. Two things.\n"
    assert verify(text, reflow(text)).passed


def test_equivalence_fails_when_meaning_changes() -> None:
    assert not verify("# heading\n", "heading\n").passed


# --- the golden corpus -----------------------------------------------------


def corpus_cases() -> list[Path]:
    return sorted(d for d in CORPUS.iterdir() if d.is_dir())


def read_exact(path: Path) -> str:
    """Read *path* without newline translation, so a CRLF fixture stays CRLF."""
    return path.read_bytes().decode("utf-8")


def test_golden_corpus_matches_expected_output() -> None:
    """Byte for byte: a fixture's line endings are part of what it asserts."""
    for case in corpus_cases():
        source = read_exact(case / "input.md")
        expected = read_exact(case / "expected.md")
        assert reflow(source).encode("utf-8") == expected.encode("utf-8"), case.name


def test_golden_crlf_fixture_is_stored_with_crlf() -> None:
    """Git must not normalise the CRLF fixture, or the golden test proves nothing."""
    for name in ("input.md", "expected.md"):
        data = (CORPUS / "crlf" / name).read_bytes()
        assert b"\r\n" in data, name
        assert b"\n" not in data.replace(b"\r\n", b""), name


def test_golden_corpus_is_idempotent_and_equivalent() -> None:
    for case in corpus_cases():
        source = read_exact(case / "input.md")
        once = reflow(source)
        assert reflow(once) == once, case.name
        assert verify(source, once).passed, case.name


def _sweep(paths: list[Path], label: str) -> int:
    """Assert idempotence and equivalence over every classifiable file in *paths*."""
    seen = 0
    for doc in paths:
        source = doc.read_text(encoding="utf-8")
        parsed = classify(source)
        if not isinstance(parsed, Classified):
            continue
        seen += 1
        once = reflow_text(parsed, ReflowConfig()).text
        again = classify(once)
        assert isinstance(again, Classified), f"{label}: {doc} did not re-classify"
        assert reflow_text(again, ReflowConfig()).text == once, f"{label}: {doc} not idempotent"
        assert verify(source, once).passed, f"{label}: {doc} not equivalent"
    return seen


def test_ir_corpus_reflows_idempotently_and_equivalently() -> None:
    """The vendored IR corpus is the most hostile Markdown in the repository.

    It exercises every construct the IR knows, which is why the reflow is tested
    against it. An earlier version of this test used ``docs/`` instead, which is
    tidy prose and hid a whole class of defect — fenced divs, among others.
    """
    corpus = Path(__file__).resolve().parents[1] / "corpus" / "confluence"
    docs = sorted(corpus.rglob("*.md"))
    assert docs, "expected the vendored IR corpus to be present"
    assert _sweep(docs, "ir-corpus") > 0


def test_repository_docs_reflow_idempotently_and_equivalently() -> None:
    docs = sorted((Path(__file__).resolve().parents[2] / "docs").rglob("*.md"))
    assert docs, "expected the repository's own docs corpus to be present"
    for doc in docs:
        source = doc.read_text(encoding="utf-8")
        parsed = classify(source)
        if not isinstance(parsed, Classified):
            continue
        once = reflow_text(parsed, ReflowConfig()).text
        again = classify(once)
        assert isinstance(again, Classified), doc
        assert reflow_text(again, ReflowConfig()).text == once, doc
        assert verify(source, once).passed, doc


def test_reflow_does_not_break_inside_preformatted_inline_html() -> None:
    text = (
        "To log out of the locked workstation quickly, press <kbd>Ctrl, Alt, Delete</kbd> "
        "and then choose the sign out option from the menu that appears.\n"
    )
    once = reflow(text, width=60, min_line=1)
    assert "<kbd>Ctrl, Alt, Delete</kbd>" in once
    assert verify(text, once).passed


#: Text that opens a block when it starts a line. Reflow must never move one
#: of these to the start of a line.
BLOCK_STARTERS = (
    "***",
    "___",
    "* * *",
    "- - -",
    "_ _ _",
    "---",
    "===",
    "--",
    "-",
    "+",
    "*",
    "- x.",
    "+ x.",
    "* x.",
    "1. x.",
    "1) x.",
    "# x.",
    "> x.",
    "```",
    "~~~",
    "<div>",
    "<!-- x -->",
    "| a |",
    "$$",
    ":::",
    "::: note",
    "[^x]: y.",
    "[x]: /u",
    "[a\\]b]: /u",
    "--- | ---",
    "-- | --",
    ":-- | --:",
)


def test_reflow_never_starts_a_line_with_a_block_starter() -> None:
    for starter in BLOCK_STARTERS:
        for lead in ("Fill in every field marked with a line.", "a | b and one."):
            text = f"{lead} {starter}\n"
            once = reflow(text)
            assert once == text, (starter, once)
            assert verify(text, once).passed, starter
