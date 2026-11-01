"""Both prose writers over an external Markdown corpus, one test per file.

The ``prose_corpus`` marker keeps this module out of the default run. The roots
come from ``MDD_PROSE_CORPUS``, separated by the platform's path separator. A
root is a directory or a single file. In a git checkout the files are the
tracked ``*.md`` files, elsewhere every ``*.md`` file under the root.
``mise run prose-corpus`` and ``mise run prose-corpus-pinned`` set it.

For each file, each writer runs on a temporary copy the way
``mdd prose <check> --write`` does, and the test fails unless:

- the oracle in :mod:`tests.prose.oracle` accepts what was written,
- a second run changes nothing,
- no run reports a parse error, a write-gate refusal or a failed write.

A file named in the allowlist file that ``MDD_PROSE_CORPUS_ALLOWLIST`` points
at is expected to fail. If it passes, its test fails, so the entry goes when
the defect does.

A corpus can be private. Failure messages name the file, the writer, a line
number and the kind of change, and never quote the text.
"""

from __future__ import annotations

import functools
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from mdd.prose import runner
from mdd.prose.config import ProseConfig
from tests.prose.oracle import difference, first_changed_line

pytestmark = pytest.mark.prose_corpus

ROOTS_ENV = "MDD_PROSE_CORPUS"
ALLOWLIST_ENV = "MDD_PROSE_CORPUS_ALLOWLIST"

#: Findings that mean a writer could not do its job on a file.
FAILING_RULES = frozenset({"parse-error", "not-equivalent", "write-failed"})


@dataclass(frozen=True)
class CorpusFile:
    """One Markdown file: the root it was found under, and its path relative to it."""

    root: Path
    name: str

    @property
    def path(self) -> Path:
        return self.root / self.name


def corpus_roots() -> list[Path]:
    """The roots named in ``MDD_PROSE_CORPUS``, as absolute paths."""
    raw = os.environ.get(ROOTS_ENV, "")
    return [Path(part).expanduser().resolve() for part in raw.split(os.pathsep) if part]


def _tracked_markdown(root: Path) -> list[str] | None:
    """The tracked ``*.md`` files under *root*, or ``None`` when it is not in a git checkout."""
    try:
        listing = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if listing.returncode != 0:
        return None
    return [name for name in listing.stdout.decode("utf-8").split("\0") if name]


def files_under(root: Path) -> list[CorpusFile]:
    """Every Markdown file *root* contributes to the corpus, in a stable order."""
    if root.is_file():
        return [CorpusFile(root.parent, root.name)]
    names = _tracked_markdown(root)
    if names is None:
        names = [path.relative_to(root).as_posix() for path in root.rglob("*.md")]
    return [CorpusFile(root, name) for name in sorted(names) if (root / name).is_file()]


def corpus_files() -> list[CorpusFile]:
    """Every file under every root."""
    return [item for root in corpus_roots() for item in files_under(root)]


@functools.cache
def allowlist() -> dict[str, str]:
    """File name to reason, from ``MDD_PROSE_CORPUS_ALLOWLIST``; empty when it is unset.

    One entry per line, ``path/relative/to/root.md: reason``. Blank lines and
    lines starting with ``#`` are ignored.
    """
    location = os.environ.get(ALLOWLIST_ENV)
    if not location:
        return {}
    entries: dict[str, str] = {}
    lines = Path(location).read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        name, _, reason = stripped.partition(": ")
        if not reason.strip():
            msg = f"{location}:{number}: expected 'path: reason'"
            raise ValueError(msg)
        entries[name.strip()] = reason.strip()
    return entries


# --- driving the writers ----------------------------------------------------


@dataclass(frozen=True)
class Written:
    """What one writer left on disk, and the findings that mean it could not work."""

    text: str
    problems: tuple[str, ...]


def write_copy(check: str, name: str, text: str) -> Written:
    """Run ``mdd prose <check> --write`` over a copy of *text* named like the original.

    ``--allow-mirror`` is on: a mirrored file is exactly as likely to expose a
    writer defect, and refusing it would hide the write from the oracle.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(name).name
        _ = path.write_bytes(text.encode("utf-8"))
        options = runner.RunOptions(checks=(check,), write=True, allow_mirror=True)
        result = runner.run([path], ProseConfig(), options)
        after = path.read_bytes().decode("utf-8")
    problems = tuple(
        f"{finding.rule} at line {finding.line}: {finding.message}"
        for finding in result.findings
        if finding.rule in FAILING_RULES
    )
    if result.failed and not problems:
        problems = ("the run failed; see the log",)
    return Written(text=after, problems=problems)


def writer_problems(check: str, name: str, text: str) -> list[str]:
    """Everything wrong with what *check* does to *text*, without quoting it."""
    once = write_copy(check, name, text)
    problems = list(once.problems)
    if once.text == text:
        return problems
    reason = difference(text, once.text)
    if reason is not None:
        problems.append(f"the written file means something else: {reason}")
    twice = write_copy(check, name, once.text)
    problems.extend(f"second run: {problem}" for problem in twice.problems)
    if twice.text != once.text:
        line = first_changed_line(once.text, twice.text)
        problems.append(f"a second run changed the file again, first at line {line}")
    return problems


def file_problems(item: CorpusFile) -> list[str]:
    """Everything wrong with what either writer does to *item*."""
    try:
        text = item.path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return ["the file is not UTF-8"]
    return [
        f"{check}: {problem}"
        for check in runner.WRITERS
        for problem in writer_problems(check, item.name, text)
    ]


# --- tests --------------------------------------------------------------------

FILES = corpus_files()


def test_corpus_is_configured() -> None:
    """Every root exists and contributes files, and every allowlist entry names one."""
    roots = corpus_roots()
    if not roots:
        pytest.fail(f"{ROOTS_ENV} names no corpus root", pytrace=False)
    empty = [str(root) for root in roots if not files_under(root)]
    if empty:
        pytest.fail(f"no Markdown files under: {', '.join(empty)}", pytrace=False)
    names = {item.name for item in FILES}
    stale = sorted(set(allowlist()) - names)
    if stale:
        pytest.fail(f"allowlist entries name no corpus file: {', '.join(stale)}", pytrace=False)


@pytest.mark.parametrize("item", FILES, ids=[item.name for item in FILES])
def test_writers_keep_the_document(item: CorpusFile) -> None:
    """Both writers leave *item* meaning what it meant, and agree with themselves."""
    problems = file_problems(item)
    reason = allowlist().get(item.name)
    if reason is None:
        if problems:
            pytest.fail("\n".join(problems), pytrace=False)
        return
    if problems:
        pytest.xfail(f"allowlisted: {reason}")
    pytest.fail(f"allowlisted ({reason}), but every check passes: remove the entry", pytrace=False)
