"""Structured DevPilot tools and argument validation."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from devpilot.workspace import (
    MAX_FILE_BYTES,
    CommandValidationError,
    WorkspaceError,
    git_diff,
    git_status,
    list_project_files,
    read_project_file,
    search_project,
)


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListFilesArguments(ToolArguments):
    path: str | None = None


class ReadFileArguments(ToolArguments):
    path: str = Field(min_length=1, max_length=1_024)


class SearchFilesArguments(ToolArguments):
    query: str = Field(min_length=1, max_length=200)


class WriteFileArguments(ToolArguments):
    path: str = Field(min_length=1, max_length=1_024)
    content: str = Field(max_length=MAX_FILE_BYTES)


class EditFileArguments(ToolArguments):
    path: str = Field(min_length=1, max_length=1_024)
    old_text: str = Field(min_length=1, max_length=MAX_FILE_BYTES)
    new_text: str = Field(max_length=MAX_FILE_BYTES)


class RunCommandArguments(ToolArguments):
    command: str = Field(min_length=1, max_length=4_096)


class EmptyArguments(ToolArguments):
    pass


class ToolFailure(Exception):
    """A tool failed in a way that should be returned to the model as an observation."""


ToolHandler = Callable[[BaseModel], Any]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type[ToolArguments]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        arguments: type[ToolArguments],
        handler: ToolHandler,
    ) -> None:
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = ToolDefinition(name, description, arguments, handler)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, raw_arguments: str | dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"ok": False, "error": f"Unknown tool '{name}'."}
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except json.JSONDecodeError as error:
            return {"ok": False, "error": f"Tool arguments must be valid JSON: {error.msg}."}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "Tool arguments must be a JSON object."}
        try:
            validated = tool.arguments.model_validate(arguments)
        except ValidationError as error:
            details = [
                {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
                for item in error.errors()
            ]
            return {"ok": False, "error": "Invalid tool arguments.", "details": details}
        try:
            return {"ok": True, "result": tool.handler(validated)}
        except (ToolFailure, WorkspaceError, CommandValidationError, OSError) as error:
            return {"ok": False, "error": str(error)}


def create_tool_registry(
    root: Path,
    *,
    write_file: ToolHandler,
    edit_file: ToolHandler,
    run_command: ToolHandler,
    run_tests: ToolHandler,
) -> ToolRegistry:
    registry = ToolRegistry()

    def list_files(arguments: BaseModel) -> dict[str, Any]:
        path = ListFilesArguments.model_validate(arguments).path
        files = list_project_files(root)
        if path:
            candidate = Path(path)
            if candidate.is_absolute() or candidate.drive or ".." in PurePath(path).parts:
                raise WorkspaceError("Absolute paths and parent-directory traversal are not allowed.")
            prefix = path.replace("\\", "/").strip("/")
            if prefix not in {"", "."}:
                files = [item for item in files if item == prefix or item.startswith(f"{prefix}/")]
        return {"files": files}

    def read_file(arguments: BaseModel) -> dict[str, str]:
        parsed = ReadFileArguments.model_validate(arguments)
        return {"path": parsed.path, "content": read_project_file(root, parsed.path)}

    def search_files(arguments: BaseModel) -> dict[str, Any]:
        parsed = SearchFilesArguments.model_validate(arguments)
        return {"matches": search_project(root, parsed.query)}

    registry.register("list_files", "List workspace-relative project files.", ListFilesArguments, list_files)
    registry.register("read_file", "Read a UTF-8 text file in the workspace.", ReadFileArguments, read_file)
    registry.register("search_files", "Find literal text in workspace files.", SearchFilesArguments, search_files)
    registry.register("write_file", "Create or replace a file after user approval.", WriteFileArguments, write_file)
    registry.register("edit_file", "Replace one exact text occurrence after user approval.", EditFileArguments, edit_file)
    registry.register("run_command", "Run one allowlisted command after user approval.", RunCommandArguments, run_command)
    registry.register("run_tests", "Run the workspace pytest suite after user approval.", EmptyArguments, run_tests)
    registry.register("get_git_status", "Read the workspace Git status.", EmptyArguments, lambda _: git_status(root))
    registry.register("get_git_diff", "Read the workspace Git diff.", EmptyArguments, lambda _: git_diff(root))
    return registry
