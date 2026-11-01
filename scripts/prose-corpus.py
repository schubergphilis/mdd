"""Run both prose writers over a Markdown corpus that does not live in this repository.

    prose-corpus.py [--allowlist FILE] PATH...   any corpus, local or private
    prose-corpus.py --pinned                     the pinned public corpus

Each PATH is a directory or a single Markdown file. In a git checkout only the
tracked ``*.md`` files count. The checks themselves are the ``prose_corpus``
tests in ``tests/prose/test_corpus.py``; this script fetches the pinned corpus
when asked to, and hands the roots to pytest.

The report names each failing file, the writer and a line number, and never
prints the file's text, so it is safe to run over a private corpus. Never wire
a private path into CI.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The pinned public corpus: schubergphilis/ai-training. Its content is
# CC BY-SA 4.0 and this repository is Apache-2.0, so it is fetched at run time
# into an ignored cache directory and never copied in, not even as a fixture
# or an excerpt. A defect it reveals gets a fixture written from scratch.
#
# To bump the pin:
#   1. Find the new commit: git ls-remote https://github.com/schubergphilis/ai-training main
#   2. Set PINNED_SHA below to its full 40-character SHA.
#   3. Run `mise run prose-corpus-pinned`.
#   4. For each failing file, write a small fixture of your own that reproduces
#      the defect and fix it, or add the file to PINNED_ALLOWLIST with a
#      one-line reason. Remove any entry the run reports as passing.
#   5. Commit the new SHA and the allowlist together.
PINNED_URL = "https://github.com/schubergphilis/ai-training.git"
PINNED_SHA = "b0d6906076761bc353a18812ef7e5e72d5d1df93"
PINNED_ALLOWLIST = REPO / "tests" / "prose" / "ai-training-allowlist.txt"
PINNED_CHECKOUT = REPO / ".cache" / "prose-corpus" / "ai-training"

ROOTS_ENV = "MDD_PROSE_CORPUS"
ALLOWLIST_ENV = "MDD_PROSE_CORPUS_ALLOWLIST"


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def checked_out_sha(checkout: Path) -> str | None:
    # Look for .git first: without it, git would walk up and answer for the
    # repository the cache directory sits in.
    if not (checkout / ".git").is_dir():
        return None
    try:
        return git("rev-parse", "--verify", "--quiet", "HEAD", cwd=checkout).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def fetch_pinned(checkout: Path) -> None:
    """Make *checkout* a clean checkout of exactly PINNED_SHA, fetching only that commit."""
    if checked_out_sha(checkout) != PINNED_SHA:
        print(f"fetching {PINNED_URL} at {PINNED_SHA}", flush=True)
        checkout.mkdir(parents=True, exist_ok=True)
        if not (checkout / ".git").is_dir():
            _ = git("init", "--quiet", cwd=checkout)
        _ = git(
            "fetch", "--quiet", "--depth", "1", "--no-tags", PINNED_URL, PINNED_SHA, cwd=checkout
        )
    # --force throws away any local edit, so the corpus is what the pin says.
    _ = git("checkout", "--quiet", "--force", "--detach", PINNED_SHA, cwd=checkout)
    actual = checked_out_sha(checkout)
    if actual != PINNED_SHA:
        sys.exit(f"expected {PINNED_SHA} in {checkout}, found {actual}")


def resolve(paths: list[str]) -> list[Path]:
    """Resolve *paths* against the directory the user ran ``mise run`` from."""
    base = Path(os.environ.get("MISE_ORIGINAL_CWD", Path.cwd()))
    roots = [(base / path).expanduser().resolve() for path in paths]
    missing = [str(root) for root in roots if not root.exists()]
    if missing:
        sys.exit(f"no such file or directory: {', '.join(missing)}")
    return roots


def run_checks(roots: list[Path], allowlist: Path | None) -> int:
    env = dict(os.environ)
    env[ROOTS_ENV] = os.pathsep.join(str(root) for root in roots)
    if allowlist is not None:
        env[ALLOWLIST_ENV] = str(allowlist)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/prose/test_corpus.py",
        "-m",
        "prose_corpus",
        "--no-cov",
        "-q",
        "-rfxX",
        # The cache would keep the failing file names of a private corpus.
        "-p",
        "no:cacheprovider",
    ]
    return subprocess.run(command, cwd=REPO, env=env, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    _ = parser.add_argument("paths", nargs="*", metavar="PATH", help="corpus root or file")
    _ = parser.add_argument("--pinned", action="store_true", help="the pinned public corpus")
    _ = parser.add_argument("--allowlist", type=Path, help="files expected to fail, with reasons")
    args = parser.parse_args()
    if args.pinned:
        if args.paths or args.allowlist:
            parser.error("--pinned takes no PATH and no --allowlist")
        fetch_pinned(PINNED_CHECKOUT)
        return run_checks([PINNED_CHECKOUT], PINNED_ALLOWLIST)
    if not args.paths:
        parser.error("give at least one PATH, or --pinned")
    allowlist = resolve([str(args.allowlist)])[0] if args.allowlist else None
    return run_checks(resolve(args.paths), allowlist)


if __name__ == "__main__":
    sys.exit(main())
