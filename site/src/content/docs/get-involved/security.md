---
title: Security Policy
description: 'mdd is pre-1.0 and was published as open source in 2026. Please read
  this before you deploy it anywhere that matters:'
sidebar:
  order: 3
editUrl: https://github.com/schubergphilis/mdd/edit/main/SECURITY.md
---

## Status: pre-1.0, recently open-sourced

`mdd` is pre-1.0 and was published as open source in 2026. Please read
this before you deploy it anywhere that matters:

- There has been **no independent security review** of this codebase.
- `mdd` is written almost entirely by AI agents under human review. The
  review is real, but it is not the same thing as an audit.
- Under `0.x` semantic versioning, breaking changes land between minor
  versions. Pin a version if you need stability.

None of that means we are relaxed about security reports. It means you
should calibrate your trust accordingly, and that we would rather hear
about a problem than not.

## Supported versions

| Version | Supported |
|---------|-----------|
| latest `0.x` | yes |
| any earlier `0.x` | no |

Security fixes land on `main` and ship in the next release of the current
minor. While `mdd` is pre-1.0 there are **no security backports** to
older minor versions. This will be revisited at 1.0.

## Reporting a vulnerability

Please report privately. Do not open a public GitHub issue, and do not
discuss the vulnerability publicly until a fix is available.

**Preferred:** email
[abuse@schubergphilis.com](mailto:abuse@schubergphilis.com) with `[mdd]`
in the subject. This is Schuberg Philis's standing responsible-disclosure
channel. Encrypted mail is preferred; the PGP public key is at
<https://keybase.io/schubergphilis>, and an encrypted chat option is
linked from the page below. The company's full responsible disclosure
policy — including credit, the hall of fame, and the bounty — is at
<https://schubergphilis.com/security> and takes precedence over this
document on anything it covers.

**On GitHub:** if you would rather report through GitHub, private
vulnerability reporting is enabled on this repository — use the
["Report a vulnerability" button](https://github.com/schubergphilis/mdd/security/advisories/new)
under the Security tab.

Please do not send sensitive information over unencrypted channels or
social media.

Please include:

- What the issue is and what an attacker gets out of it.
- Steps to reproduce, or a proof of concept.
- The `mdd` version (`mdd --version`) and platform.
- Any workaround you have already found.
- Whether you want public credit or prefer to stay anonymous.

Do not include real customer data, live credentials, or content from a
private Confluence space or SharePoint site in a report. A redacted
reproduction is more useful to us than a real one.

## Rules of engagement

If you think you have found a vulnerability, we would very much
appreciate it if you:

- Don't exploit your finding.
- Share the information with just us, not other parties.
- Give us time to assess the situation and respond within a reasonable
  timeframe.

## What to expect

`mdd` is maintained on a best-effort basis by a small team. We aim to:

1. Acknowledge your report within **5 business days**.
2. Confirm or close it, with a written explanation either way, within
   **15 business days**.
3. For confirmed issues, agree a fix and disclosure timeline with you.
   Severe issues in the credential and push paths get priority; expect a
   release rather than a patch to an older version (see *Supported
   versions*).
4. Credit you in the release notes and the advisory if you have told us
   you want public credit. By default you remain anonymous.

These are targets, not contractual commitments, and they apply to this
open source project. Reports about Schuberg Philis production systems
fall under <https://schubergphilis.com/security> instead.

## Credit and bounty

By default you remain anonymous. If you would rather be named, say so
and tell us the name or alias to use; we will credit you in the GitHub
advisory and the release notes.

Reports sent to `abuse@schubergphilis.com` are handled under Schuberg
Philis's responsible disclosure policy, which offers reporters a token
of appreciation and maintains a public hall of fame. See
<https://schubergphilis.com/security> for the current options and what
it covers. `mdd` runs no separate bounty of its own.

## Scope

In scope: the `mdd` package and CLI in this repository, and documentation
that would lead a careful operator into an insecure configuration.

Out of scope:

- **The services `mdd` talks to** — Confluence Cloud, SharePoint /
  OneDrive / Microsoft Graph, 1Password, GitLab, GitHub, and any
  OpenAI-compatible AI gateway. Report those to the respective vendor.
- **External tools** — Quarto, librsvg, ripgrep, Microsoft Office, `op`,
  `git`. Report upstream.
- **Third-party Python dependencies.** Report upstream. Do tell us if
  the way `mdd` calls a dependency turns a non-issue into an exploitable
  one, or if we are pinning something known-vulnerable — `pip-audit`
  runs in CI, but it is not infallible.
- **Operator misconfiguration**, including an empty or wrong
  confidentiality blacklist, an over-broad Confluence or Graph token, a
  world-readable config directory, or pointing `origin` at a remote you
  did not mean to publish to.
- **AI output quality.** The `mdd ai` commands call a third-party
  gateway; output is non-deterministic and may be wrong. That is a
  known property, not a vulnerability.
- **Breaking changes between `0.x` minors.** Documented above.
- Findings from a scanner with no demonstrated impact on `mdd`.

## Good faith

If you follow this policy in good faith, we will treat your report as a
contribution: we will work through it with you, we will tell you what we
decided and why, and we will not ask you to stay quiet indefinitely. In
return, please don't access, modify, or retain data that isn't yours,
and don't degrade any service while investigating.
