# DevPilot testing

## Run tests

Install the DevPilot backend extra and run the focused tests:

```powershell
python -m pip install -e ".[devpilot]"
python -m pytest tests/devpilot -q
```

Run the retained upstream test suite as well:

```powershell
python -m pytest -q
```

Build the React application:

```powershell
Set-Location frontend
npm install
npm run build
```

## Test coverage

The DevPilot tests cover:

- Workspace path traversal and symlink protection, bounded files/output, project scanning/search, command policy, timeouts, and dependency-install classifications.
- Session creation/history, file reads/search, Git repository detection, approval-gated modifications/deletion, optimistic concurrency checks, and rejected test runs.
- The integrated `DefaultAgent` loop with a deterministic test model, a proposed command, explicit user approval, actual script execution, and completion only after the completion sentinel is observed.

Existing upstream agent/model/environment tests are retained unchanged. Those tests cover the original agent's step/cost/time limits, observation handling, model message parsing, and environment behavior.

## Integration validation boundaries

Deterministic tests do not represent paid provider calls. To verify a configured provider manually, set a real LiteLLM model and its provider key, start the API and UI, create a disposable Git workspace, submit a small task, inspect/approve each proposal, and verify the resulting tests and Git diff. Do not use a production workspace for first-run validation.
