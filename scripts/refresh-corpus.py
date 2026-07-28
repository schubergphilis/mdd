#!/usr/bin/env python3
"""Wrapper for the corpus-side refresh-corpus.py.

The actual refresh logic lives at ``tests/corpus/confluence/scripts/refresh-corpus.py``
(vendored from the old standalone test-confluence repo). It imports
``mdd.confluence.*`` and so must run inside this repo's uv venv. This
wrapper just invokes it via the active Python interpreter.

Any CLI args are forwarded to the corpus script unchanged.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

MDD_ROOT = Path(__file__).resolve().parent.parent
CORPUS = MDD_ROOT / "tests" / "corpus" / "confluence"


def main() -> int:
    script = CORPUS / "scripts" / "refresh-corpus.py"
    if not script.is_file():
        sys.exit(f"refresh-corpus.py missing: {script}")
    sys.argv = [str(script), *sys.argv[1:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
