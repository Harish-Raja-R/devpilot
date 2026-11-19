# DevPilot technical report outline

Use this as a structure for a report grounded in the implementation and measured runs. Insert environment-specific values only after measuring them; distinguish test doubles from live provider calls.

## 1. Executive summary

- Problem and intended users
- DevPilot's local coding-workspace MVP
- Scope and key results, with the validation date and environment
- Explicit status of live-provider verification

## 2. Project context and attribution

- Existing mini-SWE-agent repository and retained upstream CLI
- DevPilot-specific application code versus reused libraries/services
- License and attribution preserved
- Relationship to upstream documented in [ARCHITECTURE.md](./ARCHITECTURE.md)

## 3. Requirements and scope

- Natural-language coding task submission
- Workspace inspection and file operations
- Approval-gated changes and command execution
- Execution history, cancellation, and live updates
- MVP exclusions and known limitations

## 4. Architecture

- React/Vite/Monaco frontend
- FastAPI backend and task worker
- SQLite persistence for sessions, tasks, and execution events
- `DevPilotAgent`, LiteLLM provider boundary, and `ToolRegistry`
- REST and WebSocket event delivery
- Include an architecture diagram from [ARCHITECTURE.md](./ARCHITECTURE.md)

## 5. Agent execution and conversation management

- System/task message construction and workspace context
- Provider request parameters and structured function schemas
- Tool-call argument validation and dispatch
- Observation messages returned to the model on the next iteration
- Completion detection, bounded history, iteration/runtime limits, errors, and cooperative cancellation
- Clarify that LiteLLM is the provider client; the DevPilot loop and registry are custom application code

## 6. Tool catalog

Describe inputs, effects, and approval requirements for:

- `list_files`, `read_file`, `search_files`
- `write_file`, `edit_file`
- `run_command`, `run_tests`
- `get_git_status`, `get_git_diff`

## 7. Security and privacy

- Workspace path containment and validation
- Pydantic tool-argument validation
- Command allowlist/argv validation, `shell=False`, timeouts, and output limits
- Explicit approval paths for mutations and execution
- Credential handling and sanitized child environment
- Cooperative cancellation, local-only API, and absence of an OS sandbox

## 8. Verification and evidence

Record the exact command, date, runtime, and raw test/build outcome for:

- DevPilot and relevant upstream parser tests
- Ruff
- Frontend production build
- Mocked observation-driven calculator task
- Browser UI task submission, live activity, approvals, test result, and cancellation
- Real provider connectivity (only if an actual external call occurred)

The browser calculator workflow previously verified with a temporary local mock provider produced **10 passed**. This is mock-backed UI integration evidence, not live LLM evidence. Replace or supplement this line only with newly captured results.

## 9. Limitations and future work

- No real provider credentials were configured during the inspected readiness pass
- No cost ceiling is enforced by the custom loop
- Active tasks and pending approvals do not survive a backend restart
- Cancellation cannot immediately interrupt a synchronous provider call or subprocess
- Approval controls do not isolate arbitrary project code from the host OS user
- Potential next steps: isolated execution, persistent worker/approval state, cost budgets, and production auth/deployment

## 10. Reproduction appendix

- Python/Node/npm versions
- Provider configuration requirements (never include key values)
- Exact backend/frontend launch commands
- Automated test, lint, and build commands
- Links to [IMPLEMENTATION.md](./IMPLEMENTATION.md) and [DEMO_GUIDE.md](./DEMO_GUIDE.md)
