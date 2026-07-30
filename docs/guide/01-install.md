# Install

`mdd` is one command-line tool. The install is a single line. Everything else
on this page is optional and matters only for the features that need it.

> [!WARNING]
> `mdd` is beta software. It is written largely by AI agents under human
> review, and it has had no independent security review. Several commands write
> to production document systems. Read [Safety](04-safety.md) before you point
> `mdd` at content you care about.

## Prerequisites

`mdd` needs Python 3.14. You do not have to install Python yourself. The
supported installer is [`uv`](https://docs.astral.sh/uv/), which fetches a
matching interpreter and keeps the tool in its own environment, isolated from
anything else on your machine.

Install `uv` first if you do not already have it. Follow
[Astral's installation instructions](https://docs.astral.sh/uv/getting-started/installation/).

## Install `mdd`

```bash
uv tool install git+https://github.com/schubergphilis/mdd
```

There is no PyPI package and no stable release. That command builds from the
tip of `main`, so what you get is whatever was merged most recently. Two
consequences: the tool can change under you between installs, and you should
read the [Safety](04-safety.md) page rather than assume a version number means
anything.

## Verify

```bash
mdd --version
```

```
mdd 0.1.1.dev17+gf5812ba
```

The version string comes from git rather than from a release process.
`0.1.1.dev17+gf5812ba` means seventeen commits past the `v0.1.0` tag, at commit
`f5812ba`. Quote that string when you report a problem; it identifies the exact
build.

Then get your bearings:

```bash
mdd help
```

## Optional tools

`mdd` runs without any of these. Each one turns on a specific feature, and the
command that needs it says so when it is missing.

| Tool | Needed for |
|---|---|
| [Quarto](https://quarto.org) | Rendering a `mdd new` project into `.pptx` and `.docx` |
| Microsoft Office on macOS | `mdd pdf`, `mdd pdf-pptx`, `mdd pdf-docx` |
| [ripgrep](https://ripgrep.org) (`rg`) | `mdd search` |
| [librsvg](https://gitlab.gnome.org/GNOME/librsvg) (`rsvg-convert`) | Rasterizing `.svg` files into `.svg.png` siblings during a sync |
| [1Password CLI](https://www.1password.dev/cli) (`op`) | Resolving `op://` references in configuration |

Two notes on the first two rows.

PDF export drives Word and PowerPoint through AppleScript, so it works on macOS
with Microsoft Office installed and nowhere else. There is no fallback.

Quarto is only needed to *render* a project. `mdd new` scaffolds one without
it.

> [!NOTE]
> The first `mdd convert` downloads Docling's machine-learning models, around
> 500 MB, into `~/.cache/docling/`. Later runs reuse the cache. Budget for that
> download the first time, and expect it to fail behind a proxy that blocks
> model downloads.

`mdd ai` needs an API token for a LiteLLM gateway. See
[Configuration and secrets](05-configuration.md).

## Upgrade

```bash
uv tool upgrade mdd
```

The install points at a git URL rather than a version, and `main` moves. If
`uv` decides there is nothing to do, force a rebuild from the current tip:

```bash
uv tool install --force git+https://github.com/schubergphilis/mdd
```

Re-run `mdd --version` afterwards and check that the commit changed.

## Uninstall

```bash
uv tool uninstall mdd
```

That removes the tool and its environment. It leaves four things behind, on
purpose:

- configuration under `~/.config/mdd/`
- the Docling model cache under `~/.cache/docling/`
- any mirror repository you cloned or created
- skill symlinks under `~/.claude/skills/`

Remove the skill symlinks with `mdd skills uninstall` *before* you uninstall
the tool. Delete the rest by hand if you want them gone.

## Install from a clone

Contributors, and anyone who wants to run an unmerged branch, work from a
clone instead:

```bash
git clone https://github.com/schubergphilis/mdd
cd mdd
mise install
mise run install
uv run mdd --version
```

Inside a clone, run `uv run mdd` rather than `mdd`. A bare `mdd` resolves to
whatever is on your `PATH`, which is usually the tool install and not the code
you are editing.

[CONTRIBUTING.md](../../CONTRIBUTING.md) covers the development setup, the
quality gate, and how to propose a change.

## Next

[Quickstart](02-quickstart.md) walks through a first run that needs no
Confluence or SharePoint access.
