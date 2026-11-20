import json
import sqlite3
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from devpilot.api import EventStore, create_app


def tool_call(name, arguments, call_id="call-1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def model_response(content="", call=None):
    message = {"role": "assistant", "content": content}
    if call is not None:
        message["tool_calls"] = [call]
    return {"choices": [{"message": message, "finish_reason": "tool_calls" if call else "stop"}]}


class ObservationDrivenCalculatorModel:

    def __init__(self):
        self.observations = []
        self.requests = []
        self.provider_requests = []

    def __call__(self, *, messages, **kwargs):
        self.requests.append(messages)
        self.provider_requests.append(kwargs)
        observations = [
            json.loads(message["content"])
            for message in messages
            if message.get("role") == "tool"
        ]
        self.observations.append(observations)

        if not observations:
            return model_response(
                "I will inspect the workspace, create the calculator and tests, then run them.",
                tool_call("list_files", {}),
            )
        elif len(observations) == 1:
            assert observations[-1] == {"ok": True, "result": {"files": []}}
            calculator = (
                "import math\n"
                "\n"
                "def parse_number(value: str) -> float:\n"
                "    try:\n"
                "        number = float(value)\n"
                "    except (TypeError, ValueError) as error:\n"
                "        raise ValueError('Enter a valid number.') from error\n"
                "    if not math.isfinite(number):\n"
                "        raise ValueError('Number must be finite.')\n"
                "    return number\n"
                "\n"
                "def calculate(left: float, operator: str, right: float) -> float:\n"
                "    if operator == '+':\n"
                "        return left + right\n"
                "    if operator == '-':\n"
                "        return left - right\n"
                "    if operator == '*':\n"
                "        return left * right\n"
                "    if operator == '/':\n"
                "        if right == 0:\n"
                "            raise ValueError('Cannot divide by zero.')\n"
                "        return left / right\n"
                "    raise ValueError('Unsupported operator.')\n"
                "\n"
                "def main() -> None:\n"
                "    try:\n"
                "        left = parse_number(input('First number: '))\n"
                "        operator = input('Operator (+, -, *, /): ')\n"
                "        right = parse_number(input('Second number: '))\n"
                "        result = calculate(left, operator, right)\n"
                "    except ValueError as error:\n"
                "        print(error)\n"
                "        raise SystemExit(1) from error\n"
                "    print(result)\n"
                "\n"
                "if __name__ == '__main__':\n"
                "    main()\n"
            )
            return model_response(
                "The workspace is clear; I will create the calculator module.",
                tool_call("write_file", {"path": "calculator.py", "content": calculator}),
            )
        elif len(observations) == 2:
            assert observations[-1]["ok"] is True
            assert observations[-1]["result"]["path"] == "calculator.py"
            tests = (
                "import pytest\n"
                "from calculator import calculate, parse_number\n"
                "\n"
                "@pytest.mark.parametrize(('operator', 'expected'), [\n"
                "    ('+', 7), ('-', 3), ('*', 10), ('/', 2.5),\n"
                "])\n"
                "def test_arithmetic(operator, expected):\n"
                "    assert calculate(5, operator, 2) == expected\n"
                "\n"
                "def test_parse_number_accepts_numeric_input():\n"
                "    assert parse_number('2.5') == 2.5\n"
                "\n"
                "@pytest.mark.parametrize('value', ['invalid', 'nan', 'inf'])\n"
                "def test_parse_number_rejects_invalid_or_non_finite_input(value):\n"
                "    with pytest.raises(ValueError):\n"
                "        parse_number(value)\n"
                "\n"
                "def test_calculate_rejects_unsupported_operator():\n"
                "    with pytest.raises(ValueError, match='Unsupported'):\n"
                "        calculate(1, '^', 2)\n"
                "\n"
                "def test_division_by_zero_is_rejected():\n"
                "    with pytest.raises(ValueError, match='zero'):\n"
                "        calculate(1, '/', 0)\n"
            )
            return model_response(
                "The calculator is in place; I will add unit tests.",
                tool_call("write_file", {"path": "test_calculator.py", "content": tests}),
            )
        elif len(observations) == 3:
            assert observations[-1]["ok"] is True
            assert observations[-1]["result"]["path"] == "test_calculator.py"
            return model_response(
                "Both files were written; I will run the workspace test suite.",
                tool_call("run_tests", {}),
            )
        elif len(observations) == 4:
            test_observation = observations[-1]
            assert test_observation["ok"] is True
            test_result = test_observation["result"]
            assert test_result["returncode"] == 0
            assert test_result["status"] == "passed"
            assert "10 passed" in test_result["output"]
            return model_response(
                "The actual pytest output confirms 10 passing tests. "
                "Created calculator.py and test_calculator.py; 10 tests passed."
            )
        else:
            raise AssertionError("The custom DevPilot loop made an unexpected additional model request.")


@pytest.fixture
def api(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    app = create_app(tmp_path / "sessions.sqlite3", enforce_loopback=False)
    with TestClient(app) as client:
        response = client.post("/api/sessions", json={"workspace": str(workspace)})
        assert response.status_code == 201
        yield client, workspace, response.json()["id"]


def test_existing_database_migrates_task_model_name_column(tmp_path):
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE tasks (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, task TEXT NOT NULL, "
            "status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )

    EventStore(database)

    with sqlite3.connect(database) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
    assert "model_name" in columns


def test_session_files_search_git_and_history_are_workspace_scoped(api):
    client, workspace, session_id = api
    source = workspace / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")

    assert client.get(f"/api/sessions/{session_id}/files").json()["files"] == ["app.py"]
    file_response = client.get(f"/api/sessions/{session_id}/file", params={"path": "app.py"})
    assert file_response.json()["content"] == "VALUE = 1\n"
    assert len(file_response.json()["sha256"]) == 64
    assert client.get(f"/api/sessions/{session_id}/search", params={"q": "value"}).json()["matches"][0]["path"] == "app.py"
    assert client.get(f"/api/sessions/{session_id}/file", params={"path": "../secret"}).status_code == 400
    assert client.get(f"/api/sessions/{session_id}/git/status").json()["is_git_repo"] is False
    assert client.get(f"/api/sessions/{session_id}/events").json()[0]["type"] == "session_created"


def test_websocket_streams_persisted_session_events(api):
    client, _, session_id = api
    with client.websocket_connect(f"/api/sessions/{session_id}/events/ws") as websocket:
        streamed = websocket.receive_json()
    assert streamed["type"] == "session_created"


def test_websocket_accepts_configured_frontend_origin(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("DEVPILOT_FRONTEND_ORIGIN", "http://127.0.0.1:5175")
    app = create_app(tmp_path / "sessions.sqlite3", enforce_loopback=False)
    with TestClient(app) as client:
        session_id = client.post("/api/sessions", json={"workspace": str(workspace)}).json()["id"]
        with client.websocket_connect(
            f"/api/sessions/{session_id}/events/ws",
            headers={"origin": "http://127.0.0.1:5175"},
        ) as websocket:
            streamed = websocket.receive_json()
    assert streamed["type"] == "session_created"


def test_file_updates_and_deletes_wait_for_approval(api):
    client, workspace, session_id = api
    original = workspace / "existing.py"
    original.write_text("before\n", encoding="utf-8")
    opened = client.get(f"/api/sessions/{session_id}/file", params={"path": "existing.py"}).json()
    proposed = client.put(
        f"/api/sessions/{session_id}/file",
        json={"path": "existing.py", "content": "after\n", "expected_sha256": opened["sha256"]},
    ).json()
    assert original.read_text(encoding="utf-8") == "before\n"
    assert client.get(f"/api/sessions/{session_id}/approvals").json()[0]["kind"] == "file_write"
    assert client.put(
        f"/api/sessions/{session_id}/approvals/{proposed['approval_id']}", json={"approved": True}
    ).status_code == 200
    assert original.read_text(encoding="utf-8") == "after\n"

    deletion = client.post(
        f"/api/sessions/{session_id}/file-delete", json={"path": "existing.py"}
    ).json()
    assert original.exists()
    client.put(f"/api/sessions/{session_id}/approvals/{deletion['approval_id']}", json={"approved": True})
    assert not original.exists()


def test_file_approval_detects_concurrent_changes(api):
    client, workspace, session_id = api
    file = workspace / "main.py"
    file.write_text("initial", encoding="utf-8")
    opened = client.get(f"/api/sessions/{session_id}/file", params={"path": "main.py"}).json()
    proposal = client.put(
        f"/api/sessions/{session_id}/file",
        json={"path": "main.py", "content": "proposed", "expected_sha256": opened["sha256"]},
    ).json()
    file.write_text("concurrent edit", encoding="utf-8")
    response = client.put(
        f"/api/sessions/{session_id}/approvals/{proposal['approval_id']}", json={"approved": True}
    )
    assert response.status_code == 409
    assert file.read_text(encoding="utf-8") == "concurrent edit"


def test_test_run_is_gated_and_emits_result(api):
    client, _, session_id = api
    started = client.post(f"/api/sessions/{session_id}/tests").json()
    approvals = client.get(f"/api/sessions/{session_id}/approvals").json()
    assert approvals[0]["kind"] == "test_run"
    client.put(
        f"/api/sessions/{session_id}/approvals/{started['test_run_id']}", json={"approved": False}
    )
    for _ in range(50):
        results = client.get(f"/api/sessions/{session_id}/tests").json()
        if results:
            break
        time.sleep(0.02)
    assert results[0]["payload"]["status"] == "rejected"


def test_approved_test_run_executes_workspace_tests(api):
    client, workspace, session_id = api
    (workspace / "test_smoke.py").write_text("def test_smoke():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    started = client.post(f"/api/sessions/{session_id}/tests").json()
    approval = client.get(f"/api/sessions/{session_id}/approvals").json()[0]

    assert approval["kind"] == "test_run"
    assert client.put(
        f"/api/sessions/{session_id}/approvals/{started['test_run_id']}",
        json={"approved": True},
    ).status_code == 200
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        results = client.get(f"/api/sessions/{session_id}/tests").json()
        if results:
            break
        time.sleep(0.02)

    assert results[0]["payload"]["status"] == "passed"
    assert "1 passed" in results[0]["payload"]["output"]


def test_expired_approval_cannot_be_applied_later(api):
    client, _, session_id = api
    service = client.app.state.service
    gate = service.create_approval(session_id, "command", {"command": "git status"})
    assert service.wait_for_approval(session_id, gate, timeout=0) is False
    assert gate.status == "expired"
    response = client.put(
        f"/api/sessions/{session_id}/approvals/{gate.id}", json={"approved": True}
    )
    assert response.status_code == 409


def test_missing_model_configuration_fails_task_without_calling_provider(api, monkeypatch):
    client, _, session_id = api
    monkeypatch.setenv("DEVPILOT_MODEL_NAME", "")
    monkeypatch.setenv("MSWEA_MODEL_NAME", "")
    task = client.post(
        f"/api/sessions/{session_id}/tasks", json={"task": "No model is configured."}
    ).json()

    with patch("devpilot.agent.litellm.completion") as completion:
        assert client.post(f"/api/sessions/{session_id}/tasks/{task['id']}/start").status_code == 202
        for _ in range(100):
            events = client.get(f"/api/sessions/{session_id}/events").json()
            errors = [event for event in events if event["type"] == "task_error"]
            if errors:
                break
            time.sleep(0.02)

    assert errors[0]["payload"]["error"].startswith("ValueError: Set DEVPILOT_MODEL_NAME")
    assert client.get(f"/api/sessions/{session_id}/tasks").json()[0]["status"] == "failed"
    completion.assert_not_called()


def test_provider_authentication_error_is_reported_without_retrying(api, monkeypatch):
    client, _, session_id = api
    monkeypatch.setenv("OPENAI_API_KEY", "")
    task = client.post(
        f"/api/sessions/{session_id}/tasks",
        json={"task": "Check provider authentication.", "model_name": "openai/example-model"},
    ).json()
    with patch(
        "devpilot.agent.litellm.completion",
        side_effect=RuntimeError("Missing API key."),
    ) as completion:
        assert client.post(f"/api/sessions/{session_id}/tasks/{task['id']}/start").status_code == 202
        for _ in range(100):
            events = client.get(f"/api/sessions/{session_id}/events").json()
            errors = [event for event in events if event["type"] == "task_error"]
            if errors:
                break
            time.sleep(0.02)

    assert "API key" in errors[0]["payload"]["error"]
    completion.assert_called_once()


def run_mock_task(client, session_id, task_text, model, *, approve=True, model_name="mock"):
    task = client.post(
        f"/api/sessions/{session_id}/tasks",
        json={"task": task_text, "model_name": model_name},
    ).json()
    with patch("devpilot.agent.litellm.completion", side_effect=model) as completion:
        assert client.post(f"/api/sessions/{session_id}/tasks/{task['id']}/start").status_code == 202
        events = []
        for _ in range(1_000):
            events = client.get(f"/api/sessions/{session_id}/events").json()
            pending = [
                approval
                for approval in client.get(f"/api/sessions/{session_id}/approvals").json()
                if approval["status"] == "pending"
            ]
            for approval in pending:
                decision = approve(approval) if callable(approve) else approve
                client.put(
                    f"/api/sessions/{session_id}/approvals/{approval['id']}",
                    json={"approved": decision},
                )
            if any(event["type"] in {"task_finished", "task_error"} for event in events):
                break
            time.sleep(0.02)
        model_calls = completion.call_count
    assert any(event["type"] in {"task_finished", "task_error"} for event in events)
    return task, events, model_calls


def test_agent_creates_calculator_from_observations_and_runs_its_tests(api):
    client, workspace, session_id = api
    model = ObservationDrivenCalculatorModel()
    task, events, model_calls = run_mock_task(
        client,
        session_id,
        "Create a Python calculator with addition, subtraction, multiplication and division, including input validation and unit tests.",
        model,
        model_name="mock-calculator",
    )
    completed = next(event for event in events if event["type"] == "task_finished")
    assert completed["payload"]["status"] == "completed"
    assert completed["payload"]["tool_calls"] == 4
    assert completed["payload"]["model_calls"] == model_calls == 5
    assert (workspace / "calculator.py").is_file()
    assert (workspace / "test_calculator.py").is_file()
    test_result = next(event for event in events if event["type"] == "test_result")
    assert test_result["payload"]["returncode"] == 0
    assert test_result["payload"]["status"] == "passed"
    assert "10 passed" in test_result["payload"]["output"]
    assert model.observations[0] == []
    assert model.observations[1][0]["result"]["files"] == []
    assert model.observations[2][-1]["result"]["path"] == "calculator.py"
    assert model.observations[3][-1]["result"]["path"] == "test_calculator.py"
    assert "10 passed" in model.observations[4][-1]["result"]["output"]
    assert len(model.requests) == 5
    assert "Create a Python calculator" in model.requests[0][1]["content"]
    assert task["model_name"] == "mock-calculator"
    assert model.provider_requests[0]["model"] == "mock-calculator"
    assert model.provider_requests[0]["timeout"] == 120
    assert {schema["function"]["name"] for schema in model.provider_requests[0]["tools"]} == {
        "list_files",
        "read_file",
        "search_files",
        "write_file",
        "edit_file",
        "run_command",
        "run_tests",
        "get_git_status",
        "get_git_diff",
    }


def test_agent_executes_file_edit_search_git_and_approved_command_tools(api):
    client, workspace, session_id = api
    source = workspace / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    requests = []

    def model(*, messages, **kwargs):
        requests.append(messages)
        observations = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if not observations:
            return model_response(call=tool_call("list_files", {}))
        if len(observations) == 1:
            assert observations[-1]["result"]["files"] == ["app.py"]
            return model_response(call=tool_call("read_file", {"path": "app.py"}))
        if len(observations) == 2:
            assert observations[-1]["result"]["content"] == "VALUE = 1\n"
            return model_response(call=tool_call("search_files", {"query": "value"}))
        if len(observations) == 3:
            assert observations[-1]["result"]["matches"][0]["path"] == "app.py"
            return model_response(call=tool_call(
                "edit_file", {"path": "app.py", "old_text": "VALUE = 1", "new_text": "VALUE = 2"}
            ))
        if len(observations) == 4:
            assert observations[-1]["result"]["status"] == "edited"
            return model_response(call=tool_call("get_git_status", {}))
        if len(observations) == 5:
            assert observations[-1]["result"]["is_git_repo"] is False
            return model_response(call=tool_call("get_git_diff", {}))
        if len(observations) == 6:
            assert observations[-1]["result"]["is_git_repo"] is False
            return model_response(call=tool_call("run_command", {"command": "python -c print(123)"}))
        assert len(observations) == 7
        assert observations[-1]["result"]["returncode"] == 0
        assert "123" in observations[-1]["result"]["output"]
        return model_response("The approved command succeeded.")

    _, events, calls = run_mock_task(client, session_id, "Inspect, edit, and verify a file.", model)
    finished = next(event for event in events if event["type"] == "task_finished")
    assert calls == 8
    assert finished["payload"]["tool_calls"] == 7
    assert source.read_text(encoding="utf-8") == "VALUE = 2\n"
    assert any(event["type"] == "command_result" for event in events)
    assert any(event["type"] == "file_changed" for event in events)
    assert len(requests) == 8


def test_agent_returns_argument_validation_error_as_observation(api):
    client, workspace, session_id = api
    requests = []

    def model(*, messages, **kwargs):
        requests.append(messages)
        observations = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if not observations:
            return model_response(call=tool_call("write_file", {
                "path": "bad.py",
                "content": "not written",
                "unexpected": True,
            }))
        assert observations[-1]["ok"] is False
        assert observations[-1]["error"] == "Invalid tool arguments."
        return model_response("The invalid arguments were rejected.")

    _, events, calls = run_mock_task(client, session_id, "Reject unknown arguments.", model)
    finished = next(event for event in events if event["type"] == "task_finished")
    assert calls == 2
    assert finished["payload"]["tool_calls"] == 1
    assert not (workspace / "bad.py").exists()
    assert not client.get(f"/api/sessions/{session_id}/approvals").json()
    assert len(requests) == 2


def test_agent_stops_at_iteration_limit(api, monkeypatch):
    client, _, session_id = api
    monkeypatch.setenv("DEVPILOT_AGENT_MAX_ITERATIONS", "1")

    def model(**kwargs):
        return model_response(call=tool_call("list_files", {}))

    _, events, calls = run_mock_task(client, session_id, "Stop after one iteration.", model)
    finished = next(event for event in events if event["type"] == "task_finished")
    assert calls == 1
    assert finished["payload"]["status"] == "stopped"
    assert finished["payload"]["error"].endswith("1-iteration limit.")


def test_command_policy_failure_is_observed_and_not_executed(api):
    client, workspace, session_id = api
    requests = []

    def model(*, messages, **kwargs):
        requests.append(messages)
        observations = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if not observations:
            return model_response(call=tool_call("run_command", {"command": "powershell -Command whoami"}))
        assert observations[-1]["ok"] is False
        assert "not an allowed workspace command" in observations[-1]["error"]
        return model_response("The unapproved executable was blocked.")

    _, events, calls = run_mock_task(client, session_id, "Check command restrictions.", model)
    assert calls == 2
    assert not (workspace / "whoami").exists()
    assert any(event["type"] == "command_rejected" for event in events)
    assert not any(event["type"] == "command_result" for event in events)
    assert len(requests) == 2


def test_rejected_file_approval_does_not_write_file(api):
    client, workspace, session_id = api
    requests = []

    def model(*, messages, **kwargs):
        requests.append(messages)
        observations = [json.loads(message["content"]) for message in messages if message["role"] == "tool"]
        if not observations:
            return model_response(call=tool_call("write_file", {"path": "denied.py", "content": "VALUE = 1\n"}))
        assert observations[-1]["ok"] is False
        assert "not approved" in observations[-1]["error"]
        return model_response("The write was denied and no file was created.")

    run_mock_task(client, session_id, "Try writing a file.", model, approve=False)
    assert not (workspace / "denied.py").exists()
    assert len(requests) == 2


def test_cancelled_task_stops_while_waiting_for_approval(api):
    client, workspace, session_id = api
    task = client.post(
        f"/api/sessions/{session_id}/tasks",
        json={"task": "Write then cancel.", "model_name": "mock"},
    ).json()
    with patch(
        "devpilot.agent.litellm.completion",
        return_value=model_response(call=tool_call("write_file", {"path": "cancel.py", "content": "x=1\n"})),
    ):
        assert client.post(f"/api/sessions/{session_id}/tasks/{task['id']}/start").status_code == 202
        for _ in range(100):
            pending = [
                item for item in client.get(f"/api/sessions/{session_id}/approvals").json()
                if item["status"] == "pending"
            ]
            if pending:
                break
            time.sleep(0.02)
        assert pending
        assert client.post(f"/api/sessions/{session_id}/tasks/{task['id']}/cancel").status_code == 202
        for _ in range(100):
            events = client.get(f"/api/sessions/{session_id}/events").json()
            if any(event["type"] == "task_finished" for event in events):
                break
            time.sleep(0.02)
    finished = next(event for event in events if event["type"] == "task_finished")
    assert finished["payload"]["status"] == "cancelled"
    assert not (workspace / "cancel.py").exists()
