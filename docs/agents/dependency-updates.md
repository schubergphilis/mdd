# Dependency updates: Renovate

[Renovate](https://docs.renovatebot.com/) keeps the dependencies current:
the Python dependencies in `pyproject.toml` and `uv.lock`, the documentation
site's `site/package.json` and `site/bun.lock`, the `.mise.toml` tools and
`mise.lock`, the GitHub Actions, and Renovate's own image. `renovate.json`
is the policy. `.github/workflows/renovate.yml` runs it self-hosted, as the
GitHub App `mdd-renovate`.

## Policy

- Renovate opens pull requests. It never merges them. A maintainer reviews
  and merges each one, like any other pull request.
- A release is proposed 7 days after it was published
  (`minimumReleaseAge`). New pull requests open on Mondays. All non-major
  updates go into one pull request, and each major into its own.
- Version floors in `pyproject.toml` and `site/package.json` move up with
  each update (`rangeStrategy: bump`), as the hand-made bumps did before.
  GitHub Actions stay pinned to a commit SHA with the version in a comment.
- Vulnerability fixes, from GitHub's Dependabot alerts and from OSV, skip
  the Monday schedule and the 7-day wait.
- Once a week, Renovate refreshes `uv.lock`, `site/bun.lock` and
  `mise.lock` (lock file maintenance). A refresh has no release date, so it
  skips the 7-day wait. Each tool's own cooldown ages the transitive
  packages it pulls in: `exclude-newer` in `pyproject.toml`,
  `minimumReleaseAge` in `site/bunfig.toml`, and `minimum_release_age` in
  `.mise.toml`.
- A new Python minor (3.14 to 3.15) waits for approval on the Dependency
  Dashboard issue and then gets its own pull request. The ML wheels lag
  behind new Python releases.
- Renovate never moves TypeScript to a new major. `astro check` needs the
  TypeScript 6 API
  ([withastro/roadmap#1321](https://github.com/withastro/roadmap/discussions/1321)).
- Commits and pull requests are titled `build(deps): ...`, labelled
  `dependencies`.

`mise run renovate-validate` checks `renovate.json` with Renovate's own
validator (needs Docker). CI runs it on every pull request.

## Why a dedicated App

`schubergphilis` is a large organization. The `mdd-renovate` App belongs to
the organization but is installed on `schubergphilis/mdd` only, and the
workflow mints each token for this repository alone, with the permissions
listed in the workflow. A wider installation would still not reach other
repositories through this workflow. Nothing is shared with other Renovate
setups in the organization.

## Setup

The App, created under **Organization settings > Developer settings >
GitHub Apps**:

- Name `mdd-renovate`, webhook off, no events.
- Repository permissions: Administration read, Checks read and write,
  Commit statuses read and write, Contents read and write, Dependabot
  alerts read, Issues read and write, Pull requests read and write,
  Workflows read and write. Metadata read is implied. No organization or
  account permissions. These are the permissions of [Renovate's GitHub App
  docs](https://docs.renovatebot.com/modules/platform/github/#running-as-a-github-app).
- Installable only on this account, and installed on `schubergphilis/mdd`
  only, through **Only select repositories**.

Its client ID and private key are secrets of the `renovate` environment,
which only `main` may deploy to. A workflow on another branch, which anyone
with write access can push, can't read them.

```sh
R=repos/schubergphilis/mdd
gh api -X PUT $R/environments/renovate --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
gh api -X POST $R/environments/renovate/deployment-branch-policies -f name=main -f type=branch
gh secret set RENOVATE_CLIENT_ID -R schubergphilis/mdd -e renovate
gh secret set RENOVATE_PRIVATE_KEY -R schubergphilis/mdd -e renovate < mdd-renovate.private-key.pem
```

Delete the downloaded key file afterwards.

Dependabot alerts stay on, because Renovate reads them. Dependabot security
updates are off, because Renovate opens the fixes.

The `main` ruleset requires a pull request and the `lint-and-test` and
`Zizmor (GitHub Actions audit)` checks. The App is not a bypass actor, so it
can't push to `main`.

## Running it

Run it by hand under **Actions > Renovate > Run workflow**, or:

```sh
gh workflow run renovate.yml -R schubergphilis/mdd                   # everything due now
gh workflow run renovate.yml -R schubergphilis/mdd -f dryRun=lookup  # report only
```

A manual run ignores the Monday schedule unless `force=false`. Each run
uploads a `renovate-report` artifact and lists the open Renovate pull
requests in its summary. The **Dependency Dashboard** issue lists pending,
held, and failed updates.
