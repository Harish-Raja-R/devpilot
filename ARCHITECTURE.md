# DevPilot architecture

## Application and retained upstream project

DevPilot is the local coding-agent application layered alongside the original mini-SWE-agent project. Its task execution loop is implemented in `src/devpilot/agent.py`; it does not delegate task orchestration or tool parsing to mini-SWE-agent.

The original mini-SWE-agent source, attribution, MIT license, configuration, model integrations, environments, CLI entry point (`mini`), and upstream tests remain in the repository. The CLI continues to use its original `DefaultAgent` and model/tool-call implementation. DevPilot uses LiteLLM for provider requests, but its messages, loop, tool registry, and completion handling are its own application code.

## DevPilot components

```text
React + Vite + Tailwind
  ├─ Monaco editor, file explorer, task/chat and approval UI
  ├─ Activity, terminal output, test output and Git diff panels
  └─ REST + WebSocket event stream
          │
          ▼
FastAPI (devpilot.api)
  ├─ SQLite sessions, tasks and append-only execution events
  ├─ Workspace-scoped file/project/Git services
  ├─ Approval gate for file edits, commands and tests
  └─ background task worker
          │
          ▼
DevPilotAgent (devpilot.agent) ── LiteLLM provider request
  ├─ bounded messages, iteration/time limits, cancellation
  ├─ structured tool-call validation and observations
  └─ ToolRegistry (devpilot.tool_registry)
       ├─ read-only workspace/file/search/Git tools
       └─ approval-gated write/edit/command/test callbacks
```

## Agent and conversation flow

1. The FastAPI task worker resolves the configured provider model, inspects the selected workspace, and creates the DevPilot tool registry with callbacks into the existing workspace and approval services.
2. `DevPilotAgent` starts a conversation containing its system instructions and the user's task plus bounded project metadata. It calls `litellm.completion` with the selected model, conversation, registry-generated function schemas, `tool_choice="auto"`, and the configured request timeout. LiteLLM reads provider credentials from the backend environment.
3. A response without tool calls and with non-empty, non-truncated assistant text is a task completion. A response with tool calls is appended to the conversation and validated against the selected tool's Pydantic schema. The loop executes at most one tool per response. If the model returns 2–4 calls, none are executed and each receives a rejection observation; more than four calls fail that model turn.
4. The registry executes the validated tool and returns a JSON observation. The assistant tool-call message and matching `role="tool"` observation are appended together, then sent on the next provider request. Conversation history is bounded by dropping complete old tool-call/observation groups while retaining the initial task context.
5. The loop stops on a final answer, iteration/runtime limit, cancellation, or surfaced error. Its structured result includes status, final submission, iteration/model/tool counts, optional provider-reported cost, and a stop/error reason.

## Tool registry and security boundary

The registered tools are `list_files`, `read_file`, `search_files`, `write_file`, `edit_file`, `run_command`, `run_tests`, `get_git_status`, and `get_git_diff`. Each has a JSON function schema backed by Pydantic validation; unknown fields, malformed JSON, unknown tools, and invalid arguments become explicit tool errors for the model. Workspace reads, searches, and Git helpers reuse `devpilot.workspace` path scoping and output bounds.

File writes and edits use DevPilot's existing approval endpoint, concurrency hash, and file-size/path checks. An edit must find exactly one matching old-text occurrence. Commands pass the existing allowlist and path/operator checks and execute as argv with `shell=False`, in the selected workspace, with a sanitized child environment, timeout, and bounded output. Test runs require a separate approval. Approval denial, timeout, tool validation errors, and command failures are returned as observations; they do not masquerade as success.

Cancellation is cooperative between model/tool steps and while waiting on an approval. A synchronous LiteLLM request or running subprocess cannot be interrupted immediately; it is bounded by its configured provider or command timeout. Approval gates and workers remain process-local. These controls are not an OS sandbox: an approved project script can access resources permitted to the logged-in user.

## API surface

FastAPI's OpenAPI page is available at `/docs`. Main endpoints include:

- `POST/GET /api/sessions`, `GET /api/sessions/{id}`
- `POST/GET /api/sessions/{id}/tasks`, `POST /api/sessions/{id}/tasks/{task}/start`
- `POST /api/sessions/{id}/tasks/{task}/cancel`
- `GET /api/sessions/{id}/events` and `/api/sessions/{id}/events/ws`
- `GET /api/sessions/{id}/files`, `GET /api/sessions/{id}/file`
- `PUT /api/sessions/{id}/file` (propose a change; writing occurs only after approval)
- `POST /api/sessions/{id}/file-delete` (propose deletion; unlink occurs only after approval)
- `GET /api/sessions/{id}/search`, `/git/status`, `/git/diff`
- `GET/PUT /api/sessions/{id}/approvals`
- `POST/GET /api/sessions/{id}/tests`

## Persistence

Session metadata, task records, and event history are stored in SQLite at `%USERPROFILE%\\.devpilot\\sessions.sqlite3` by default (or `DEVPILOT_DB_PATH`). Pending approval payloads and active workers/cancellation events are in memory. A backend restart does not resume a task or preserve a pending approval.
