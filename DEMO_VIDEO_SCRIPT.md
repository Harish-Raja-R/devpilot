# DevPilot explainer video script

**Target length:** approximately 5 minutes (4–6 minutes at a clear speaking pace)

**Recording note:** The verified browser walkthrough used a deterministic local OpenAI-compatible mock provider through LiteLLM. It was not a real external LLM. If showing that run, keep a visible “Local mock provider — not a live LLM” disclosure on screen. A local `.env` exists but is ignored and must not be opened or shown. Never show keys, tokens, or authorization headers.

## 0:00–0:35 — Introduction

**On screen:** Show the DevPilot workspace and title card: “Local AI coding workspace.”

**Narration:** “DevPilot is a local coding workspace for turning a natural-language task into reviewed project changes. It combines a React and Monaco interface, a FastAPI backend, SQLite session and event history, and a custom tool-using agent loop. It is developed alongside mini-SWE-agent: the original `mini` CLI, source, license, and attribution remain in the repository. DevPilot does not route its task loop through the upstream `DefaultAgent`.”

## 0:35–1:15 — Architecture and honest demo disclosure

**On screen:** Briefly show the diagram in [TECHNICAL_REPORT_OUTLINE.md](./TECHNICAL_REPORT_OUTLINE.md), then the application. Keep the mock-provider disclosure visible for the verified run.

**Narration:** “The browser sends task and workspace requests to FastAPI and receives activity through a WebSocket. The backend persists sessions, tasks, and events in SQLite. For this recorded calculator run, LiteLLM connected to a temporary local mock endpoint. That lets us demonstrate the real UI, approval, tool, and test path without credentials; it does not verify a paid provider, model compatibility, or live inference.”

## 1:15–2:15 — Think, Act, Observe

**On screen:** Submit: “Create a Python calculator with addition, subtraction, multiplication and division, including input validation and unit tests.” Show the visible plan and activity stream.

**Narration:** “The task worker gives `DevPilotAgent` the task, a brief system instruction, and bounded project context. The agent sends the conversation and JSON tool schemas through LiteLLM. Think means the model’s request and returned choice; DevPilot does not expose private chain-of-thought. The model can select one tool for a response. Here it first chooses `list_files`. DevPilot validates the tool name and Pydantic arguments, executes it against the selected workspace, and sends the actual result back as a tool observation. The next request can use that observation to choose what to do next.”

**On screen:** Point at `list_files`, its result, and the next model message.

**Narration:** “This is the Think–Act–Observe cycle: model decision, bounded tool action, actual observation, then another model request. The loop ends when the model returns a non-empty final response without a tool call, or when an error, cancellation, or execution limit stops it.”

## 2:15–3:20 — Tools, approvals, and test evidence

**On screen:** Show the file-write approval for `calculator.py`, approve it; then show the test-file proposal and approve it.

**Narration:** “The registry has nine separate tools: list, read, and search files; write and edit files; run an allowed command; run pytest; read Git status; and read Git diff. File writes and edits are not applied when first proposed. The approval card shows the action, and a write is performed only after the user approves. The edit path also checks for one exact match and protects against a concurrent file change.”

**On screen:** Approve the `python -m pytest` request; show the result panel and the created files.

**Narration:** “The test tool requests approval separately. In this previously verified mock-backed UI run, the files were created and pytest reported 10 passed. That is actual pytest output from the workspace. The agent received it as an observation before its final summary. It is evidence for the application flow, not proof that a live model generated the code or that another provider is compatible.”

## 3:20–3:55 — Cancellation

**On screen:** Show the second task paused at file-write approval; click **Stop** and point to the cancelled status.

**Narration:** “Cancellation is cooperative. In this verified case the task was waiting for approval; pressing Stop cancelled the pending proposal, and the proposed file was absent afterward. An in-flight synchronous model request or subprocess cannot necessarily be interrupted immediately; it may continue until its configured timeout.”

## 3:55–4:40 — Security and limitations

**On screen:** Show the relevant section of [SECURITY.md](./SECURITY.md).

**Narration:** “Workspace paths are constrained, tool arguments are schema-validated, and commands are policy-checked and run as argv without a shell. File mutations and execution require approval; timeouts and output limits are applied. The API is intended for loopback use and has no multi-user authentication. Most importantly, approval is not an OS sandbox: an approved test or project script still runs with the current user’s permissions. Use an isolated container or VM for untrusted code.”

## 4:40–5:10 — Validation and close

**On screen:** Show test/lint/build results, then the report and checklist. Do not show secrets or private account data.

**Narration:** “The selected DevPilot and upstream parser tests passed: 46 passed and one symlink test was skipped because this host does not permit symlink creation. Ruff and the frontend production build passed. No real LLM request has been made, so provider availability and connectivity remain unverified. The repository includes reproducible mocked tests, a technical report, and a submission checklist. DevPilot’s custom loop and approval workflow are demonstrated; live-provider support remains to be verified with an authorized provider.”
