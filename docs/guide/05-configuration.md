# Configuration and secrets

`mdd` reads several small YAML files rather than one big one. Each file
covers one concern and has its own search path. Nothing is generated for
you: if a command needs a config file and cannot find one, it says so and
exits.

## Where configuration lives

Every file below is optional except where a command needs it. The general
shape is: an explicit path on the command line wins, then a `configs/`
directory relative to your **current working directory**, then
`~/.config/mdd/`.

| File | Holds | Search path |
|---|---|---|
| `confluence.yaml` | Confluence URL, username, API token | `--config`, then `./configs/`, then `~/.config/mdd/` |
| `ai.yaml` | AI gateway URL, token, model aliases | `--config`, then `./configs/`, then `~/.config/mdd/` |
| `data-protection.yaml` | the confidentiality blacklist | all of them, combined (see below) |
| `external-publishers.yaml` | pages owned by other automation | bundled, then `~/.config/mdd/`, then `./configs/external-publishers.local.yaml` |
| `sharepoint-mapping.yaml` | site name to repository name | `--mapping`, then `./configs/`, then `~/.config/mdd/` |
| `config.yaml` | extra search roots under a `docs:` key | `./configs/`, then `~/.config/mdd/` |

The cwd-relative `./configs/` entry is more load-bearing than it looks. It
means the directory you run from decides which tenant you talk to. The test
corpus in this repository uses exactly that property: it ships a
`configs/confluence.yaml` pointing at a throwaway instance, so commands run
from inside it cannot reach a production tenant by accident. Consider doing
the same for any mirror you keep locally.

Two files behave differently on purpose.

`data-protection.yaml` is **additive**. Every copy that exists is loaded
and the entries combine: the file bundled with the `mdd` install, then
`~/.config/mdd/data-protection.yaml`, then `./configs/data-protection.yaml`,
plus a file named with `--blacklist` on the commands that accept it
(`mdd search` today). You extend the list; you cannot
shrink it by shadowing the file. Removing an entry means editing the file
that contains it, which leaves a diff in git.

`external-publishers.yaml` merges in the other direction: the bundled file
is the base, `~/.config/mdd/external-publishers.yaml` overrides it, and
`./configs/external-publishers.local.yaml` overrides that. Merging appends
managed spaces and subtrees, and extends the account-id list of a publisher
that already exists by name.

## Confluence

```yaml
# configs/confluence.yaml
confluence:
  url: https://your-instance.atlassian.net
  username: you@example.com
  api_token: op://Employee/confluence-pat/token
```

`username` is your Atlassian account email and is not a secret. `url` is
the instance base URL; a page URL you pass on the command line must match
it, or `mdd` refuses the operation rather than risk hitting another tenant.

Create the API token in Atlassian's account settings, not in Confluence
itself. `mdd confluence whoami` is the cheapest way to confirm the token
works: it prints the account it authenticated as.

Note what is **not** here. `mdd confluence sync-space` does not read an
output directory out of this file. It uses `--output`, or, when the current
directory is a clone whose `origin` URL names the space, the current
directory. Configure `spaces:` if you want [`mdd search`](06-commands.md)
to find the mirror:

```yaml
confluence:
  url: https://your-instance.atlassian.net
  username: you@example.com
  api_token: op://Employee/confluence-pat/token
  spaces:
    ENGINEERING:
      output_dir: ~/mirrors/ENGINEERING
```

## SharePoint

SharePoint needs no credentials at all. `mdd` never calls a SharePoint API;
it reads the folder OneDrive has already synced to your disk, and your
OneDrive client holds the authentication. See
[Your first SharePoint sync](08-sharepoint-first-sync.md) for what that
changes.

The sync root is discovered: `mdd` looks for a single
`~/Library/CloudStorage/OneDrive-SharedLibraries-*` directory. If you have
more than one tenant synced, the discovery is ambiguous and the command
stops and tells you so. In that case, point `mdd sharepoint sync-folder` at
the site folder directly by path.

`configs/sharepoint-mapping.yaml` maps a SharePoint site name to a
repository name, because site names contain spaces and repository paths do
not. It is committed to git so everyone derives the same name:

```yaml
# configs/sharepoint-mapping.yaml
sites:
  "HR Documentation":
    repo: HR-Documentation
```

Sites with no entry fall back to a default rule (whitespace and special
characters collapse to `-`), and `mdd sharepoint list-sites` warns about
each one so you can decide whether to pin it.

For `mdd search` to see SharePoint mirrors, give them an `output_dir` under
`sharepoint.sites` in `configs/sharepoint.yaml`.

## The AI gateway

`mdd ai` talks to any OpenAI-compatible endpoint. There is no useful
default, so set one:

```yaml
# configs/ai.yaml
ai:
  base_url: https://your-gateway.example.com/v1
  api_token: op://Employee/ai-gateway/token
  token_hint: >-
    request a gateway token from the platform team, then store it in
    1Password under Employee/ai-gateway field token.
  models:
    default: claude-sonnet-4-5
    summarise: claude-haiku-4-5
    embed: text-embedding-3-large
```

`token_hint` is shown verbatim whenever the token is missing or rejected.
Fill it in with wherever your tokens actually come from; it is the one
piece of your deployment's operational knowledge `mdd` can repeat back to a
confused user. The `models` block maps the three task names `mdd` resolves
onto whatever your gateway serves.

## Secrets

The rule is short: **no secret ever goes into a config file, into the
mirror, or into git.**

Every token field accepts a 1Password secret reference instead of a value.
`mdd` resolves it by shelling out to the `op` CLI at the moment it is
needed, caches the result in memory for that one command, and never writes
it to a file, a log, or an error message. Exceptions redact anything that
looks like a token or an `op://` reference before it can reach a stack trace.

```yaml
api_token: op://Employee/confluence-pat/token
```

If you are signed in to several 1Password accounts and the vault lives in a
non-default one, pin the account:

```yaml
api_token:
  ref: op://Employee/confluence-pat/token
  account: example
```

`account` is the shorthand from `op account list`, or the sign-in address.
Without it, `op` uses whichever account was active last and may report that
the vault does not exist. The same object form works for `ai.api_token`.
You can also set the `MDD_OP_ACCOUNT` environment variable, or `op`'s own
`OP_ACCOUNT`.

This needs the 1Password CLI installed, signed in, and with desktop app
integration enabled. `mdd` bundles no 1Password libraries; it only knows
how to run `op`. When resolution fails, `mdd` distinguishes "not installed"
from "signed out" so the error tells you which one you have.

> [!IMPORTANT]
> `mdd` does **not** interpolate environment variables into config files.
> There is no `${CONFLUENCE_TOKEN}` support, and no `.env` file loading.
> A value that is not an `op://` reference is used literally, so pasting a
> raw token into YAML does work — and it puts the token in a file, which is
> the thing this design exists to prevent. Do not do it.

A handful of environment variables affect behavior, none of them secrets:
`MDD_OP_ACCOUNT` for the 1Password account, `MDD_LOG_LEVEL` for verbosity,
`NO_COLOR` and `FORCE_COLOR` for `mdd search` output, and `CLAUDE_HOME` for
where `mdd skills install` puts its symlinks.

## Before your first sync

Work through this list once. Most first-run failures are on it.

1. **`op` is installed and unlocked.** Run any `mdd confluence` command; if
   the token cannot resolve, `mdd` tells you whether `op` is missing or
   locked.
2. **`mdd confluence whoami` succeeds** and prints the account you expect.
   Wrong account here means every push is attributed to it.
3. **The account has the permissions you think it has**, in the space you
   are about to sync, and no more. A token inherits everything its user can
   do.
4. **You are running from the right directory.** `./configs/confluence.yaml`
   beats `~/.config/mdd/confluence.yaml`. Check which file is winning
   before you assume which tenant you are pointed at.
5. **The mirror directory is a git repository, and it is clean.** Sync
   refuses to run on a dirty tree, and that check is the only thing between
   your uncommitted edits and a sync commit. It silently passes if the
   directory is not a repository at all.
6. **`configs/data-protection.yaml` says what you mean.** The copy shipped
   in this repository is a template with an empty Confluence list. Read
   [Safety](04-safety.md) for what the blacklist covers in this
   distribution, which is less than you might assume.
7. **You have run `--dry-run` first.** Both sync commands support it and it
   prints the whole plan.

[S07](../spec/S07-data-protection.md) is the design record for the
credential and blacklist rules.
