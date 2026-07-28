# 007 - data protection

**Purpose:** Two cross-cutting rules that protect the organisation's data and credentials for every command.

**Status:** Implemented (2026-05-19)

## Introduction

Two rules apply to every `mdd` command:

1. **Credentials** are resolved from 1Password at runtime via the `op` CLI;
   raw tokens never appear in config, env vars, or on disk.
2. **Confidentiality blacklist** lists Confluence spaces and SharePoint
   sites that must never be pushed to GitLab. Every `mdd` command that
   could publish content to a git remote consults the blacklist first.

This is the canonical reference for both rules;
S08 (GitLab),
[S09](S09-confluence-command.md) (Confluence), and
[S10](S10-sharepoint-command.md) (SharePoint) defer to it.

## Requirements

### 1. Credentials via 1Password

1. **Config files store `op://` references, not tokens.** Wherever a token
   is required, the value in YAML must be a 1Password secret reference of
   the form `op://<vault>/<item>/<field>`. Example:
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
2. **No environment-variable token fallback.** Environment interpolation
   in config remains supported for non-secret values (URLs, usernames),
   but **not** for tokens. No `${CONFLUENCE_TOKEN}`, no `$GITLAB_TOKEN`
   read from the parent shell.
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
   not be pushed to GitLab. Both lists are required to exist (may be
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
4. **The gate fires before any GitLab interaction.** `mdd gitlab push`,
   `mdd gitlab create-repo`, and the `--push` paths in `mdd confluence` /
   `mdd sharepoint` all call the same blacklist helper.
5. **`--force` does not override the blacklist.** Removing an entry
   requires editing the config file, which leaves a diff in git history.
   This is intentional friction.
6. **Local-only export is unrestricted.** The blacklist gates publishing,
   not local conversion. A user can export an `Appraisals` site to a
   non-git directory for personal use; it just cannot end up on GitLab.

## Design Approach

**Credential resolver.** A single helper (`src/mdd/utils/secrets.py`)
resolves `op://...` references via `op read`, caches results in process
memory for one CLI run, and redacts the token from any error/repr. All
config loaders (Confluence, GitLab, Lucid, AI) call it; there is no
other code path for secrets.

**Blacklist helper.** A single helper (`src/mdd/utils/blacklist.py`) is
imported wherever a publish path exists. If a code path can write to
GitLab, it must call one of `check_confluence` / `check_sharepoint`
first. The helper also detects which source system a work-tree mirrors
(frontmatter scan + GitLab remote URL inspection) so `mdd gitlab push`
can look up the right blacklist without the caller telling it.

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

## 1Password setup (README pointer)

The README covers installing `op`, enabling CLI integration in the
1Password desktop app, creating the `confluence-pat` / `gitlab-pat`
items, and referencing them from `mdd` config. When token resolution
fails at runtime, `mdd` prints a short error pointing at this spec and
the README section, and (separately) detects the signed-out case and
asks the user to unlock.

## Related upstream specs

- 008-gitlab-command — GitLab command; defers to this spec for data-protection rules
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
