# DevPilot implementation and setup

## Requirements

- Python 3.10+ and Node.js 20+
- A LiteLLM-supported provider account/API key for actual agent tasks
- The original mini-SWE-agent source and license in this repository

## Install

From the repository root in PowerShell:

```powershell
python -m pip install -e ".[devpilot]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Set `DEVPILOT_MODEL_NAME` to a provider-qualified model name and set the matching provider credential in `.env` (for example `OPENAI_API_KEY` for an OpenAI model or `ANTHROPIC_API_KEY` for Anthropic). API credentials are read only by the backend/LiteLLM; they are not sent to the browser. Do not commit `.env`.

Install the frontend:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

In another terminal, from the repository root:

```powershell
python -m devpilot.run
```

The API binds to `127.0.0.1:8000`; the Vite UI binds to `127.0.0.1:5173` and proxies `/api` and WebSocket traffic. Visit `http://127.0.0.1:5173`. FastAPI docs are at `http://127.0.0.1:8000/docs`.

For a step-by-step demonstration and submission materials, see [DEMO_GUIDE.md](./DEMO_GUIDE.md), [TECHNICAL_REPORT_OUTLINE.md](./TECHNICAL_REPORT_OUTLINE.md), and [DEMO_VIDEO_SCRIPT.md](./DEMO_VIDEO_SCRIPT.md).

The original `mini` command is unchanged. For example, `mini --help` and the upstream mini-SWE-agent usage remain available.

## Configuration

| Variable | Default | Description |
|---|---:|---|
| `DEVPILOT_MODEL_NAME` | unset | LiteLLM provider/model name used for tasks |
| `DEVPILOT_HOST` | `127.0.0.1` | Must be a loopback address |
| `DEVPILOT_PORT` | `8000` | Backend port |
| `DEVPILOT_DB_PATH` | `%USERPROFILE%\.devpilot\sessions.sqlite3` | Session, task, and event database |
| `DEVPILOT_AGENT_MAX_ITERATIONS` | `30` | Agent model-turn limit (1–200) |
| `DEVPILOT_COMMAND_TIMEOUT` | `60` | Approved command timeout in seconds (1–300) |
| `DEVPILOT_MODEL_TIMEOUT` | `120` | Timeout for each provider request in seconds (1–120) |
| Provider-specific keys | provider-dependent | Read by LiteLLM; never returned by API endpoints |

The custom DevPilot loop also enforces a 30-minute wall-clock limit and bounds retained conversation history. LiteLLM may report provider cost when available; the custom loop does not impose a cost ceiling.

## Implemented behavior

- `src/devpilot/agent.py` owns DevPilot's LiteLLM request loop, bounded conversation, tool-call handling, observation feedback, completion detection, iteration/runtime limits, cancellation checks, and structured result.
- `src/devpilot/tool_registry.py` registers nine independently callable, Pydantic-validated tools: `list_files`, `read_file`, `search_files`, `write_file`, `edit_file`, `run_command`, `run_tests`, `get_git_status`, and `get_git_diff`.
- The task worker in `src/devpilot/api.py` uses this custom engine by default and connects mutating/execution tools to the existing workspace validation, file concurrency checks, approval gates, SQLite history, and live events.
- Uses the actual LiteLLM response and tool observations. Missing model configuration, provider failures, tool validation errors, and execution failures are explicit; no model response or execution result is fabricated.
- Supports workspace/session/task history, file listing/reading/search, approval-gated file writes and edits, test runs, Git status/diff, output capture, and model/task completion events.
- Requires approval for each agent file write/edit, command/code execution, dependency install, test run, editor write, and requested deletion. Git write/commit/push commands are rejected by the existing command policy.
- Shows actual command output and Git diff text. Git status/diff reports that no repository exists when the selected folder is not a Git checkout.
- Project language/framework/dependency context is built from bounded file lists and manifests, not by loading all source into the prompt.

## Differences from upstream

DevPilot's original application code includes `src/devpilot/agent.py`, `src/devpilot/tool_registry.py`, the `devpilot` entry point, FastAPI session/event/workspace APIs and approval integration, the frontend, and associated documentation/tests. It uses LiteLLM as its provider client and reuses DevPilot's pre-existing workspace/path/command/approval services. The original mini-SWE-agent `src/minisweagent` package, `mini` CLI, `DefaultAgent` loop, configuration system, model integrations, environment implementations, and upstream tests are retained and continue to power the standalone CLI; they do not power DevPilot's task loop. The source attribution and MIT license remain in [LICENSE.md](./LICENSE.md).

## Known limitations

- The backend is local-only and does not provide multi-user authentication or remote deployment.
- The approval policy and argv validation reduce accidental exposure but are **not an operating-system sandbox**. An approved project script or package-manager hook can still access resources permitted to the logged-in user. Review project code before approving execution; use an OS/container sandbox for untrusted repositories.
- Pending approvals and running workers are process-local. Session/task/event history is durable, but a restart does not resume a task.
- Project browsing currently accepts a local folder path typed/pasted by the user; browser-native arbitrary filesystem access is not requested.
- The Git diff view displays actual tracked changes and includes readable text diffs for untracked UTF-8 files.
- Live integration with a paid model requires the user's own provider configuration; CI tests use deterministic test models and do not claim a real provider call.
