# Issue tracker: GitHub

Issues for `mdd` are managed as GitHub issues on `schubergphilis/mdd`, the
same remote as the source code.

Use the `gh` CLI for all operations. The working tree has several remotes
(`gitlab`, `lsimons`, `bot`), so pass `-R schubergphilis/mdd` explicitly
rather than relying on `gh` picking the right one:

```bash
gh -R schubergphilis/mdd issue list --label needs-triage
gh -R schubergphilis/mdd issue view <number>
gh -R schubergphilis/mdd issue create --title "..." --body "..." --label needs-triage
gh -R schubergphilis/mdd issue edit <number> --add-label ready-for-agent --remove-label needs-triage
```

`gh issue --help` documents the rest.

Do not put a closing keyword (`closes #NNN`, `fixes #NNN`) in a commit that
lands directly on `main` — it auto-closes the issue before the work is
reviewed. Put it in the pull request body instead.

## Labels

| Label             | Description                                        | Colour  |
| ----------------- | -------------------------------------------------- | ------- |
| `bug`             | Something isn't working                            | #d73a4a |
| `documentation`   | Improvements or additions to documentation         | #0075ca |
| `enhancement`     | New feature or request                             | #a2eeef |
| `needs-triage`    | Maintainer needs to evaluate this issue            | #e6e6fa |
| `needs-info`      | Waiting on reporter for more information           | #e6e6fa |
| `ready-for-agent` | Fully specified, ready for an autonomous agent     | #e6e6fa |
| `ready-for-human` | Requires human implementation                      | #e6e6fa |
| `wontfix`         | This will not be worked on                         | #ffffff |
| `duplicate`       | This issue or pull request already exists          | #cfd3d7 |
| `invalid`         | This doesn't seem right                            | #e4e669 |
| `question`        | Further information is requested                   | #d876e3 |
| `good first issue`| Good for newcomers                                 | #7057ff |
| `help wanted`     | Extra attention is needed                          | #008672 |

Renovate puts `dependencies` on its own pull requests
([dependency-updates.md](dependency-updates.md)). Do not apply it by hand.

## Triage flow

1. A new issue gets `needs-triage`.
2. A maintainer adds a kind label (`bug` / `enhancement` / `documentation`).
3. If the report is incomplete, `needs-info` replaces `needs-triage` until
   the reporter answers.
4. Once the issue states what to change and how to verify it, it becomes
   `ready-for-agent` (an autonomous agent can take it end to end) or
   `ready-for-human` (it needs judgement, a live service, or Microsoft
   Office on macOS that an agent does not have).
5. `wontfix` closes it with a written reason.

An issue that would need a design decision is not `ready-for-agent`. It
needs a spec in `docs/spec/` first — see
[`000-specs.md`](../spec/000-specs.md).
