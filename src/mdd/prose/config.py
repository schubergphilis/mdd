"""``prose.yaml`` discovery and the resolved, frozen prose configuration.

Discovery is the per-domain shape every other config in ``mdd`` uses:
explicit ``--config PATH`` (an error if missing), then ``./configs/prose.yaml``,
then ``~/.config/mdd/prose.yaml``. First hit wins; there is no merging across
locations, because a style config must state a repository's whole house style
in one file a reviewer can read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from mdd.prose.rules import (
    CHECK_NAMES,
    CROSS_CUTTING,
    DEFAULT_ENABLED,
    RULES,
    Severity,
    rules_for,
)
from mdd.utils.config import ConfigError, load_yaml

_CONFIG_NAME = "prose.yaml"

DEFAULT_WIDTH = 100
DEFAULT_MIN_LINE = 32
DEFAULT_MAX_AGE_DAYS = 180
DEFAULT_REVIEW_FIELD = "last-verified"

#: Shipped abbreviations whose trailing period never ends a sentence. A
#: project's list is merged into this, never substituted for it.
DEFAULT_ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "e.g.",
        "i.e.",
        "cf.",
        "etc.",
        "vs.",
        "viz.",
        "al.",
        "ca.",
        "approx.",
        "est.",
        "Dr.",
        "Mr.",
        "Mrs.",
        "Ms.",
        "Prof.",
        "Sr.",
        "Jr.",
        "St.",
        "Fig.",
        "No.",
        "Ch.",
        "Sec.",
        "Vol.",
        "pp.",
        "Inc.",
        "Ltd.",
        "Co.",
        "Jan.",
        "Feb.",
        "Mar.",
        "Apr.",
        "Jun.",
        "Jul.",
        "Aug.",
        "Sep.",
        "Sept.",
        "Oct.",
        "Nov.",
        "Dec.",
    }
)

QuoteConvention = Literal["inside", "outside", "off"]


@dataclass(frozen=True)
class ReflowConfig:
    """Knobs for the semantic-line-break reflow."""

    width: int = DEFAULT_WIDTH
    min_line: int = DEFAULT_MIN_LINE
    abbreviations: frozenset[str] = DEFAULT_ABBREVIATIONS
    single_letter_words: frozenset[str] = frozenset()


@dataclass(frozen=True)
class LintConfig:
    """Knobs for the mechanical lint."""

    quote_punctuation: QuoteConvention = "inside"
    allow_hard_break: bool = True
    literal_quote_patterns: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True)
class AnchorsConfig:
    """Knobs for the anchor resolver."""

    slug_style: Literal["github"] = "github"


@dataclass(frozen=True)
class FreshnessConfig:
    """Knobs for the freshness gate."""

    review_field: str = DEFAULT_REVIEW_FIELD
    max_age_days: int = DEFAULT_MAX_AGE_DAYS


@dataclass(frozen=True)
class ProseConfig:
    """The resolved configuration every check consumes."""

    enabled: frozenset[str] = frozenset(DEFAULT_ENABLED)
    severities: dict[str, Severity] = field(default_factory=dict)
    reflow: ReflowConfig = ReflowConfig()
    lint: LintConfig = LintConfig()
    anchors: AnchorsConfig = AnchorsConfig()
    freshness: FreshnessConfig = FreshnessConfig()

    def severity(self, rule: str) -> Severity:
        """Return the resolved severity for *rule*."""
        known = self.severities.get(rule)
        if known is not None:
            return known
        registered = RULES.get(rule)
        return registered.default if registered is not None else Severity.ERROR


def find_config_file(explicit: Path | None) -> Path | None:
    """Return the ``prose.yaml`` to load, or ``None`` when there is none.

    Raises ConfigError when *explicit* is given but does not exist.
    """
    if explicit is not None:
        if not explicit.exists():
            raise ConfigError(f"Prose config file not found: {explicit}")
        return explicit
    local = Path("configs") / _CONFIG_NAME
    if local.is_file():
        return local
    user = Path.home() / ".config" / "mdd" / _CONFIG_NAME
    if user.is_file():
        return user
    return None


#: Every key each section accepts. A key outside these is a config error, so a
#: misspelt knob fails loudly instead of silently keeping its default.
_KNOWN_KEYS: dict[str, frozenset[str]] = {
    "": frozenset({"prose"}),
    "prose": frozenset({"checks", "rules", *CHECK_NAMES}),
    "prose.reflow": frozenset(
        {"width", "min-line", "abbreviations", "single-letter-words", "rules"}
    ),
    "prose.lint": frozenset(
        {"quote-punctuation", "allow-hard-break", "literal-quote-patterns", "rules"}
    ),
    "prose.anchors": frozenset({"slug-style", "rules"}),
    "prose.freshness": frozenset({"field", "max-age-days", "rules"}),
}


def _reject_unknown_keys(where: str, raw: dict[str, Any]) -> None:
    known = _KNOWN_KEYS[where]
    for key in raw:  # pyright: ignore[reportAny]
        if key not in known:
            path = f"{where}.{key}" if where else str(key)  # pyright: ignore[reportAny]
            expected = ", ".join(sorted(known))
            raise ConfigError(f"{path} is not a known key; expected one of {expected}")


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value: Any = raw.get(key)  # pyright: ignore[reportAny]
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"prose.{key} must be a mapping")
    return cast("dict[str, Any]", value)


def _severity_value(where: str, raw: object) -> Severity:
    # YAML 1.1 decodes an unquoted `off` as the boolean False, and `off` is the
    # spelling this config is documented with, so accept it.
    if raw is False:
        return Severity.OFF
    if not isinstance(raw, str):
        raise ConfigError(f"{where} must be one of error, warning, off")
    try:
        return Severity(raw.strip().lower())
    except ValueError as exc:
        raise ConfigError(f"{where} must be one of error, warning, off (got {raw!r})") from exc


def _resolve_enabled(checks: dict[str, Any]) -> frozenset[str]:
    """Fold the ``checks:`` mapping into the set of checks that run."""
    enabled = set(DEFAULT_ENABLED)
    for name, raw in checks.items():  # pyright: ignore[reportAny]
        if name not in CHECK_NAMES:
            known = ", ".join(CHECK_NAMES)
            raise ConfigError(f"prose.checks.{name} is not a known check; expected one of {known}")
        if _severity_value(f"prose.checks.{name}", raw) is Severity.OFF:
            enabled.discard(name)
        else:
            enabled.add(name)
    return frozenset(enabled)


def _apply_check_level(severities: dict[str, Severity], name: str, checks: dict[str, Any]) -> None:
    """Step 2: a check-level severity replaces the built-in default for its rules.

    A rule that is off by default stays off: it encodes a house style or is
    noisy, and only naming it under the check's ``rules`` turns it on.
    """
    raw: Any = checks.get(name)  # pyright: ignore[reportAny]
    if raw is None:
        return
    resolved = _severity_value(f"prose.checks.{name}", raw)
    if resolved is Severity.OFF:
        return
    for rule in rules_for(name):
        if rule.default is not Severity.OFF:
            severities[rule.rule] = resolved


def _rules_key(check: str) -> str:
    """Where a rule owned by *check* is configured.

    The cross-cutting rules belong to no check, so they live directly under
    ``prose.rules`` rather than under a check's own section.
    """
    return "prose.rules" if check == CROSS_CUTTING else f"prose.{check}.rules"


def _apply_rule_level(severities: dict[str, Severity], owner: str, rules: dict[str, Any]) -> None:
    """Step 3: a rule named under its owner's ``rules`` beats the check-level default.

    A rule is accepted only under the section of the check that owns it. Filing
    it under another check would read as though that check's ``off`` governs it,
    which it does not.
    """
    where = _rules_key(owner)
    for rule_id, raw in rules.items():  # pyright: ignore[reportAny]
        registered = RULES.get(rule_id)
        if registered is None:
            raise ConfigError(f"{where}.{rule_id} is not a known rule id")
        if registered.check != owner:
            raise ConfigError(
                f"{where}.{rule_id} is in the wrong section; "
                f"set it under {_rules_key(registered.check)}"
            )
        severities[rule_id] = _severity_value(f"{where}.{rule_id}", raw)


def _resolve_severities(raw_prose: dict[str, Any], checks: dict[str, Any]) -> dict[str, Severity]:
    """Resolve every rule's severity, applying check-level then rule-level keys."""
    severities = {rule.rule: rule.default for rule in RULES.values()}
    for name in CHECK_NAMES:
        _apply_check_level(severities, name, checks)
        _apply_rule_level(severities, name, _section(_section(raw_prose, name), "rules"))
    _apply_rule_level(severities, CROSS_CUTTING, _section(raw_prose, "rules"))
    return severities


def _str_list(where: str, raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{where} must be a list of strings")
    items = cast("list[object]", raw)
    for item in items:
        if not isinstance(item, str):
            raise ConfigError(f"{where} must be a list of strings")
    return tuple(cast("list[str]", items))


def _positive_int(where: str, raw: object, default: int) -> int:
    if raw is None:
        return default
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        raise ConfigError(f"{where} must be a positive integer")
    return raw


def _resolve_reflow(raw: dict[str, Any]) -> ReflowConfig:
    extra = _str_list("prose.reflow.abbreviations", raw.get("abbreviations"))
    return ReflowConfig(
        width=_positive_int("prose.reflow.width", raw.get("width"), DEFAULT_WIDTH),
        min_line=_positive_int("prose.reflow.min-line", raw.get("min-line"), DEFAULT_MIN_LINE),
        abbreviations=DEFAULT_ABBREVIATIONS | frozenset(extra),
        single_letter_words=frozenset(
            _str_list("prose.reflow.single-letter-words", raw.get("single-letter-words"))
        ),
    )


def _resolve_lint(raw: dict[str, Any]) -> LintConfig:
    convention: Any = raw.get("quote-punctuation", "inside")  # pyright: ignore[reportAny]
    if convention is False:  # YAML 1.1 decodes an unquoted `off` as False
        convention = "off"
    if convention not in ("inside", "outside", "off"):
        raise ConfigError("prose.lint.quote-punctuation must be inside, outside or off")
    hard_break: Any = raw.get("allow-hard-break", True)  # pyright: ignore[reportAny]
    if not isinstance(hard_break, bool):
        raise ConfigError("prose.lint.allow-hard-break must be a boolean")
    patterns: list[re.Pattern[str]] = []
    for pattern in _str_list(
        "prose.lint.literal-quote-patterns", raw.get("literal-quote-patterns")
    ):
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise ConfigError(
                f"prose.lint.literal-quote-patterns entry {pattern!r} is not a valid regex: {exc}"
            ) from exc
    return LintConfig(
        quote_punctuation=convention,
        allow_hard_break=hard_break,
        literal_quote_patterns=tuple(patterns),
    )


def _resolve_anchors(raw: dict[str, Any]) -> AnchorsConfig:
    style: Any = raw.get("slug-style", "github")  # pyright: ignore[reportAny]
    if style != "github":
        raise ConfigError("prose.anchors.slug-style must be github")
    return AnchorsConfig(slug_style="github")


def _resolve_freshness(raw: dict[str, Any]) -> FreshnessConfig:
    name: Any = raw.get("field", DEFAULT_REVIEW_FIELD)  # pyright: ignore[reportAny]
    if not isinstance(name, str) or not name:
        raise ConfigError("prose.freshness.field must be a non-empty string")
    return FreshnessConfig(
        review_field=name,
        max_age_days=_positive_int(
            "prose.freshness.max-age-days", raw.get("max-age-days"), DEFAULT_MAX_AGE_DAYS
        ),
    )


def load(path: Path | None = None) -> ProseConfig:
    """Load and resolve the prose config, or return the defaults when there is none."""
    found = find_config_file(path)
    if found is None:
        return ProseConfig(severities={rule.rule: rule.default for rule in RULES.values()})
    raw_file = load_yaml(found)
    _reject_unknown_keys("", raw_file)
    raw_prose = _section(raw_file, "prose")
    _reject_unknown_keys("prose", raw_prose)
    for name in CHECK_NAMES:
        _reject_unknown_keys(f"prose.{name}", _section(raw_prose, name))
    checks = _section(raw_prose, "checks")
    return ProseConfig(
        enabled=_resolve_enabled(checks),
        severities=_resolve_severities(raw_prose, checks),
        reflow=_resolve_reflow(_section(raw_prose, "reflow")),
        lint=_resolve_lint(_section(raw_prose, "lint")),
        anchors=_resolve_anchors(_section(raw_prose, "anchors")),
        freshness=_resolve_freshness(_section(raw_prose, "freshness")),
    )
