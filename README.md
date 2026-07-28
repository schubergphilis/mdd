<img src="assets/mdd-logo.png" alt="mdd" width="360">

# mdd — Markdown Does Docs

Bidirectional sync between Markdown-in-git and the places documents
actually live: Confluence Cloud, SharePoint/OneDrive, and Office files.

`mdd` treats a git repository of Markdown as the source of truth and
reconciles it against a remote, in both directions, without losing
structure. The interesting part is the document IR in the middle:
Confluence storage XHTML and GitHub-flavoured Markdown both read into and
write out of one typed tree, which is what makes a round-trip lossless
enough to be worth automating.

> ## ⚠️ Pre-1.0 — use with care
>
> `mdd` is written almost entirely by AI agents under human review. It
> ships versioned `0.x` releases, but there is no independent security
> review and no 1.0 yet.
>
> - Under semantic versioning, `0.x` means breaking changes can land
>   between **minor** versions (`0.2 → 0.3`); pin a version if you need
>   stability.
> - Push-side operations (`mdd confluence update-page`,
>   `mdd confluence sync-space --push`, `mdd sharepoint sync-site --push`)
>   write to production systems. The data-protection blacklist (spec S07)
>   gates these, but has not been adversarially reviewed.
> - The `mdd ai` family calls an OpenAI-compatible gateway; outputs are
>   non-deterministic and should be reviewed by a human before publishing.

## Install

```bash
uv tool install git+https://github.com/schubergphilis/mdd
mdd --version
```

Three external tools must be on `PATH`: `quarto`, `rsvg-convert`
(librsvg) and `rg` (ripgrep). `mdd pdf*` additionally needs Microsoft
Office and only runs on macOS.

## Commands

### Document conversion

| Command | Description |
|---|---|
| `mdd convert <path>` | Convert `.docx`, `.pptx`, or `.pdf` files to Markdown |
| `mdd new <dir>` | Create a Quarto project with PPTX + DOCX output |
| `mdd new-pptx <dir>` | Create a Quarto PowerPoint project |
| `mdd new-docx <dir>` | Create a Quarto Word document project |
| `mdd pdf [dir]` | Export all Office files to PDF (macOS only) |
| `mdd pdf-pptx [dir]` | Export PowerPoint files to PDF (macOS only) |
| `mdd pdf-docx [dir]` | Export Word files to PDF (macOS only) |

### Confluence

| Command | Description |
|---|---|
| `mdd confluence export-page <id-or-url>` | Export a single page to `.md` with frontmatter and attachments |
| `mdd confluence sync-space <space-key>` | Reconcile an entire space with a local mirror (use `--read-only` for snapshot-only) |
| `mdd confluence create-page <file.md>` | Create a new Confluence page from a local Markdown file |
| `mdd confluence update-page <file.md>` | Push local edits back to Confluence (diff + confirm) |
| `mdd confluence whoami` | Print the current Confluence user and managed-page publishers |

### SharePoint

| Command | Description |
|---|---|
| `mdd sharepoint list-sites` | List OneDrive-synced SharePoint sites with blacklist status |
| `mdd sharepoint sync-site <name>` | Bidirectionally sync a SharePoint site with its Markdown mirror |
| `mdd sharepoint sync-folder <path>` | Bidirectionally sync an arbitrary local OneDrive folder |

### Search and AI

| Command | Description |
|---|---|
| `mdd search "<query>"` | Search across configured mirror roots via ripgrep |
| `mdd ai rewrite <file>` | Rewrite Markdown for clarity and tone |
| `mdd ai index <dir>` | Walk a directory and generate `INDEX.md` summaries |
| `mdd ai review <dir>` | Review a Markdown mirror for duplicates / stale content |

### Other

| Command | Description |
|---|---|
| `mdd --version` | Print the installed `mdd` version and exit |
| `mdd help` | Show usage (full reference for every command and flag) |
| `mdd skills list` | List bundled Claude Code skills |
| `mdd skills install` | Symlink bundled skills into `~/.claude/skills/` |
| `mdd skills uninstall` | Remove only the symlinks installed by `mdd` |

## Extending it: the mirror seam

Where a synced mirror gets *pushed* is deliberately not baked in. A
`MirrorBackend` supplies the four provider-specific operations — resolve
the remote URL, ensure the remote project exists, guard the push, probe
reachability — and the sync engines are otherwise generic git.

Two backends ship in the box: `git` (push to whatever `origin` already
points at) and `local` (never push). A downstream wrapper registers its
own and composes a CLI on top:

```python
from mdd.cli import build_dispatcher
from mdd.mirror import register_backend

from my_org.backend import MyForgeBackend
from my_org import commands as extras


def main(argv=None):
    register_backend("myforge", MyForgeBackend())
    return build_dispatcher(
        default_backend="myforge",
        extra_commands=extras.ALL,
    ).run(argv)
```

`build_dispatcher` takes exactly two extension points — the default
backend name and a list of command modules exposing
`register(subparsers, parents)` — so a wrapper adds subcommands and a
hosting provider without forking the core. See
[`lsimons/mdd-wrapper`](https://github.com/lsimons/mdd-wrapper) for a
minimal worked example.

## Configuration

Config lives in YAML under `~/.config/mdd/`, with a `./configs/` directory
in the working tree taking precedence. Secrets are never stored in these
files: a value may be an `op://` reference resolved through the 1Password
CLI at call time, or come from the environment.

## Documentation

Design docs live in [`docs/spec/`](docs/spec/); start from
[`docs/spec/000-specs.md`](docs/spec/000-specs.md) for the index and the
shared conventions.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). `mise run ci` is the gate.

## Security

Please report vulnerabilities privately, not as a GitHub issue. See
[`SECURITY.md`](SECURITY.md) for the reporting channels, what is in
scope, and what to expect.

## Licence

Copyright 2026 Schuberg Philis B.V.

Licensed under the Apache License, Version 2.0 (the "License"); you may
not use these files except in compliance with the License. You may obtain
a copy of the License in [`LICENSE`](LICENSE) or at
<https://www.apache.org/licenses/LICENSE-2.0>.

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.
