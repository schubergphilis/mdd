# 002 - mdd CLI Tool

**Purpose:** A unified `mdd` CLI dispatcher that routes subcommands to command modules.

**Status:** Superseded by [S35](S35-argparse-cli-parsing.md) (2026-05-16)

## Superseded

The dispatcher described here was replaced by [S35](S35-argparse-cli-parsing.md)'s
single-argparse-tree design. For the current contract — including the full
subcommand list, the `register(subparsers, parents)` convention, the
`CommonParents` (`--config`, `--dry-run`) parent parsers, and the root logging
flags (`-v`, `--trace`, `--trace-bodies`, `--log-level=`) — read S35 instead.
This file is retained for history; do not extend it.

## Requirements (historic)

- Executable CLI named `mdd`, installed as a console script
- `mdd help` (and no args / `--help`) shows usage
- `mdd echo <args>` echoes arguments — smoke test
- `mdd <unknown>` prints error to stderr and exits 1
- Subcommands: `help`, `echo`, `convert`, `new`, `new-pptx`, `new-docx`, `pdf`, `pdf-pptx`, `pdf-docx`

## Design Approach (historic)

- Entry point: `src/mdd/cli.py`, `main(args: list[str] | None = None) -> int`
- Explicit command routing (no dynamic discovery)
- Returns int exit code; `sys.exit()` only in `__main__` / entry point

## Implementation Notes (historic)

- See [000-specs.md](000-specs.md) for CLI patterns
- Commands lived in `src/mdd/commands/`; each exported one `cmd_*` function (now `register()` per S35)
