# DevPilot final submission checklist

## Implementation and evidence

- [x] DevPilot uses its own `DevPilotAgent` loop and `ToolRegistry`; mini-SWE-agent's original CLI and source remain intact.
- [x] Nine structured tools are registered, with validation and approval gates for mutations/execution.
- [x] SQLite session/task/event history and the React/FastAPI integration are present.
- [x] Mocked sequential tool tests use real workspace operations and actual pytest output.
- [x] Current focused validation: 46 passed, 1 skipped; Ruff passed; frontend production build passed.
- [x] Browser UI calculator and cancellation flows were exercised with a temporary local mock provider. Label the run as mock-backed, not live LLM.
- [ ] Run the symlink-specific test on a host that allows symlink creation.
- [ ] If live model performance is part of judging, configure an authorized provider and make a real minimal task run. Record provider/model identity and result without recording credentials.

## Documentation and presentation

- [x] [DEMO_GUIDE.md](./DEMO_GUIDE.md) distinguishes mock and live-provider evidence and documents approvals/cancellation.
- [x] [TECHNICAL_REPORT_OUTLINE.md](./TECHNICAL_REPORT_OUTLINE.md) contains an implementation-grounded report draft and measured verification.
- [x] [DEMO_VIDEO_SCRIPT.md](./DEMO_VIDEO_SCRIPT.md) labels the mock-provider demonstration.
- [x] [INTERVIEW_EXPLANATION.md](./INTERVIEW_EXPLANATION.md) provides a concise technical explanation.
- [ ] Before recording, verify that screen sharing does not expose `.env`, API keys, tokens, private workspace data, or unrelated account information.
- [ ] Record and review the video; ensure any mocked endpoint is visibly disclosed as a mock.

## Repository and publication

- [x] Local Git repository is on `main`, has two existing commits, and was clean before this documentation update.
- [x] Original MIT license and attribution are present.
- [x] `.gitignore` excludes local environment/secrets, virtual environments, dependency folders, and build/database outputs while retaining `.env.example`.
- [x] The user supplied the existing destination; pre-push `git ls-remote` returned no refs, so there was no remote commit to merge.
- [x] No repository was created; the existing local `main` history is being preserved.
- [ ] Configure `origin`, commit the reviewed project changes, push `main` without force, then verify the remote branch and commit.
- [x] GitHub CLI (`gh`) is not installed, so account-level authentication/repository discovery was unavailable; the specified destination was checked directly with Git.
- [x] `.env` and credential values are not intended for publication. Never publish `.env` or credentials.

## Operational cautions

- [ ] Configure `DEVPILOT_MODEL_NAME` and the matching provider key in a local, ignored `.env` before a live task.
- [ ] Use a disposable trusted project for demonstrations; review every file/command/test approval.
- [ ] Do not expose the loopback API to the public internet. Approval controls do not sandbox code running as the current OS user.
- [ ] Do not claim provider compatibility, model quality, or live inference until a real request has succeeded.
