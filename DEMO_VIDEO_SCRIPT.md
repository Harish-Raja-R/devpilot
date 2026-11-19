# DevPilot explainer video script

**Target length:** 4–6 minutes
**Recording note:** The previously verified browser walkthrough used a deterministic local mock provider through LiteLLM, not a real external LLM. If recording that configuration, display a persistent “Local mock provider” label. Do not show credentials.

## 0:00–0:25 — Introduction

**On screen:** DevPilot workspace and repository title.

**Narration:** “DevPilot is a local AI coding workspace. It combines a React and Monaco interface with a FastAPI service, SQLite execution history, and a custom tool-using agent loop. It lives alongside mini-SWE-agent, whose original CLI, source, and license are preserved.”

## 0:25–1:10 — Architecture

**On screen:** [ARCHITECTURE.md](./ARCHITECTURE.md), then the workspace.

**Narration:** “A task submitted in the UI is handled by the FastAPI task worker. DevPilot's own `DevPilotAgent` constructs the conversation and sends it through LiteLLM. A separate `ToolRegistry` exposes nine validated tools. LiteLLM is the provider client; it is not the DevPilot execution loop.”

## 1:10–2:10 — Task and tool selection

**On screen:** Submit the calculator task; show activity and plan.

**Narration:** “The model can inspect files, read and search, propose writes or edits, run commands or tests, and inspect Git status and diffs. The model's requested tool name and arguments are validated before dispatch. The tool's actual result becomes an observation in the next model request.”

**On screen:** Activity panel showing `list_files`, file proposal, and approval.

**Narration:** “Here, the model first inspects the workspace. A proposed write pauses for user approval. Once approved, DevPilot writes through its workspace-scoped services and reports the result back to the model.”

## 2:10–3:10 — Approvals and test feedback

**On screen:** Approve the calculator and test files, then approve pytest; show test output.

**Narration:** “Mutating file operations and execution are not silently applied. The user sees the proposed action and approves or rejects it. After pytest runs, its real output is displayed and returned to the model as another observation. In the verified local-mock walkthrough, the calculator suite reported 10 passed. This demonstrates the application workflow; the model endpoint in that run was a mock, not a live provider.”

## 3:10–3:50 — Cancellation

**On screen:** A second task pending a file-write approval; click **Stop**.

**Narration:** “Cancellation is cooperative. This task is waiting for approval, so cancellation resolves the pending proposal without writing the file. The interface records the cancelled status. A currently running synchronous model request or subprocess may take until its configured timeout to stop.”

## 3:50–4:40 — Security and limitations

**On screen:** [SECURITY.md](./SECURITY.md).

**Narration:** “Workspace paths and tool inputs are validated. Commands are checked, executed as argv without a shell, bounded by timeouts and output limits, and require approval. Provider keys remain in the backend environment. These are defense-in-depth controls, not an operating-system sandbox: approved project code still runs with the current user's permissions. DevPilot is local-only and should not be exposed publicly.”

## 4:40–5:00 — Close

**On screen:** README and launch instructions.

**Narration:** “The custom DevPilot engine, tool registry, API integration, frontend, tests, and documentation are in this repository. A real-provider demonstration requires configuring a supported provider and confirming that an actual request succeeds. The automated mocked tests remain available for repeatable, credential-free validation.”
