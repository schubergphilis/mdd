"""Tests for prose.yaml discovery, severity precedence and validation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mdd.prose import config as prose_config
from mdd.prose.rules import DEFAULT_ENABLED, RULES, Severity, rules_for
from mdd.utils.config import ConfigError


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "prose.yaml"
    _ = path.write_text(body, encoding="utf-8")
    return path


def test_no_config_file_is_not_an_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    loaded = prose_config.load(None)
    assert loaded.enabled == frozenset(DEFAULT_ENABLED)
    assert loaded.source is None


def test_explicit_missing_config_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        _ = prose_config.load(tmp_path / "absent.yaml")


def test_cwd_config_wins_over_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "configs").mkdir()
    local = tmp_path / "configs" / "prose.yaml"
    _ = local.write_text("prose: {}\n", encoding="utf-8")
    home = tmp_path / "home" / ".config" / "mdd"
    home.mkdir(parents=True)
    _ = (home / "prose.yaml").write_text("prose: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert prose_config.find_config_file(None) == Path("configs") / "prose.yaml"


def test_home_config_is_used_when_there_is_no_local_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home" / ".config" / "mdd"
    home.mkdir(parents=True)
    expected = home / "prose.yaml"
    _ = expected.write_text("prose: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert prose_config.find_config_file(None) == expected


def test_checks_off_disables_the_check(tmp_path: Path) -> None:
    loaded = prose_config.load(write_config(tmp_path, "prose:\n  checks:\n    lint: off\n"))
    assert "lint" not in loaded.enabled
    assert "anchors" in loaded.enabled


def test_check_level_severity_replaces_every_rule_default(tmp_path: Path) -> None:
    loaded = prose_config.load(write_config(tmp_path, "prose:\n  checks:\n    lint: warning\n"))
    for rule in rules_for("lint"):
        assert loaded.severity(rule.rule) is Severity.WARNING


def test_rule_level_severity_beats_the_check_level(tmp_path: Path) -> None:
    loaded = prose_config.load(
        write_config(
            tmp_path,
            "prose:\n  checks:\n    lint: warning\n  lint:\n    rules:\n"
            "      invisible-space: error\n",
        )
    )
    assert loaded.severity("invisible-space") is Severity.ERROR
    assert loaded.severity("multiple-spaces") is Severity.WARNING


def test_off_check_cannot_be_re_enabled_by_a_rule(tmp_path: Path) -> None:
    loaded = prose_config.load(
        write_config(
            tmp_path,
            "prose:\n  checks:\n    lint: off\n  lint:\n    rules:\n      multiple-spaces: error\n",
        )
    )
    assert "lint" not in loaded.enabled


def test_reflow_and_freshness_are_off_until_configured(tmp_path: Path) -> None:
    loaded = prose_config.load(write_config(tmp_path, "prose: {}\n"))
    assert loaded.enabled == frozenset(DEFAULT_ENABLED)


def test_enabling_reflow(tmp_path: Path) -> None:
    loaded = prose_config.load(write_config(tmp_path, "prose:\n  checks:\n    reflow: error\n"))
    assert "reflow" in loaded.enabled


def test_reflow_knobs_and_merged_abbreviations(tmp_path: Path) -> None:
    loaded = prose_config.load(
        write_config(
            tmp_path,
            "prose:\n  reflow:\n    width: 80\n    min-line: 10\n"
            "    abbreviations: [Sect.]\n    single-letter-words: [I]\n",
        )
    )
    assert loaded.reflow.width == 80
    assert loaded.reflow.min_line == 10
    assert "Sect." in loaded.reflow.abbreviations
    assert "e.g." in loaded.reflow.abbreviations
    assert loaded.reflow.single_letter_words == frozenset({"I"})


def test_lint_knobs(tmp_path: Path) -> None:
    loaded = prose_config.load(
        write_config(
            tmp_path,
            "prose:\n  lint:\n    quote-punctuation: outside\n    allow-hard-break: false\n"
            "    literal-quote-patterns:\n      - '^-{1,2}[a-z]'\n",
        )
    )
    assert loaded.lint.quote_punctuation == "outside"
    assert not loaded.lint.allow_hard_break
    assert loaded.lint.literal_quote_patterns[0].pattern == "^-{1,2}[a-z]"


def test_freshness_knobs(tmp_path: Path) -> None:
    loaded = prose_config.load(
        write_config(tmp_path, "prose:\n  freshness:\n    field: reviewed\n    max-age-days: 30\n")
    )
    assert loaded.freshness.review_field == "reviewed"
    assert loaded.freshness.max_age_days == 30


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("prose:\n  checks:\n    nope: error\n", "not a known check"),
        ("prose:\n  checks:\n    lint: loud\n", "must be one of"),
        ("prose:\n  checks:\n    lint: 3\n", "must be one of"),
        ("prose:\n  lint:\n    rules:\n      nope: error\n", "not a known rule id"),
        ("prose:\n  reflow:\n    width: 0\n", "positive integer"),
        ("prose:\n  reflow:\n    abbreviations: 3\n", "list of strings"),
        ("prose:\n  reflow:\n    abbreviations: [3]\n", "list of strings"),
        ("prose:\n  lint:\n    quote-punctuation: sideways\n", "inside, outside or off"),
        ("prose:\n  lint:\n    allow-hard-break: maybe\n", "boolean"),
        ("prose:\n  lint:\n    literal-quote-patterns: ['(']\n", "not a valid regex"),
        ("prose:\n  anchors:\n    slug-style: gitlab\n", "must be github"),
        ("prose:\n  freshness:\n    field: ''\n", "non-empty string"),
        ("prose:\n  checks: 3\n", "must be a mapping"),
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, body: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        _ = prose_config.load(write_config(tmp_path, body))


def _config_rule_ids(text: str) -> set[str]:
    """Every rule id named under a `rules:` block in *text*."""
    found: set[str] = set()
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.strip() == "rules:":
            in_rules = True
            continue
        if in_rules and line.strip().endswith(":") and ":" in line:
            in_rules = False
        if in_rules and ":" in line:
            found.add(line.strip().split(":", 1)[0])
    return found


def test_every_rule_named_in_a_config_resolves_to_a_real_rule() -> None:
    """Declared-but-nonexistent rule ids are what rots first in a configurable linter.

    The earlier version of this test iterated ``RULES`` and asserted each member
    was in ``RULES`` — a tautology that could not fail. This walks the direction
    that matters: config → registry.
    """
    sample = Path("configs/prose.yaml")
    assert sample.is_file(), "the bundled configs/prose.yaml is the dogfooding config"
    named = _config_rule_ids(sample.read_text(encoding="utf-8"))
    unknown = named - set(RULES)
    assert not unknown, f"config names rules that do not exist: {sorted(unknown)}"


def test_every_registered_rule_has_a_check_that_can_configure_it() -> None:
    """The other direction: a rule nobody can reach from a config is dead weight."""
    from mdd.prose.rules import CHECK_NAMES, CROSS_CUTTING

    for rule in RULES.values():
        assert rule.check in (*CHECK_NAMES, CROSS_CUTTING), rule


def test_a_config_naming_an_unknown_rule_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not a known rule id"):
        _ = prose_config.load(
            write_config(tmp_path, "prose:\n  lint:\n    rules:\n      no-such-rule: error\n")
        )


def test_unknown_rule_resolves_to_error() -> None:
    assert prose_config.ProseConfig().severity("no-such-rule") is Severity.ERROR
