# DevPilot security

## Local API and credentials

DevPilot is a local developer tool, not a multi-user service. The supported `devpilot` launcher binds to a loopback address and rejects non-loopback HTTP/WebSocket clients. CORS is limited to the local Vite origin. Do not run it on a public interface, reverse-proxy it, or expose `/docs`/the API to an untrusted network. The app has no user authentication because it is designed for a single local user.

Provider API keys stay in the backend process environment and are not part of session responses, model names, event payloads, or frontend assets. Child commands receive a filtered environment that excludes common API-key, token, password, credential, authorization, and secret variables. Keep `.env` out of version control.

## Workspace and file operations

- Session file paths must be relative to the selected workspace. Absolute paths, parent traversal, escaping symlinks, non-text/oversized file reads, and oversized writes are rejected.
- DevPilot's structured tool arguments are validated before dispatch. Read/search/Git tools use workspace-scoped helpers; Git tools are read-only.
- File writes and deletes initiated through the editor/API are proposals. The user must explicitly approve them; writes verify the file hash has not changed since it was opened/proposed.
- Workspace scans skip symlinks and common generated/dependency directories. Search and command outputs are bounded.
- A selected folder is an explicit user choice. Avoid opening a directory containing secrets or files that should not be available to an agent.

## Command execution and approvals

- The web client has no free-form terminal endpoint. Model-proposed commands are parsed into argv and executed with `shell=False` only after a separate approval decision.
- Commands are parsed to argv and never passed through a shell, so shell chaining, redirection, and pipelines are not interpreted. Parent traversal, arbitrary executable names, and write-capable Git operations are rejected. Python execution (including inline code) is permitted only as a visible, explicitly approved action so the agent can make changes and run project code.
- Dependency installs, test execution, and all agent terminal commands require approval. Processes have bounded timeouts and captured output; Git commit/push is not supported.
- A denied command is returned to the model as a failed observation, never reported as executed.
- Cancellation is cooperative while waiting for approval and between tool/model steps. A running provider request or subprocess may continue until its configured timeout.

## Security boundary and residual risk

This approval and command policy is defense-in-depth, not a sandbox. Running user-approved Python/Node scripts, tests, or package lifecycle hooks executes project code with the current OS user's permissions. Such code may access files outside the workspace or use network access. The API cannot reliably infer every side effect in arbitrary program code. Treat untrusted repositories as untrusted code and run them in a dedicated container/VM or another OS-level sandbox before approving execution. Do not assume path checks on editor APIs constrain arbitrary program behavior.

There is no automatic project-file deletion, commit, or remote push. Deletion is a separate explicit proposal and requires approval. The API does not include a deployment/remote execution feature.

## Reporting

Do not expose the backend outside loopback. For a security issue in this DevPilot addition, report it privately to the project maintainer before public disclosure. Upstream mini-SWE-agent security guidance is also in [docs/SECURITY.md](./docs/SECURITY.md).
