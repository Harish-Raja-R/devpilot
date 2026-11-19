# DevPilot technical demonstration guide

## What has and has not been verified

The browser-to-API flow was exercised with a temporary local OpenAI-compatible mock provider through LiteLLM. In the actual UI, the calculator task created `calculator.py` and `test_calculator.py`, requested approval for each write and the pytest run, streamed activity updates, and displayed the real pytest output: **10 passed**. A second UI task was cancelled while waiting for write approval; its status became `cancelled` and the proposed file was not written.

No `.env` or provider credential was configured in the inspected workspace, and `.env.example` contains only a placeholder model. No real external LLM request was made. The temporary mock provider used for the browser demonstration is not included in this repository. Do not present the mock run as a live-provider result.

## Launch the application

From the repository root in PowerShell, install the optional backend dependencies and configure a real LiteLLM-supported provider:

```powershell
python -m pip install -e ".[devpilot]"
Copy-Item .env.example .env
```

Edit `.env` locally: set `DEVPILOT_MODEL_NAME` to the provider-qualified model identifier and set the matching provider API key. Keep the key private and do not commit `.env`. For example, an OpenAI model generally uses `OPENAI_API_KEY`; an Anthropic model generally uses `ANTHROPIC_API_KEY`. Check the selected model's current LiteLLM provider naming before use.

Start the backend in one terminal:

```powershell
devpilot
```

Start the frontend in a second terminal:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. The API is at `http://127.0.0.1:8000`; its OpenAPI page is `http://127.0.0.1:8000/docs`. Detailed setup and configuration are in [IMPLEMENTATION.md](./IMPLEMENTATION.md).

## Suggested live walkthrough

1. Open a trusted local project folder in the workspace selector and create/select a session.
2. Submit: “Create a Python calculator with addition, subtraction, multiplication and division, including input validation and unit tests.”
3. Point out the plan and the activity stream. The stream records task start, model messages, tool calls, observations, approvals, and test results.
4. Review each proposed file write and approve it explicitly. Show the files in the explorer/editor.
5. Review the `python -m pytest` approval request, approve it, and show the actual command output in the test/activity panel. The UI flow previously verified against the local mock reported 10 passed; a new run may differ.
6. Explain that the model receives tool observations on the next request, rather than the UI fabricating a result.
7. For cancellation, submit another task, wait until a file-write approval is pending, then select **Stop** before approving. Confirm the task is `cancelled` and the proposed file does not exist.
8. Show the Git status/diff panel when working in a Git checkout. The calculator demo folder used for the verified UI run was not a Git repository, so it showed no Git repository.
9. Close by describing the local-only security boundary: approvals are useful safeguards, not an OS sandbox.

Only claim a live-provider run if a real provider request was actually performed during the recorded demonstration. If using a mock endpoint, label it clearly as a deterministic mock and distinguish it from a real model.

## Reproducible mocked checks

The committed tests use mocked model responses and exercise sequential tool calls, real workspace operations, approval callbacks, observation feedback, and completion without external credentials:

```powershell
python -m pytest tests\devpilot tests\models\test_actions_toolcall.py -q -rs
```

These automated tests are not a real LLM connectivity check. The temporary local provider used for the browser demonstration was removed after verification; the UI demonstration steps above require a configured provider to repeat interactively.

## Security notes for presenters

- Do not show `.env`, API keys, authorization headers, or secrets in a screen recording.
- Use a disposable, trusted workspace and review code before approving execution.
- File writes/edits and commands/tests are approval-gated. Command execution uses the existing validation policy, argv, `shell=False`, timeouts, and output bounds.
- Approved project code runs with the current OS user's permissions. Use a container or VM for untrusted code.
- The server is intended for loopback use only. Do not expose it on a public interface.
