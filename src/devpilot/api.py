"""Local FastAPI application integrating DevPilot's custom agent engine."""

import asyncio
import hashlib
import ipaddress
import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import dotenv
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from devpilot.agent import DevPilotAgent
from devpilot.tool_registry import (
    EditFileArguments,
    EmptyArguments,
    RunCommandArguments,
    ToolFailure,
    WriteFileArguments,
    create_tool_registry,
)
from devpilot.workspace import (
    MAX_FILE_BYTES,
    CommandValidationError,
    WorkspaceError,
    git_diff,
    git_status,
    inspect_project,
    list_project_files,
    read_project_file,
    resolve_workspace_path,
    run_workspace_command,
    search_project,
    validate_command,
    write_project_file,
)

dotenv.load_dotenv()


class SessionCreate(BaseModel):
    workspace: str = Field(min_length=1, max_length=4_096)
    title: str | None = Field(default=None, max_length=200)


class TaskCreate(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    model_name: str | None = Field(default=None, max_length=200)


class TaskStart(BaseModel):
    model_name: str | None = Field(default=None, max_length=200)


class ApprovalDecision(BaseModel):
    approved: bool


class FileChangeRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1_024)
    content: str = Field(max_length=MAX_FILE_BYTES)
    expected_sha256: str | None = Field(default=None, max_length=64)


class FileDeleteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=1_024)


class EventStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    task TEXT NOT NULL,
                    model_name TEXT,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id),
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            task_columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "model_name" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN model_name TEXT")

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_session(self, session_id: str, workspace: Path, title: str) -> dict[str, Any]:
        now = time.time()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, str(workspace), title, "idle", now, now),
            )
        return self.get_session(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 100").fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def update_session(self, session_id: str, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status, time.time(), session_id),
            )

    def create_task(self, task_id: str, session_id: str, task: str, model_name: str | None = None) -> dict[str, Any]:
        now = time.time()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO tasks (id, session_id, task, model_name, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_id, session_id, task, model_name, "queued", now, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at DESC LIMIT 100", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_task(self, task_id: str, status: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", (status, time.time(), task_id))

    def add_event(self, session_id: str, event_type: str, payload: dict[str, Any], task_id: str | None = None) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO events (session_id, task_id, event_type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, task_id, event_type, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            connection.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))
            return int(cursor.lastrowid)

    def events_after(self, session_id: str, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE session_id = ? AND id > ? ORDER BY id LIMIT ?",
                (session_id, after, limit),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": row["session_id"],
                "task_id": row["task_id"],
                "type": row["event_type"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


class ApprovalGate:
    def __init__(self, approval_id: str, kind: str, details: dict[str, Any]):
        self.id = approval_id
        self.kind = kind
        self.details = details
        self.status = "pending"
        self.approved: bool | None = None
        self.event = threading.Event()
        self.expected_sha256: str | None = None
        self.pending_content: str | None = None

class DevPilotService:
    def __init__(self, store: EventStore):
        self.store = store
        self.lock = threading.RLock()
        self.pending_approvals: dict[str, dict[str, ApprovalGate]] = {}
        self.active_tasks: set[str] = set()
        self.task_cancellations: dict[str, threading.Event] = {}

    def emit(self, session_id: str, event_type: str, payload: dict[str, Any], task_id: str | None = None) -> int:
        return self.store.add_event(session_id, event_type, payload, task_id)

    def create_approval(
        self,
        session_id: str,
        kind: str,
        details: dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> ApprovalGate:
        gate = ApprovalGate(uuid.uuid4().hex, kind, details)
        with self.lock:
            self.pending_approvals.setdefault(session_id, {})[gate.id] = gate
        self.emit(session_id, "approval_required", {"id": gate.id, "kind": kind, "details": details}, task_id)
        return gate

    def list_approvals(self, session_id: str) -> list[dict[str, Any]]:
        with self.lock:
            gates = list(self.pending_approvals.get(session_id, {}).values())
        return [
            {"id": gate.id, "kind": gate.kind, "details": gate.details, "status": gate.status}
            for gate in gates
        ]

    def wait_for_approval(
        self,
        session_id: str,
        gate: ApprovalGate,
        timeout: int = 300,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while not gate.event.wait(min(0.25, max(0, deadline - time.monotonic()))):
            if cancel_event is not None and cancel_event.is_set():
                with self.lock:
                    if gate.status == "pending":
                        gate.status = "cancelled"
                        gate.event.set()
                self.emit(
                    session_id,
                    "approval_resolved",
                    {"id": gate.id, "kind": gate.kind, "status": gate.status},
                )
                return False
            if time.monotonic() >= deadline:
                break
        if gate.event.is_set():
            return gate.approved is True
        expired = False
        with self.lock:
            if gate.status == "pending":
                gate.status = "expired"
                gate.event.set()
                expired = True
            approved = gate.approved is True
        if expired:
            self.emit(
                session_id,
                "approval_resolved",
                {"id": gate.id, "kind": gate.kind, "status": "expired"},
            )
        return approved

    def approve(self, session_id: str, approval_id: str, approved: bool) -> dict[str, Any]:
        with self.lock:
            gate = self.pending_approvals.get(session_id, {}).get(approval_id)
            if gate is None:
                raise HTTPException(status_code=404, detail="Approval request not found.")
            if gate.status != "pending":
                raise HTTPException(status_code=409, detail="This approval has already been resolved.")
            gate.status = "resolving"
        try:
            if gate.kind in {"file_write", "file_delete"} and approved:
                session = self.require_session(session_id)
                root = Path(session["workspace"])
                target = resolve_workspace_path(
                    root, gate.details["path"], allow_missing=gate.kind == "file_write"
                )
                current_hash = _file_sha256(target) if target.is_file() else None
                if current_hash != gate.expected_sha256:
                    raise HTTPException(status_code=409, detail="File changed after the approval was requested.")
                if gate.kind == "file_write":
                    if gate.pending_content is None:
                        raise HTTPException(status_code=409, detail="The proposed file content is unavailable.")
                    write_project_file(root, gate.details["path"], gate.pending_content)
                else:
                    target.unlink()
                gate.approved = True
                gate.status = "approved"
                gate.event.set()
                self.emit(
                    session_id,
                    "file_changed" if gate.kind == "file_write" else "file_deleted",
                    {"path": gate.details["path"], "approval_id": gate.id},
                )
            else:
                gate.approved = approved
                gate.status = "approved" if approved else "rejected"
                gate.event.set()
        except Exception:
            gate.status = "pending"
            raise
        self.emit(
            session_id,
            "approval_resolved",
            {"id": gate.id, "kind": gate.kind, "status": gate.status},
        )
        return {"id": gate.id, "status": gate.status}

    def require_session(self, session_id: str) -> dict[str, Any]:
        session = self.store.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        return session

    def start_agent(self, session_id: str, task_id: str, model_name: str | None) -> None:
        with self.lock:
            if task_id in self.active_tasks:
                raise HTTPException(status_code=409, detail="Task is already running.")
            if any(
                self.store.get_task(existing_id)["session_id"] == session_id
                for existing_id in self.active_tasks
                if self.store.get_task(existing_id)
            ):
                raise HTTPException(status_code=409, detail="This session already has a running task.")
            self.active_tasks.add(task_id)
            self.task_cancellations[task_id] = threading.Event()
        thread = threading.Thread(
            target=self._run_agent,
            args=(session_id, task_id, model_name),
            name=f"devpilot-{task_id[:8]}",
            daemon=True,
        )
        thread.start()

    def cancel_agent(self, session_id: str, task_id: str) -> dict[str, str]:
        task = self.store.get_task(task_id)
        if task is None or task["session_id"] != session_id:
            raise HTTPException(status_code=404, detail="Task not found.")
        with self.lock:
            cancel_event = self.task_cancellations.get(task_id)
            if cancel_event is None:
                raise HTTPException(status_code=409, detail="Task is not running.")
            cancel_event.set()
        self.emit(session_id, "task_cancellation_requested", {"task_id": task_id}, task_id)
        return {"task_id": task_id, "status": "cancellation_requested"}

    def _run_agent(self, session_id: str, task_id: str, model_name: str | None) -> None:
        task_record = self.store.get_task(task_id)
        session = self.store.get_session(session_id)
        if task_record is None or session is None:
            return
        root = Path(session["workspace"])
        self.store.update_task(task_id, "running")
        self.store.update_session(session_id, "running")
        self.emit(session_id, "task_started", {"task": task_record["task"]}, task_id)
        try:
            command_timeout = _bounded_setting("DEVPILOT_COMMAND_TIMEOUT", 60, 1, 300)
            model_timeout = _bounded_setting("DEVPILOT_MODEL_TIMEOUT", 120, 1, 120)
            iteration_limit = _bounded_setting("DEVPILOT_AGENT_MAX_ITERATIONS", 30, 1, 200)
            configured_model = model_name or os.getenv("DEVPILOT_MODEL_NAME") or os.getenv("MSWEA_MODEL_NAME")
            if not configured_model:
                raise ValueError("Set DEVPILOT_MODEL_NAME and the provider API key in the backend environment.")
            project = inspect_project(root)
            cancel_event = self.task_cancellations[task_id]

            def wait_for_tool_approval(kind: str, details: dict[str, Any]) -> ApprovalGate:
                gate = self.create_approval(session_id, kind, details, task_id=task_id)
                self.emit(session_id, "tool_approval_requested", {"id": gate.id, "kind": kind}, task_id)
                if not self.wait_for_approval(session_id, gate, cancel_event=cancel_event):
                    raise ToolFailure(
                        "Task was cancelled while waiting for approval."
                        if cancel_event.is_set()
                        else "Operation was not approved or its approval request expired."
                    )
                return gate

            def write_file(arguments: WriteFileArguments) -> dict[str, str]:
                try:
                    gate = self.propose_file_change(
                        session_id,
                        FileChangeRequest(path=arguments.path, content=arguments.content),
                        task_id=task_id,
                    )
                except HTTPException as error:
                    raise ToolFailure(str(error.detail)) from error
                if not self.wait_for_approval(session_id, gate, cancel_event=cancel_event):
                    raise ToolFailure(
                        "Task was cancelled while waiting for file approval."
                        if cancel_event.is_set()
                        else "File change was not approved or its approval request expired."
                    )
                return {"path": arguments.path, "status": "written"}

            def edit_file(arguments: EditFileArguments) -> dict[str, str]:
                try:
                    target = resolve_workspace_path(root, arguments.path)
                    original = read_project_file(root, arguments.path)
                except (WorkspaceError, OSError) as error:
                    raise ToolFailure(str(error)) from error
                if original.count(arguments.old_text) != 1:
                    raise ToolFailure("The target text must occur exactly once in the file.")
                updated = original.replace(arguments.old_text, arguments.new_text, 1)
                try:
                    gate = self.propose_file_change(
                        session_id,
                        FileChangeRequest(
                            path=arguments.path,
                            content=updated,
                            expected_sha256=_file_sha256(target),
                        ),
                        task_id=task_id,
                    )
                except HTTPException as error:
                    raise ToolFailure(str(error.detail)) from error
                if not self.wait_for_approval(session_id, gate, cancel_event=cancel_event):
                    raise ToolFailure(
                        "Task was cancelled while waiting for file approval."
                        if cancel_event.is_set()
                        else "File change was not approved or its approval request expired."
                    )
                return {"path": arguments.path, "status": "edited"}

            def run_command(arguments: RunCommandArguments) -> dict[str, Any]:
                try:
                    argv, approval_kind = validate_command(arguments.command, root)
                except CommandValidationError as error:
                    self.emit(
                        session_id,
                        "command_rejected",
                        {"command": arguments.command, "reason": str(error)},
                        task_id,
                    )
                    raise ToolFailure(f"Command blocked by DevPilot safety policy: {error}") from error
                gate = wait_for_tool_approval(
                    approval_kind,
                    {
                        "command": arguments.command,
                        "explanation": "Review the complete command and its project-code effects before execution.",
                    },
                )
                self.emit(
                    session_id,
                    "command_proposed",
                    {"command": arguments.command, "approval_id": gate.id},
                    task_id,
                )
                result = run_workspace_command(argv, root, timeout=command_timeout)
                self.emit(
                    session_id,
                    "command_result",
                    {"command": arguments.command, **result},
                    task_id,
                )
                if cancel_event.is_set():
                    raise ToolFailure("Task was cancelled after the command completed.")
                if gate.approved is not True:
                    raise ToolFailure("Command execution was not approved.")
                return result

            def run_tests(_arguments: EmptyArguments) -> dict[str, Any]:
                gate = wait_for_tool_approval(
                    "test_run",
                    {"command": "python -m pytest", "explanation": "Run the workspace pytest suite."},
                )
                result = run_workspace_command(
                    ["python", "-m", "pytest"],
                    root,
                    timeout=min(300, command_timeout),
                )
                result["status"] = "passed" if result["returncode"] == 0 else "failed"
                self.emit(session_id, "test_result", {"id": gate.id, **result}, task_id)
                if cancel_event.is_set():
                    raise ToolFailure("Task was cancelled after the test run completed.")
                return result

            registry = create_tool_registry(
                root,
                write_file=write_file,
                edit_file=edit_file,
                run_command=run_command,
                run_tests=run_tests,
            )
            agent = DevPilotAgent(
                configured_model,
                registry,
                system_prompt=(
                    "You are DevPilot, an AI coding agent working only in the selected workspace. "
                    "Start with a brief user-visible plan, inspect relevant files, make focused changes, "
                    "and run tests when useful. "
                    "Choose exactly one registered tool per response. File and Git tools are workspace-scoped; "
                    "approved code execution is not an operating-system sandbox. Do not attempt to access "
                    "external paths, credentials, or networks. "
                    "File writes/edits, commands, and tests require user approval and may be denied. "
                    "Do not claim an operation succeeded unless its tool observation confirms it. "
                    "When the task is complete, respond with a concise summary based on observed results."
                ),
                request_timeout=model_timeout,
                max_iterations=iteration_limit,
                max_runtime_seconds=1_800,
                cancel_event=cancel_event,
                emit=lambda event_type, payload: self.emit(session_id, event_type, payload, task_id),
            )
            result = agent.run(
                task_record["task"],
                project_context=json.dumps(project, ensure_ascii=False),
            )
            if result.status == "failed":
                raise RuntimeError(result.error or "The agent failed.")
            status = result.status
            self.store.update_task(task_id, status)
            self.emit(
                session_id,
                "task_finished",
                {
                    "status": status,
                    "exit_status": status,
                    "submission": result.submission,
                    "iterations": result.iterations,
                    "model_calls": result.model_calls,
                    "tool_calls": result.tool_calls,
                    "cost": result.cost,
                    "error": result.error,
                },
                task_id,
            )
            self.store.update_session(session_id, "idle")
        except Exception as error:
            self.store.update_task(task_id, "failed")
            self.store.update_session(session_id, "error")
            self.emit(session_id, "task_error", {"error": f"{type(error).__name__}: {error}"}, task_id)
        finally:
            with self.lock:
                self.active_tasks.discard(task_id)
                self.task_cancellations.pop(task_id, None)

    def propose_file_change(
        self,
        session_id: str,
        request: FileChangeRequest,
        *,
        task_id: str | None = None,
    ) -> ApprovalGate:
        session = self.require_session(session_id)
        root = Path(session["workspace"])
        try:
            target = resolve_workspace_path(root, request.path, allow_missing=True)
            if target.exists() and target.stat().st_size > MAX_FILE_BYTES:
                raise WorkspaceError(f"Files larger than {MAX_FILE_BYTES} bytes cannot be modified.")
            current_hash = _file_sha256(target) if target.exists() else None
            if request.expected_sha256 is not None and current_hash != request.expected_sha256:
                raise HTTPException(status_code=409, detail="File changed since it was opened.")
            if len(request.content.encode("utf-8")) > MAX_FILE_BYTES:
                raise HTTPException(status_code=413, detail=f"Files larger than {MAX_FILE_BYTES} bytes cannot be saved.")
        except WorkspaceError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        gate = self.create_approval(
            session_id,
            "file_write",
            {"path": request.path, "new_file": current_hash is None},
            task_id=task_id,
        )
        gate.expected_sha256 = current_hash
        gate.pending_content = request.content
        self.emit(
            session_id,
            "file_change_proposed",
            {"path": request.path, "approval_id": gate.id},
            task_id,
        )
        return gate

    def propose_file_delete(self, session_id: str, request: FileDeleteRequest) -> ApprovalGate:
        session = self.require_session(session_id)
        try:
            target = resolve_workspace_path(Path(session["workspace"]), request.path)
        except WorkspaceError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        gate = self.create_approval(
            session_id,
            "file_delete",
            {"path": request.path, "explanation": "This permanently removes the selected workspace file."},
        )
        gate.expected_sha256 = _file_sha256(target)
        return gate

    def start_test_run(self, session_id: str) -> str:
        self.require_session(session_id)
        gate = self.create_approval(
            session_id,
            "test_run",
            {"command": "python -m pytest", "explanation": "Run the workspace test suite."},
        )
        self.emit(session_id, "test_run_started", {"id": gate.id, "status": "awaiting_approval"})

        def run() -> None:
            if not self.wait_for_approval(session_id, gate):
                result = {
                    "output": "Test run was not approved or the approval request expired.",
                    "returncode": 126,
                    "status": gate.status,
                }
            else:
                session = self.store.get_session(session_id)
                result = run_workspace_command(["python", "-m", "pytest"], Path(session["workspace"]), timeout=300)
                result["status"] = "passed" if result["returncode"] == 0 else "failed"
            self.emit(session_id, "test_result", {"id": gate.id, **result})

        threading.Thread(target=run, name=f"devpilot-tests-{gate.id[:8]}", daemon=True).start()
        return gate.id


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_app(database_path: Path | None = None, *, enforce_loopback: bool = True) -> FastAPI:
    db_path = database_path or Path(
        os.getenv("DEVPILOT_DB_PATH", Path.home() / ".devpilot" / "sessions.sqlite3")
    )
    allowed_origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        os.getenv("DEVPILOT_FRONTEND_ORIGIN", "http://127.0.0.1:5173"),
    }
    store = EventStore(db_path)
    service = DevPilotService(store)
    application = FastAPI(title="DevPilot API", version="0.1.0")
    application.state.service = service
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type"],
    )

    @application.middleware("http")
    async def local_clients_only(request: Request, call_next):
        if enforce_loopback:
            host = request.client.host if request.client else ""
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
            if not is_loopback:
                return JSONResponse(status_code=403, content={"detail": "DevPilot is restricted to local clients."})
        return await call_next(request)

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        return store.list_sessions()

    @application.post("/api/sessions", status_code=201)
    def create_session(request: SessionCreate) -> dict[str, Any]:
        workspace = Path(request.workspace).expanduser()
        try:
            workspace = workspace.resolve(strict=True)
        except OSError as error:
            raise HTTPException(status_code=400, detail=f"Workspace does not exist: {error}") from error
        if not workspace.is_dir():
            raise HTTPException(status_code=400, detail="Workspace must be a directory.")
        title = request.title or workspace.name or str(workspace)
        session = store.create_session(uuid.uuid4().hex, workspace, title)
        service.emit(session["id"], "session_created", {"workspace": str(workspace), "title": title})
        return session

    @application.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = service.require_session(session_id)
        return {**session, "project": inspect_project(Path(session["workspace"]))}

    @application.get("/api/sessions/{session_id}/files")
    def files(session_id: str) -> dict[str, Any]:
        session = service.require_session(session_id)
        root = Path(session["workspace"])
        return {"files": list_project_files(root), "project": inspect_project(root)}

    @application.get("/api/sessions/{session_id}/file")
    def file_content(session_id: str, path: str) -> dict[str, str]:
        session = service.require_session(session_id)
        try:
            content = read_project_file(Path(session["workspace"]), path)
            target = resolve_workspace_path(Path(session["workspace"]), path)
        except WorkspaceError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"path": path, "content": content, "sha256": _file_sha256(target)}

    @application.put("/api/sessions/{session_id}/file")
    def propose_file_change(session_id: str, request: FileChangeRequest) -> dict[str, Any]:
        gate = service.propose_file_change(session_id, request)
        return {"approval_id": gate.id, "status": gate.status}

    @application.post("/api/sessions/{session_id}/file-delete", status_code=202)
    def propose_file_delete(session_id: str, request: FileDeleteRequest) -> dict[str, Any]:
        gate = service.propose_file_delete(session_id, request)
        return {"approval_id": gate.id, "status": gate.status}

    @application.get("/api/sessions/{session_id}/git/status")
    def session_git_status(session_id: str) -> dict[str, Any]:
        session = service.require_session(session_id)
        return git_status(Path(session["workspace"]))

    @application.get("/api/sessions/{session_id}/git/diff")
    def session_git_diff(session_id: str) -> dict[str, Any]:
        session = service.require_session(session_id)
        return git_diff(Path(session["workspace"]))

    @application.get("/api/sessions/{session_id}/search")
    def search_files(session_id: str, q: str = Query(min_length=1, max_length=200)) -> dict[str, Any]:
        session = service.require_session(session_id)
        try:
            return {"matches": search_project(Path(session["workspace"]), q)}
        except WorkspaceError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @application.post("/api/sessions/{session_id}/tasks", status_code=201)
    def create_task(session_id: str, request: TaskCreate) -> dict[str, Any]:
        service.require_session(session_id)
        task_text = request.task.strip()
        if not task_text:
            raise HTTPException(status_code=422, detail="Task must contain non-whitespace text.")
        task = store.create_task(uuid.uuid4().hex, session_id, task_text, request.model_name)
        service.emit(session_id, "task_queued", {"task": task_text}, task["id"])
        return task

    @application.post("/api/sessions/{session_id}/tasks/{task_id}/start", status_code=202)
    def start_task(session_id: str, task_id: str, request: TaskStart | None = None) -> dict[str, str]:
        task = store.get_task(task_id)
        if task is None or task["session_id"] != session_id:
            raise HTTPException(status_code=404, detail="Task not found.")
        if task["status"] != "queued":
            raise HTTPException(status_code=409, detail=f"Task is {task['status']} and cannot be started.")
        service.start_agent(
            session_id,
            task_id,
            (request.model_name if request else None) or task.get("model_name"),
        )
        return {"task_id": task_id, "status": "starting"}

    @application.post("/api/sessions/{session_id}/tasks/{task_id}/cancel", status_code=202)
    def cancel_task(session_id: str, task_id: str) -> dict[str, str]:
        return service.cancel_agent(session_id, task_id)

    @application.get("/api/sessions/{session_id}/tasks")
    def session_tasks(session_id: str) -> list[dict[str, Any]]:
        service.require_session(session_id)
        return store.list_tasks(session_id)

    @application.get("/api/sessions/{session_id}/events")
    def session_events(session_id: str, after: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
        service.require_session(session_id)
        return store.events_after(session_id, after)

    @application.websocket("/api/sessions/{session_id}/events/ws")
    async def stream_events(websocket: WebSocket, session_id: str) -> None:
        if enforce_loopback:
            host = websocket.client.host if websocket.client else ""
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
            if not is_loopback:
                await websocket.close(code=1008, reason="DevPilot accepts local clients only.")
                return
        if store.get_session(session_id) is None:
            await websocket.close(code=1008, reason="Session not found.")
            return
        origin = websocket.headers.get("origin")
        if origin and origin not in allowed_origins:
            await websocket.close(code=1008, reason="Origin is not allowed.")
            return
        await websocket.accept()
        try:
            after = max(0, int(websocket.query_params.get("after", "0")))
        except ValueError:
            await websocket.close(code=1008, reason="Invalid event cursor.")
            return
        try:
            while True:
                events = await asyncio.to_thread(store.events_after, session_id, after)
                for event in events:
                    await websocket.send_json(event)
                    after = event["id"]
                await asyncio.sleep(0.35)
        except WebSocketDisconnect:
            return

    @application.get("/api/sessions/{session_id}/approvals")
    def approvals(session_id: str) -> list[dict[str, Any]]:
        service.require_session(session_id)
        return service.list_approvals(session_id)

    @application.put("/api/sessions/{session_id}/approvals/{approval_id}")
    def resolve_approval(session_id: str, approval_id: str, request: ApprovalDecision) -> dict[str, Any]:
        return service.approve(session_id, approval_id, request.approved)

    @application.post("/api/sessions/{session_id}/tests", status_code=202)
    def start_test_run(session_id: str) -> dict[str, str]:
        run_id = service.start_test_run(session_id)
        return {"test_run_id": run_id, "status": "awaiting_approval"}

    @application.get("/api/sessions/{session_id}/tests")
    def test_results(session_id: str) -> list[dict[str, Any]]:
        service.require_session(session_id)
        return [event for event in store.events_after(session_id) if event["type"] == "test_result"]

    return application


def _bounded_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer.") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


app = create_app()
