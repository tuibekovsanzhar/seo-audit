# Stage 2

Stage 2 is the local web app. Its guide is [WEB-APP.md](WEB-APP.md) and its API is [WEB-API.md](WEB-API.md).

History of the stages, as Git tags on branch `stage1-integration` (nothing was pushed):

| Tag | Holds |
|---|---|
| `pre-stage1` | The project as it was, plus the previously untracked Lite helper. |
| `stage1-integrated` | Engine and report repairs ([STAGE-1.md](STAGE-1.md)). |
| `stage2-web-app` | The first web app (conversation-centred API under `/api`). Superseded by the next two. |
| `stage3-engine-checks` | Skill readiness gate, STR-16, STR-17, progress counters, full affected-page lists. |
| `stage4-web-v1` | The web app rebuilt to the full specification: `/api/v1`, confirm step, one-at-a-time queue, event stream, comparison, profile, PDF. |

To look at any of them without changing your files: `git log --oneline --decorate`, `git show <tag> --stat`,
`git diff <tag> <tag>`.
