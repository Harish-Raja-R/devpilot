# DevPilot interview explanation

## 60-second overview

“DevPilot is a local AI coding workspace built alongside mini-SWE-agent. The React/Monaco frontend submits tasks to a FastAPI backend, which stores sessions, tasks, and activity events in SQLite and streams updates to the UI. For each task, a custom `DevPilotAgent` sends the system prompt, task, and bounded workspace context to a configured model through LiteLLM. The model chooses from nine structured tools exposed by a Pydantic-validated `ToolRegistry`. The backend executes the selected tool, returns the real result as an observation in the next model request, and repeats until a final response or a configured limit. File changes, commands, and tests require user approval. The DevPilot loop and registry are our application code; LiteLLM and the retained mini-SWE-agent project are dependencies/context, not claims of original authorship. We verified sequential tool behavior and the UI approval/test/cancellation flow with mocks; we have not verified a real provider call because no provider credentials are configured.”

## If asked how the loop works

1. The task worker resolves the configured model and inspects the workspace.
2. `DevPilotAgent` creates the system/task messages and sends them with the JSON tool schemas to `litellm.completion`.
3. It reads the assistant response, validates a selected tool's arguments, and dispatches at most one tool per response.
4. It appends the assistant tool call and the actual tool observation to conversation history, then makes the next model request.
5. A non-empty assistant message with no tool call is completion; iteration/runtime limits, errors, or cancellation stop execution.

## If asked what is original versus reused

“The DevPilot-specific loop, tool registry, FastAPI task/approval integration, workspace UI, and their tests are our application implementation. LiteLLM provides provider compatibility and the app reuses its selected workspace/security services. The upstream mini-SWE-agent CLI, `DefaultAgent`, models, environments, tests, license, and attribution are retained; DevPilot does not use the upstream `DefaultAgent` as its task loop.”

## If asked about safety

“Paths are scoped to a selected workspace; arguments are schema-validated; file mutations and command/test runs require approval; commands are validated and run as argv without a shell, with timeouts and bounded output. These are defense-in-depth controls, not an OS sandbox: an approved test or project script still runs with the current user's permissions. The app is designed for local loopback use and has no multi-user authentication.”

## If asked about evidence

“The selected test run passed 46 tests with one symlink test skipped because this host disallows symlink creation; Ruff and the frontend production build passed. An observation-driven mocked calculator workflow created files, ran pytest, and observed 10 passing tests. The browser flow also used a temporary local mock provider. We have not made a real external LLM request, so I would not claim live-provider verification.”

## Likely technical questions

### Why build a custom loop instead of using mini-SWE-agent's `DefaultAgent`?

“The project objective was for DevPilot to own and clearly expose its execution loop and structured tools. The FastAPI task worker calls `DevPilotAgent`; mini-SWE-agent's original CLI and `DefaultAgent` remain intact for the standalone `mini` workflow. We reuse LiteLLM and workspace/approval services rather than claiming every dependency or upstream component was written from scratch.”

### What exactly is sent to the model?

“Each request includes the system message, the user's task with bounded project context, retained conversation messages, and the registry-generated JSON function schemas. LiteLLM receives the configured model name and request timeout. Provider credentials stay in the backend process. We do not expose hidden chain-of-thought.”

### How does the agent select and execute a tool?

“The model returns a structured function call. DevPilot resolves the tool name, validates JSON against that tool's Pydantic argument model, and dispatches the registered handler. At most one tool is executed per model response. An observation contains the handler's actual result and is included in the next request.”

### What if the model asks for multiple tools or sends invalid arguments?

“Invalid JSON, unknown tools, non-object arguments, unknown fields, and schema violations are rejected and represented as failed observations. If it asks for two through four tools in one response, none run and the model receives a rejection observation for each. More than four calls fails that turn. This keeps execution bounded and preserves the single-action conversation shape.”

### How do you know the task is complete?

“A non-empty assistant response without tool calls completes the task, unless the model response was truncated; truncation stops the task. An empty answer without a tool call fails. DevPilot does not wait for mini-SWE-agent's completion sentinel.”

### What happens before a file write or command runs?

“The API validates the workspace path or command policy and creates a pending approval. The UI presents the proposed action. File changes are applied only after approval and are protected by a concurrency hash. Commands are executed as argv with `shell=False` only after approval; pytest has its own approval request.”

### How does cancellation work, and what are its limits?

“Stop sets a cancellation event. The agent checks between steps, and the approval wait observes it periodically, so a pending write can be cancelled without applying it. A synchronous provider call or subprocess is not immediately interruptible and can continue until its configured timeout.”

### Is this a secure sandbox?

“No. Path checks, argument validation, approvals, command restrictions, timeouts, output bounds, and a filtered child environment reduce risk. Approved project code still runs with the current OS user's permissions. Untrusted code should run in a container or VM; the local API is not a public multi-user service.”

### What do the tests prove—and what do they not prove?

“The observation-driven model double chooses sequential tools based on actual observations. The tools operate on a temporary workspace and execute pytest; the test checks the real test output. The browser demonstration also used a local mock provider through LiteLLM. These verify orchestration, API/UI events, approvals, and test execution, but not live provider connectivity, model quality, or provider/model compatibility.”

### What is persisted, and what remains in memory?

“SQLite stores sessions, tasks, and events. Active workers, cancellation events, and pending approvals are process-local, so a restart does not resume a running task or approval. Making execution restart-safe is a possible future enhancement, not a current guarantee.”

### What would you improve next?

“First, configure an authorized provider and make a real minimal smoke-test call, without recording its key. Next, run the symlink test on a host that permits symlinks and add OS-level isolation for untrusted projects. Longer term, I would consider persistent worker state and a cost budget. GitHub authentication/repository discovery is also still pending because `gh` is not installed; no remote or publication has been set up.”
