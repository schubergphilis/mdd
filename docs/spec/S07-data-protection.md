# 007 - data protection

**Purpose:** Two cross-cutting rules that protect the organisation's data and credentials for every command.

**Status:** Implemented (2026-07-31)

## Introduction

Two rules apply to every `mdd` command:

1. **Credentials** are resolved from 1Password at runtime via the `op` CLI;
   raw tokens never appear in config, env vars, or on disk.
2. **Confidentiality blacklist** lists Confluence spaces and SharePoint
   sites whose content must never leave its source system. Every `mdd`
   sync and export command consults the blacklist at its entry point,
   before it fetches or writes anything.

This is the canonical reference for both rules;
[S09](S09-confluence-command.md) (Confluence),
[S10](S10-sharepoint-command.md) (SharePoint), and any mirror backend a
deployment supplies defer to it.

## Requirements

### 1. Credentials via 1Password

1. **Config files store `op://` references, not tokens.** Wherever a token
   is required, the value in YAML is required to be a 1Password secret
   reference of the form `op://<vault>/<item>/<field>`. This is a rule for
   the operator, not something the code enforces: `resolve_secret` returns
   any value that does not start with `op://` unchanged, so a raw token
   pasted into YAML does work. It is still forbidden — a token in a config
   file is a token on disk, and the file is the one thing likely to be
   copied, shared, or committed by mistake. Nothing detects the violation,
   which is why it is written down here. Example:
   ```yaml
   confluence:
     api_token: op://Employee/confluence-pat/token
   gitlab:
     api_token: op://Employee/gitlab-pat/token
   ```

   When the user is signed in to several 1Password accounts and the
   referenced vault lives in a non-default account, the secret may be
   specified as an object that pins the account:
   ```yaml
   confluence:
     api_token:
       ref: op://Employee/confluence-pat/token
       account: example
   ```
   `account` is the shorthand (`op account list --format=json`) or sign-in
   address; it is passed through to `op read --account <account>`. Without
   this, `op` falls back to whichever account was active last and may
   fail with `"Employee" isn't a vault in this account`. The same
   `account` field is supported on `lucid.api_token` and `ai.api_token`.
2. **No environment-variable token fallback.** No `${CONFLUENCE_TOKEN}`,
   no `$GITLAB_TOKEN` read from the parent shell. No config value of any
   kind is interpolated from the environment: config values are used
   literally, and the only substitution any loader performs is `op://`
   resolution for secrets and `~` expansion for paths. A `${VAR}` in a
   config file is a literal `${VAR}`.
3. **No `.env` files holding tokens, no shell exports.** If a third-party
   tool we shell out to (e.g. `glab`) needs an env var, it is set inline
   for that single subprocess invocation, populated from `op read` —
   never exported to the parent shell.
4. **Tokens stay in process memory only.** Resolved values are cached for
   the lifetime of one CLI invocation; never written to a temp file, log,
   or error message. Errors and exceptions redact any token value.
5. **`op` CLI must be installed and authenticated.** `mdd` does not bundle
   1Password integration libraries; it only knows how to invoke `op`.

### 2. Confidentiality blacklist

1. **Mandatory blacklist for both Confluence and SharePoint.** A config
   file lists Confluence space keys and SharePoint site names that must
   not be pushed to a remote. Both lists are required to exist (may be
   empty arrays); a missing key is a hard error to force a deliberate
   choice.
2. **Blacklist config is committed to git.** It's the inverse of secret —
   a list of what's secret enough that it must not leave its source
   system. Version control gives an audit trail of who added/removed
   what.
3. **Match is case-insensitive against the canonical name. Exact by
   default; trailing `*` enables a prefix match.** That's the only
   wildcard form supported — no `?`, no `**`, no character classes,
   no regex. The rule must be readable by anyone scanning the file and
   trivially grep-able.
   - Confluence: match against `space_key` (e.g. `HRPRIV`).
   - SharePoint: match against the OneDrive folder name with any
     trailing ` - Documents` suffix stripped (e.g. `Appraisals` or
     `Appraisals - Alice Example`). OneDrive can sync a SharePoint
     sub-folder, in which case the folder name will not match the
     SharePoint site name — the match runs on whatever the user sees in
     OneDrive, so prefix patterns matter for family names like
     `Appraisal*`. See [S10](S10-sharepoint-command.md) for the
     sub-folder case in detail.
   - Examples: `Board` matches exactly `Board` (case-insensitive)
     but does **not** match `Advisory Board`. `Appraisal*` matches
     `Appraisal`, `Appraisals`, `Appraisals - Alice Example`,
     `Appraisal Cycle 2026`.
4. **The gate fires at the entry point of every sync and export, not at
   the push step.** `sync_space`, `sync_site`, `sync_folder`,
   `export_site`, `export_folder` and `export_page` each call the
   blacklist helper before they fetch or write anything, so a blacklisted
   space or site aborts the whole run rather than being caught per page
   deep in an apply loop. `--dry-run` is gated too: it is not a preview
   escape hatch. A mirror backend a deployment supplies may add its own
   push-time gate on top; that is additional defence, not the mechanism.
   Gating at the entry point rather than at `--push` is deliberate — the
   push is far downstream of the point where protected content has
   already been written to a work-tree that is usually a git clone.
5. **`--force` does not override the blacklist.** Removing an entry
   requires editing the config file, which leaves a diff in git history.
   This is intentional friction.
6. **Local-only export is gated as well.** Earlier versions of this spec
   said local export was unrestricted and only publishing was gated. The
   implementation is stricter and stays that way: because the gate sits
   at the entry point, exporting a blacklisted space or site to a plain
   local directory is refused too, `--push` or not. The reasoning is that
   a local directory is a weak boundary — it is usually a git clone, it
   gets backed up, and it gets synced. The blacklist means "this content
   does not leave its source system", and a local copy has already left.
   The consequence to accept is that there is no supported way to export
   a blacklisted space for personal use; removing the entry, with the
   diff that leaves, is the only route.
7. **An unidentifiable Confluence space is refused when anything is
   blacklisted.** A page whose API response carries no space key cannot
   be checked, so it is treated as potentially protected. When the
   Confluence blacklist is empty there is nothing to protect and it is
   allowed through, so a deployment that has not opted into blacklisting
   sees no new failure.
8. **A missing blacklist config fails closed.** If no loaded file
   declares the section being checked, the sync or export aborts rather
   than proceeding unprotected. See "Config schema" below for the load
   order and the error the operator gets.

## Design Approach

**Credential resolver.** A single helper (`src/mdd/utils/secrets.py`)
resolves `op://...` references via `op read`, caches results in process
memory for one CLI run, and redacts the token from any error/repr. All
config loader (Confluence, AI, and any a wrapper adds) calls it; there is no
other code path for secrets.

**Blacklist helper.** A single helper (`src/mdd/utils/blacklist.py`) is
imported by every sync and export entry point. A code path that pulls
content out of Confluence or SharePoint must call `check_confluence` or
`check_sharepoint` first, at the top of the function, on the space key or
site name it was asked to operate on. There is deliberately no per-page
or per-file variant of the check: the unit the operator blacklists is a
space or a site, so the gate belongs where that identity is known and
before the work starts.

The helper also detects which source system an existing work-tree
mirrors (frontmatter scan + `origin` URL inspection), so a deployment's
mirror backend can gate its own push without the caller telling it which
list to consult. That path has no caller inside the core — the core's
sync and export entry points always know their own source system — and
exists for backends outside it.

**Naming the file that refused.** Entries union across up to four files,
so a refusal reports which of them declares the matching pattern.
"Remove the pattern from the config" is not actionable when four configs
could be the one.

## Config schema

The blacklist is a separate YAML file from per-user secrets — it's
shared, so it's committed to git; per-user secrets are not.

The entries below are **illustrative**. The live policy is whatever
`configs/data-protection.yaml` actually contains; duplicating it into a
spec would only guarantee the two drift apart, and a spec is a worse
place to review a confidentiality decision than a diff on the config.

```yaml
# configs/data-protection.yaml — committed
confluence:
  blacklisted_spaces:
    - HRPRIV
    - LEGAL
    - FINPRIV

sharepoint:
  blacklisted_sites:
    - Board                 # governance bodies: minutes and decisions
    - Governance
    - "Appraisal*"          # prefix match catches Appraisals, Appraisals - <Name>, etc.
    - "Performance Review*"
    - Coaching
    - "Customer-*"          # named client engagements
```

Sites that *are* expected to be mirror-safe (company-wide audience —
`Labs`, `Engineering`, `Software`, `Policies`, `Company`, `AI`) are
documented in the README rather than the blacklist file. The blacklist
is the gate; an inventory of allowed sites is informational.

**Discovery is additive.** Every file found in the search paths below is
loaded, and the blacklisted entries are unioned. This is so the repo-bundled
file always blocks its entries regardless of where `mdd` is invoked from, and
so users can extend the list without rewriting it. Load order (later files
extend earlier ones):

1. Repo-bundled `configs/data-protection.yaml` — resolved relative to the
   `mdd` install location, so it applies regardless of the caller's working
   directory.
2. `~/.config/mdd/data-protection.yaml` — per-user additions.
3. `./configs/data-protection.yaml` — cwd-relative (skipped when it
   resolves to the same file as the repo-bundled one).
4. `--blacklist <file>` argument — additional entries for a single run.

A file may declare only `confluence:` or only `sharepoint:`; the merged
result must declare each section that is being checked, otherwise the
gate fails closed.

**Fail-closed means every sync and export needs a reachable config.**
When nothing in the load order exists, the run aborts with an error
naming all four locations and stating that either list may be an empty
array. That is the deliberate choice — an absent data-protection config
is not an allow-all — but it makes source 1 load-bearing, and source 1
resolves relative to the checked-out source tree. An install that does
not carry `configs/` alongside the package finds no bundled file, so a
user of such an install needs `~/.config/mdd/data-protection.yaml` (two
empty lists are enough) before any sync or export will run.

## 1Password setup (README pointer)

The README covers installing `op`, enabling CLI integration in the
1Password desktop app, creating the `confluence-pat` / `gitlab-pat`
items, and referencing them from `mdd` config. When token resolution
fails at runtime, `mdd` prints a short error pointing at this spec and
the README section, and (separately) detects the signed-out case and
asks the user to unlock.

## Related upstream specs

- [009-confluence-command](S09-confluence-command.md) — Confluence command; defers to this spec for data-protection rules
- [010-sharepoint-command](S10-sharepoint-command.md) — SharePoint command; defers to this spec for data-protection rules

## Out of scope

- A Python integration with the 1Password Connect server or Service
  Accounts (overkill for a developer CLI).
- Caching credentials to disk — even encrypted (1Password already does
  this).
- Automated rotation — 1Password handles item lifecycle.
- Glob/regex blacklist matching beyond a single trailing `*` — keeps
  the rule auditable. Prefix-only is a deliberate compromise to handle
  family names like `Appraisal*` without opening the door to full
  pattern matching.
- Allowlist mode (push only what's explicitly allowed) — could be a
  follow-up if the team prefers default-deny semantics.
