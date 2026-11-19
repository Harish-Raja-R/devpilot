from unittest.mock import patch

from devpilot.agent import DevPilotAgent
from devpilot.tool_registry import EmptyArguments, ToolRegistry, create_tool_registry
from devpilot.workspace import write_project_file


def test_agent_bounds_history_by_dropping_complete_tool_turns():
    registry = ToolRegistry()
    registry.register("ping", "Return a test observation.", EmptyArguments, lambda _arguments: {"pong": True})
    requests = []

    def completion(**kwargs):
        messages = kwargs["messages"]
        requests.append(messages)
        assert len(messages) <= 7
        assistant_calls = {
            call["id"]
            for message in messages
            if message["role"] == "assistant"
            for call in message.get("tool_calls", [])
        }
        assert all(
            message["tool_call_id"] in assistant_calls
            for message in messages
            if message["role"] == "tool"
        )
        if len(requests) <= 4:
            call = {
                "id": f"ping-{len(requests)}",
                "type": "function",
                "function": {"name": "ping", "arguments": "{}"},
            }
            return {"choices": [{"message": {"role": "assistant", "content": "", "tool_calls": [call]}}]}
        return {"choices": [{"message": {"role": "assistant", "content": "Finished."}}]}

    with patch("devpilot.agent.litellm.completion", side_effect=completion):
        agent = DevPilotAgent(
            "mock",
            registry,
            system_prompt="Test agent.",
            max_iterations=5,
            max_history_messages=7,
        )
        result = agent.run("Repeat the ping tool.")

    assert result.status == "completed"
    assert result.tool_calls == 4
    assert len(requests) == 5
    assert len(agent.messages) == 7


def test_registry_exposes_and_executes_all_nine_structured_tools(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    write_project_file(root, "src/app.py", "VALUE = 1\n")
    calls = []

    def handler(name):
        def execute(arguments):
            calls.append((name, arguments.model_dump()))
            return {"status": "executed"}

        return execute

    registry = create_tool_registry(
        root,
        write_file=handler("write_file"),
        edit_file=handler("edit_file"),
        run_command=handler("run_command"),
        run_tests=handler("run_tests"),
    )
    schemas = registry.schemas()
    expected_names = {
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

    assert {schema["function"]["name"] for schema in schemas} == expected_names
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["parameters"]["additionalProperties"] is False

    assert registry.execute("list_files", {}) == {"ok": True, "result": {"files": ["src/app.py"]}}
    assert registry.execute("read_file", {"path": "src/app.py"}) == {
        "ok": True,
        "result": {"path": "src/app.py", "content": "VALUE = 1\n"},
    }
    matches = registry.execute("search_files", {"query": "value"})
    assert matches["ok"] is True
    assert matches["result"]["matches"][0]["path"] == "src/app.py"
    assert registry.execute("write_file", {"path": "new.py", "content": "x=1"})["ok"] is True
    assert registry.execute(
        "edit_file", {"path": "src/app.py", "old_text": "VALUE", "new_text": "RESULT"}
    )["ok"] is True
    assert registry.execute("run_command", {"command": "python -m pytest"})["ok"] is True
    assert registry.execute("run_tests", {})["ok"] is True
    assert registry.execute("get_git_status", {})["ok"] is True
    assert registry.execute("get_git_diff", {})["ok"] is True
    assert [name for name, _ in calls] == ["write_file", "edit_file", "run_command", "run_tests"]


def test_registry_rejects_bad_json_unknown_tools_and_unsafe_paths(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    registry = create_tool_registry(
        root,
        write_file=lambda _arguments: {"status": "written"},
        edit_file=lambda _arguments: {"status": "edited"},
        run_command=lambda _arguments: {"status": "ran"},
        run_tests=lambda _arguments: {"status": "tested"},
    )

    assert registry.execute("read_file", "{")["ok"] is False
    assert registry.execute("unknown", {})["ok"] is False
    assert registry.execute("read_file", {"path": "../outside.py"})["ok"] is False
    assert registry.execute("list_files", {"path": "../outside"})["ok"] is False
    assert registry.execute(
        "write_file", {"path": "safe.py", "content": "x", "extra": True}
    )["error"] == "Invalid tool arguments."
