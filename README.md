# DevPilot

DevPilot is a local AI coding workspace for working with projects on your computer. It combines a browser-based editor and file explorer with an approval-gated coding agent.

The agent uses a configured LiteLLM-supported model to inspect a selected workspace, propose changes, run approved commands and tests, and report its results in the UI.

## Features

- Browse, search, and edit files in a selected local workspace.
- Create sessions and follow task activity as it happens.
- Use structured agent tools for reading, searching, writing, editing, testing, and read-only Git inspection.
- Review and approve file changes, deletions, commands, dependency installs, and test runs before execution.
- View command output, test results, and Git diffs in the workspace.
- Keep session, task, and event history in a local SQLite database.

## Requirements

- Python 3.10 or later
- Node.js 20 or later
- A LiteLLM-supported provider and API key to run agent tasks

## Quick start

Run these commands from the repository root in PowerShell:

```powershell
python -m pip install -e ".[devpilot]"
Copy-Item .env.example .env
```

Edit `.env` and set `DEVPILOT_MODEL_NAME` to a provider-qualified model name, along with the matching provider API key. For example, an OpenAI model generally uses `OPENAI_API_KEY`; an Anthropic model generally uses `ANTHROPIC_API_KEY`. Keep this file private and do not commit it.

Start the backend in one terminal:

```powershell
python -m devpilot.run
```

Start the frontend in another terminal:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The backend API is at [http://127.0.0.1:8000](http://127.0.0.1:8000), and its interactive API documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

For detailed configuration and setup guidance, see [IMPLEMENTATION.md](./IMPLEMENTATION.md).

## Using the workspace

1. Enter a local project folder and open it to create a session.
2. Select the session and describe the coding task in the AI Agent panel.
3. Review proposed file changes and commands. Approve only the actions you want the agent to perform.
4. Follow activity, tests, command output, and Git changes in the workspace.

The backend binds to loopback by default. Keep it local and use a trusted workspace.

## Security

Approvals are safeguards, not an operating-system sandbox. Approved project scripts, tests, and package lifecycle hooks run with the current user's permissions and may access resources outside the selected workspace. Review actions before approving them; use a container or virtual machine for untrusted code.

Provider credentials are read by the backend and should never be committed or shared in recordings. See [SECURITY.md](./SECURITY.md) for the security boundary and additional guidance.

## Development and tests

Run the DevPilot backend tests from the repository root:

```powershell
python -m pytest tests\devpilot -q
```

Run the frontend tests and production build:

```powershell
Set-Location frontend
npm.cmd test
npm.cmd run build
```

The retained Python command-line interface can also be run with `mini --help`. Its implementation and original documentation remain separate from the DevPilot application.

More about the application:

- [Architecture](./ARCHITECTURE.md)
- [Implementation and configuration](./IMPLEMENTATION.md)
- [Security](./SECURITY.md)
- [Testing](./TESTING.md)
- [Demonstration guide](./DEMO_GUIDE.md)

## Upstream attribution and license

This repository includes and modifies portions of [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent), alongside the DevPilot application. The original copyright and MIT license terms are retained in [LICENSE.md](./LICENSE.md); keep that notice with distributions of the retained upstream portions.
