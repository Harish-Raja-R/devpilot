"""DevPilot's structured tool-calling agent loop."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Any, Literal

import litellm

from devpilot.tool_registry import ToolRegistry
from devpilot.workspace import MAX_OUTPUT_BYTES

MAX_TOOL_CALLS_PER_RESPONSE = 4
DEFAULT_MAX_HISTORY_MESSAGES = 200


@dataclass(frozen=True)
class AgentResult:
    status: Literal["completed", "failed", "stopped", "cancelled"]
    submission: str
    iterations: int
    model_calls: int
    tool_calls: int
    cost: float | None = None
    error: str | None = None


class DevPilotAgent:
    def __init__(
        self,
        model_name: str,
        tools: ToolRegistry,
        *,
        system_prompt: str,
        request_timeout: int = 120,
        max_iterations: int = 30,
        max_runtime_seconds: int = 1_800,
        max_history_messages: int = DEFAULT_MAX_HISTORY_MESSAGES,
        cancel_event: Event | None = None,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if request_timeout < 1 or max_iterations < 1 or max_runtime_seconds < 1:
            raise ValueError("Agent timeouts and iteration limits must be positive.")
        if max_history_messages < MAX_TOOL_CALLS_PER_RESPONSE + 3:
            raise ValueError(
                f"Agent history must allow at least {MAX_TOOL_CALLS_PER_RESPONSE + 3} messages."
            )
        self.model_name = model_name
        self.tools = tools
        self.system_prompt = system_prompt
        self.request_timeout = request_timeout
        self.max_iterations = max_iterations
        self.max_runtime_seconds = max_runtime_seconds
        self.max_history_messages = max_history_messages
        self.cancel_event = cancel_event or Event()
        self.emit = emit or (lambda _event_type, _payload: None)
        self.messages: list[dict[str, Any]] = []
        self._history_groups: list[list[dict[str, Any]]] = []
        self.model_calls = 0
        self.tool_calls = 0
        self.cost: float | None = None

    def run(self, task: str, *, project_context: str = "") -> AgentResult:
        started = time.monotonic()
        self.messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"Project context:\n{project_context}\n\nTask:\n{task}",
            },
        ]
        self._history_groups = []
        self.model_calls = 0
        self.tool_calls = 0
        self.cost = None

        for iteration in range(1, self.max_iterations + 1):
            if self.cancel_event.is_set():
                return self._result("cancelled", iteration - 1, error="Task cancelled.")
            if time.monotonic() - started >= self.max_runtime_seconds:
                return self._result("stopped", iteration - 1, error="Agent runtime limit reached.")

            response = litellm.completion(
                model=self.model_name,
                messages=self.messages,
                tools=self.tools.schemas(),
                tool_choice="auto",
                timeout=self.request_timeout,
            )
            self.model_calls += 1
            self._record_cost(response)
            choice = _field(response, "choices", [None])[0]
            if choice is None:
                return self._result("failed", iteration, error="The model returned no choices.")
            message = _field(choice, "message")
            if message is None:
                return self._result("failed", iteration, error="The model returned no message.")
            assistant_message = _message_dict(message)
            assistant_message["role"] = "assistant"
            content = assistant_message.get("content") or ""
            self.emit("agent_message", {"role": "assistant", "content": content})
            tool_calls = assistant_message.get("tool_calls") or []

            if not tool_calls:
                self._append_round([assistant_message])
                if _field(choice, "finish_reason") == "length":
                    return self._result("stopped", iteration, submission=content, error="Model response was truncated.")
                if not content.strip():
                    return self._result("failed", iteration, error="The model returned neither a tool call nor a final response.")
                return self._result("completed", iteration, submission=content)

            if self.cancel_event.is_set():
                return self._result("cancelled", iteration, error="Task cancelled.")

            if len(tool_calls) > MAX_TOOL_CALLS_PER_RESPONSE:
                return self._result(
                    "failed",
                    iteration,
                    error=f"The model returned more than {MAX_TOOL_CALLS_PER_RESPONSE} tool calls at once.",
                )

            round_messages = [assistant_message]
            if len(tool_calls) > 1:
                for tool_call in tool_calls:
                    call_id = _field(tool_call, "id")
                    if not call_id:
                        return self._result("failed", iteration, error="The model returned a tool call without an id.")
                    tool_name = _field(_field(tool_call, "function"), "name", "")
                    observation = {
                        "ok": False,
                        "error": "Choose exactly one tool per response; no tools were executed.",
                    }
                    self.emit("tool_result", {"tool": tool_name, **observation})
                    round_messages.append(_tool_message(call_id, observation))
                self._append_round(round_messages)
                continue

            tool_call = tool_calls[0]
            call_id = _field(tool_call, "id")
            function = _field(tool_call, "function")
            tool_name = _field(function, "name", "")
            raw_arguments = _field(function, "arguments", "")
            if not call_id:
                return self._result("failed", iteration, error="The model returned a tool call without an id.")
            self.tool_calls += 1
            self.emit("tool_started", {"tool": tool_name})
            observation = self.tools.execute(tool_name, raw_arguments)
            if len(json.dumps(observation, ensure_ascii=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
                observation = {
                    "ok": False,
                    "error": f"Tool result exceeded the {MAX_OUTPUT_BYTES}-byte observation limit.",
                }
            self.emit("tool_result", {"tool": tool_name, **observation})
            round_messages.append(_tool_message(call_id, observation))
            self._append_round(round_messages)

        return self._result(
            "stopped",
            self.max_iterations,
            error=f"Agent reached its {self.max_iterations}-iteration limit.",
        )

    def _append_round(self, messages: list[dict[str, Any]]) -> None:
        self.messages.extend(messages)
        self._history_groups.append(messages)
        while len(self.messages) > self.max_history_messages and len(self._history_groups) > 1:
            expired = self._history_groups.pop(0)
            del self.messages[2 : 2 + len(expired)]

    def _record_cost(self, response: Any) -> None:
        hidden = _field(response, "_hidden_params", {})
        cost = _field(hidden, "response_cost")
        if isinstance(cost, (int, float)):
            self.cost = (self.cost or 0.0) + float(cost)

    def _result(
        self,
        status: Literal["completed", "failed", "stopped", "cancelled"],
        iterations: int,
        *,
        submission: str = "",
        error: str | None = None,
    ) -> AgentResult:
        return AgentResult(
            status=status,
            submission=submission,
            iterations=iterations,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            cost=self.cost,
            error=error,
        )


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _message_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return dict(message)
    model_dump = getattr(message, "model_dump", None)
    if callable(model_dump):
        return model_dump(exclude_none=True)
    raise TypeError("The model response message cannot be converted to a conversation message.")


def _tool_message(call_id: str, observation: dict[str, Any]) -> dict[str, str]:
    content = json.dumps(observation, ensure_ascii=False)
    return {"role": "tool", "tool_call_id": call_id, "content": content}
