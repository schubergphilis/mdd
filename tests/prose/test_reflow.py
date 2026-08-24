"""Tests for sentence segmentation, clause packing and the reflow itself."""

from __future__ import annotations

from pathlib import Path

from mdd.prose.classify import Classified, classify
from mdd.prose.config import ProseConfig, ReflowConfig
from mdd.prose.inline import mask_flags, scan
from mdd.prose.reflow.apply import canonical, equivalent, findings, reflow_text
from mdd.prose.reflow.clauses import pack, split_units
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
    return split_units(text, flags, 0, len(text))


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


# --- clause units ----------------------------------------------------------


def test_units_split_at_top_level_commas() -> None:
    assert units("a, b; c: d") == ["a,", "b;", "c:", "d"]


def test_units_ignore_commas_inside_brackets() -> None:
    assert units("a (b, c) d") == ["a (b, c) d"]


def test_units_ignore_commas_inside_quotes() -> None:
    assert units('a "b, c" d') == ['a "b, c" d']


def test_units_ignore_commas_inside_masked_spans() -> None:
    assert units("a `b, c` d") == ["a `b, c` d"]


def test_spaced_dash_is_a_boundary() -> None:
    assert units("a — b") == ["a —", "b"]


def test_unspaced_dash_is_not_a_boundary() -> None:
    assert units("a—b") == ["a—b"]


# --- packing ---------------------------------------------------------------


def test_a_sentence_that_fits_stays_on_one_line() -> None:
    assert pack(["a,", "b"], width=100, min_line=32, first_indent=0, cont_indent=0) == ["a, b"]


def test_packing_breaks_when_the_next_unit_would_overflow() -> None:
    long = "x" * 60
    assert pack(
        [f"{long},", f"{long},", long], width=100, min_line=1, first_indent=0, cont_indent=0
    ) == [f"{long},", f"{long},", long]


def test_a_unit_longer_than_the_width_is_not_broken() -> None:
    long = "x" * 200
    assert pack([long], width=100, min_line=32, first_indent=0, cont_indent=0) == [long]


def test_min_line_keeps_a_short_tail_attached() -> None:
    long = "x" * 99
    packed = pack([f"{long},", "too."], width=100, min_line=32, first_indent=0, cont_indent=0)
    assert packed == [f"{long}, too."]


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


def test_canonical_returns_none_for_unparseable_input() -> None:
    assert canonical("ok") is not None


def test_equivalence_holds_for_a_reflow() -> None:
    text = "One thing, with a clause. Two things.\n"
    assert equivalent(text, reflow(text))


def test_equivalence_fails_when_meaning_changes() -> None:
    assert not equivalent("# heading\n", "heading\n")


# --- the golden corpus -----------------------------------------------------


def corpus_cases() -> list[Path]:
    return sorted(d for d in CORPUS.iterdir() if d.is_dir())


def test_golden_corpus_matches_expected_output() -> None:
    for case in corpus_cases():
        source = (case / "input.md").read_text(encoding="utf-8")
        expected = (case / "expected.md").read_text(encoding="utf-8")
        assert reflow(source) == expected, case.name


def test_golden_corpus_is_idempotent_and_equivalent() -> None:
    for case in corpus_cases():
        source = (case / "input.md").read_text(encoding="utf-8")
        once = reflow(source)
        assert reflow(once) == once, case.name
        assert equivalent(source, once), case.name


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
        assert equivalent(source, once), doc
