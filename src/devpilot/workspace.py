"""Workspace-scoped project inspection and command execution."""

import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path, PurePath
from typing import Any

MAX_FILE_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 64_000
MAX_FILES = 2_000
IGNORED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
}
ALLOWED_COMMANDS = {
    "cat",
    "echo",
    "grep",
    "git",
    "ls",
    "npm",
    "python",
    "python3",
    "pytest",
    "pwd",
    "rg",
    "uv",
}


class WorkspaceError(ValueError):
    """A workspace path or operation is invalid."""


class CommandValidationError(ValueError):
    """A terminal command is outside the supported command policy."""


def resolve_workspace_path(root: Path, relative_path: str, *, allow_missing: bool = False) -> Path:
    """Resolve a relative path and reject traversal, absolute paths and escaping symlinks."""
    root = root.resolve(strict=True)
    if not relative_path or "\0" in relative_path:
        raise WorkspaceError("A non-empty relative path is required.")
    candidate_path = Path(relative_path)
    if (
        candidate_path.is_absolute()
        or candidate_path.drive
        or any(part == ".." for part in PurePath(relative_path).parts)
    ):
        raise WorkspaceError("Absolute paths and parent-directory traversal are not allowed.")
    candidate = (root / candidate_path).resolve(strict=not allow_missing)
    if not candidate.is_relative_to(root):
        raise WorkspaceError("The requested path is outside the selected workspace.")
    if not allow_missing and not candidate.is_file():
        raise WorkspaceError("The requested path is not a file.")
    return candidate


def list_project_files(root: Path) -> list[str]:
    """List a bounded set of workspace-relative files, excluding generated directories."""
    files: list[str] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [
            directory
            for directory in directories
            if directory not in IGNORED_DIRECTORIES and not (Path(current) / directory).is_symlink()
        ]
        for filename in filenames:
            path = Path(current) / filename
            if path.is_symlink():
                continue
            files.append(path.relative_to(root).as_posix())
            if len(files) >= MAX_FILES:
                return sorted(files)
    return sorted(files)


def read_project_file(root: Path, relative_path: str) -> str:
    path = resolve_workspace_path(root, relative_path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise WorkspaceError(f"Files larger than {MAX_FILE_BYTES} bytes cannot be opened.")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceError("The requested file is not UTF-8 text.") from error


def write_project_file(root: Path, relative_path: str, content: str) -> None:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise WorkspaceError(f"Files larger than {MAX_FILE_BYTES} bytes cannot be saved.")
    path = resolve_workspace_path(root, relative_path, allow_missing=True)
    if path.exists() and not path.is_file():
        raise WorkspaceError("Only regular files can be modified.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Re-check after directory creation so an existing symlink cannot redirect a write.
    path = resolve_workspace_path(root, relative_path, allow_missing=True)
    path.write_text(content, encoding="utf-8", newline="")


def validate_command(command: str, root: Path | None = None) -> tuple[list[str], str]:
    """Parse a single approved command without shell operators or arbitrary executables."""
    if not command or len(command) > 4_096 or "\0" in command or "\n" in command or "\r" in command:
        raise CommandValidationError("Commands must be a single line of at most 4096 characters.")
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError as error:
        raise CommandValidationError(f"Could not parse command: {error}") from error
    if not arguments:
        raise CommandValidationError("An executable command is required.")
    if "/" in arguments[0] or "\\" in arguments[0] or Path(arguments[0]).drive:
        raise CommandValidationError("Commands must use an allowed executable name, not an executable path.")
    executable = Path(arguments[0]).stem.lower()
    if executable not in ALLOWED_COMMANDS:
        raise CommandValidationError(f"'{executable}' is not an allowed workspace command.")
    if any(re.search(r"(^|[/\\=])\.\.([/\\]|$)", argument) for argument in arguments[1:]):
        raise CommandValidationError("Parent-directory traversal is not allowed in command arguments.")
    if any(Path(argument).is_absolute() for argument in arguments[1:]):
        raise CommandValidationError("Absolute paths are not allowed in command arguments.")
    if executable in {"python", "python3"}:
        if len(arguments) == 1:
            raise CommandValidationError("Python must be given a workspace script or an approved module.")
        if "-m" in arguments:
            if arguments[arguments.index("-m") + 1 :][:1] not in (["pytest"], ["unittest"], ["pip"]):
                raise CommandValidationError("Python may run pytest, unittest, and pip modules only.")
        elif "-c" not in arguments:
            if arguments[1].startswith("-"):
                raise CommandValidationError("Python scripts must be workspace-relative paths.")
            if root is not None:
                try:
                    resolve_workspace_path(root, arguments[1])
                except WorkspaceError as error:
                    raise CommandValidationError(str(error)) from error
    if executable == "git" and len(arguments) > 1 and arguments[1] not in {
        "status",
        "diff",
        "log",
        "show",
        "branch",
        "rev-parse",
        "ls-files",
    }:
        raise CommandValidationError("Only read-only Git commands are supported.")
    if executable == "npm" and len(arguments) > 1 and arguments[1] not in {"test", "run", "install", "ci"}:
        raise CommandValidationError("Only npm test, run, install, and ci commands are supported.")
    if executable == "uv" and len(arguments) > 1 and arguments[1] not in {"run", "sync", "pip"}:
        raise CommandValidationError("Only uv run, sync, and pip commands are supported.")
    if executable == "git" and any(
        argument.startswith(("--git-dir", "--work-tree", "--output")) or argument == "-C"
        for argument in arguments[1:]
    ):
        raise CommandValidationError("Git path and output overrides are not supported.")
    if executable == "npm" and arguments[1:2] == ["run"]:
        approval_kind = "code_execution"
    else:
        approval_kind = (
            "dependency_install"
            if _is_dependency_install(executable, arguments)
            else "code_execution"
            if executable in {"python", "python3", "pytest"}
            else "command"
        )
    return arguments, approval_kind


def _is_dependency_install(executable: str, arguments: list[str]) -> bool:
    if executable == "npm":
        return len(arguments) > 1 and arguments[1] in {"install", "ci"}
    if executable == "uv":
        return len(arguments) > 1 and arguments[1] in {"sync", "pip"}
    return executable in {"python", "python3"} and arguments[1:3] == ["-m", "pip"]


def run_workspace_command(
    arguments: list[str], root: Path, timeout: int, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Execute a validated argv in the workspace with a timeout and bounded captured output."""
    if arguments[0] == "echo":
        return {
            "output": " ".join(arguments[1:]) + "\n",
            "returncode": 0,
            "exception_info": "",
            "truncated": False,
        }
    if arguments[0] == "pwd":
        return {"output": f"{root}\n", "returncode": 0, "exception_info": "", "truncated": False}
    if arguments[0] == "ls":
        entries = sorted(path.name for path in root.iterdir())[:MAX_FILES]
        output = "\n".join(entries) + ("\n" if entries else "")
        truncated = len(output.encode("utf-8")) > MAX_OUTPUT_BYTES
        if truncated:
            output = output[:MAX_OUTPUT_BYTES // 2] + "\n... output truncated ...\n" + output[-MAX_OUTPUT_BYTES // 2 :]
        return {"output": output, "returncode": 0, "exception_info": "", "truncated": truncated}
    if arguments[0] in {"grep", "rg"}:
        query = next((argument for argument in arguments[1:] if not argument.startswith("-")), "")
        if not query:
            return {"output": "A literal search term is required.", "returncode": 2, "exception_info": "", "truncated": False}
        matches = search_project(root, query)
        output = "".join(f"{item['path']}:{item['line']}:{item['text']}\n" for item in matches)
        truncated = len(output.encode("utf-8")) > MAX_OUTPUT_BYTES
        if truncated:
            output = output[: MAX_OUTPUT_BYTES // 2] + "\n... output truncated ...\n" + output[-MAX_OUTPUT_BYTES // 2 :]
        return {"output": output, "returncode": 0, "exception_info": "", "truncated": truncated}
    if arguments[0] == "cat":
        if len(arguments) == 1:
            return {"output": "cat requires at least one workspace file.", "returncode": 2, "exception_info": "", "truncated": False}
        try:
            output = "".join(read_project_file(root, name) for name in arguments[1:])
        except (WorkspaceError, OSError) as error:
            return {"output": str(error), "returncode": 1, "exception_info": str(error), "truncated": False}
        truncated = len(output.encode("utf-8")) > MAX_OUTPUT_BYTES
        if truncated:
            output = output[: MAX_OUTPUT_BYTES // 2] + "\n... output truncated ...\n" + output[-MAX_OUTPUT_BYTES // 2 :]
        return {
            "output": output,
            "returncode": 0,
            "exception_info": "",
            "truncated": truncated,
        }
    if arguments[0] in {"python", "python3"}:
        arguments = [sys.executable, *arguments[1:]]
    elif arguments[0] == "pytest":
        arguments = [sys.executable, "-m", "pytest", *arguments[1:]]
    with tempfile.TemporaryFile() as output_file:
        try:
            result = subprocess.run(
                arguments,
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                env=env or _command_environment(),
                timeout=timeout,
                check=False,
                shell=False,
            )
            returncode = result.returncode
            exception_info = ""
        except subprocess.TimeoutExpired:
            returncode = 124
            exception_info = f"Command timed out after {timeout} seconds."
        except OSError as error:
            returncode = 127
            exception_info = f"Could not start command: {error}"
        output_file.seek(0, os.SEEK_END)
        size = output_file.tell()
        if size <= MAX_OUTPUT_BYTES:
            output_file.seek(0)
            output = output_file.read().decode("utf-8", errors="replace")
        else:
            half = MAX_OUTPUT_BYTES // 2
            output_file.seek(0)
            head = output_file.read(half).decode("utf-8", errors="replace")
            output_file.seek(-half, os.SEEK_END)
            tail = output_file.read(half).decode("utf-8", errors="replace")
            output = f"{head}\n... {size - MAX_OUTPUT_BYTES} bytes omitted ...\n{tail}"
        return {
            "output": output,
            "returncode": returncode,
            "exception_info": exception_info,
            "truncated": size > MAX_OUTPUT_BYTES,
        }


def _command_environment() -> dict[str, str]:
    secret_name = re.compile(
        r"(?:API[_-]?KEY|ACCESS[_-]?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL|AUTHORIZATION|PRIVATE[_-]?KEY)",
        re.IGNORECASE,
    )
    return {key: value for key, value in os.environ.items() if not secret_name.search(key)}


def inspect_project(root: Path) -> dict[str, Any]:
    """Build bounded, manifest-based language/framework/dependency context for the agent."""
    files = list_project_files(root)
    extensions = Counter(Path(name).suffix.lower() for name in files if Path(name).suffix)
    languages = {
        ".py": "Python",
        ".pyi": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".java": "Java",
        ".kt": "Kotlin",
        ".go": "Go",
        ".rs": "Rust",
        ".cs": "C#",
        ".php": "PHP",
        ".rb": "Ruby",
    }
    detected_languages = Counter()
    for extension, count in extensions.items():
        if extension in languages:
            detected_languages[languages[extension]] += count
    frameworks: list[str] = []
    dependencies: set[str] = set()
    manifests = {
        "pyproject.toml": ("FastAPI", "Django", "Flask", "pytest"),
        "package.json": ("react", "vite", "next", "express", "tailwindcss"),
        "requirements.txt": ("fastapi", "django", "flask", "pytest"),
        "pom.xml": ("spring-boot",),
        "build.gradle": ("spring-boot",),
    }
    for manifest, candidates in manifests.items():
        if manifest in files:
            try:
                raw_text = read_project_file(root, manifest)
                text = raw_text.lower()
            except WorkspaceError:
                continue
            frameworks.extend(candidate for candidate in candidates if candidate.lower() in text)
            if manifest == "package.json":
                try:
                    package = json.loads(raw_text)
                    for field in ("dependencies", "devDependencies", "peerDependencies"):
                        dependencies.update(package.get(field, {}).keys())
                except (json.JSONDecodeError, AttributeError):
                    pass
            elif manifest == "pyproject.toml":
                dependencies.update(re.findall(r"""["']([A-Za-z][A-Za-z0-9_.-]*)""", raw_text))
            else:
                dependencies.update(
                    re.findall(r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(?:[<>=~!;\[]|$)", raw_text, re.MULTILINE)
                )
    return {
        "file_count": len(files),
        "languages": dict(detected_languages.most_common()),
        "frameworks": sorted(set(frameworks)),
        "manifests": [name for name in manifests if name in files],
        "dependencies": sorted(dependencies)[:100],
        "files": files[:250],
    }


def search_project(root: Path, query: str, *, max_results: int = 200) -> list[dict[str, Any]]:
    if not query or len(query) > 200:
        raise WorkspaceError("Search text must contain between 1 and 200 characters.")
    matches: list[dict[str, Any]] = []
    needle = query.casefold()
    scanned_bytes = 0
    for relative_path in list_project_files(root):
        try:
            scanned_bytes += resolve_workspace_path(root, relative_path).stat().st_size
            if scanned_bytes > 20_000_000:
                break
            text = read_project_file(root, relative_path)
        except (WorkspaceError, OSError):
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if needle in line.casefold():
                matches.append(
                    {"path": relative_path, "line": line_number, "text": line[:400]}
                )
                if len(matches) >= max_results:
                    return matches
    return matches


def git_status(root: Path) -> dict[str, Any]:
    result = run_workspace_command(["git", "status", "--short", "--branch"], root, timeout=10)
    if result["returncode"]:
        return {
            "is_git_repo": False,
            "error": result["output"].strip() or result["exception_info"],
            "status": "",
            "changed_files": [],
        }
    lines = result["output"].splitlines()
    return {
        "is_git_repo": True,
        "status": result["output"],
        "changed_files": [line[3:] for line in lines[1:] if len(line) > 3],
    }


def git_diff(root: Path) -> dict[str, Any]:
    status = git_status(root)
    if not status["is_git_repo"]:
        return {**status, "diff": ""}
    result = run_workspace_command(
        ["git", "diff", "--no-ext-diff", "--no-color", "HEAD"], root, timeout=10
    )
    diff = result["output"]
    if result["returncode"]:
        return {
            "is_git_repo": True,
            "error": result["exception_info"] or diff.strip() or f"git diff exited with status {result['returncode']}",
            "diff": "",
            "changed_files": status["changed_files"],
        }
    untracked = [line[3:] for line in status["status"].splitlines() if line.startswith("?? ")]
    for relative_path in untracked:
        try:
            content = read_project_file(root, relative_path)
        except (WorkspaceError, OSError):
            continue
        diff += "".join(
            difflib.unified_diff(
                [],
                content.splitlines(keepends=True),
                fromfile="/dev/null",
                tofile=f"b/{relative_path}",
            )
        )
    if len(diff.encode("utf-8")) > MAX_OUTPUT_BYTES:
        diff = diff[: MAX_OUTPUT_BYTES // 2] + "\n... diff truncated ...\n" + diff[-MAX_OUTPUT_BYTES // 2 :]
    return {"is_git_repo": True, "diff": diff, "changed_files": status["changed_files"]}
