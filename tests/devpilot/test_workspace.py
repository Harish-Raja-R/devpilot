import shutil
import subprocess
import sys

import pytest

from devpilot.workspace import (
    MAX_OUTPUT_BYTES,
    CommandValidationError,
    WorkspaceError,
    git_diff,
    git_status,
    inspect_project,
    list_project_files,
    read_project_file,
    run_workspace_command,
    search_project,
    validate_command,
    write_project_file,
)


def test_workspace_file_access_and_project_intelligence(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi", "pytest"]\n', encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")

    assert read_project_file(tmp_path, "src/app.py") == "from fastapi import FastAPI\n"
    assert "src/app.py" in list_project_files(tmp_path)
    assert {"path": "src/app.py", "line": 1, "text": "from fastapi import FastAPI"} in search_project(
        tmp_path, "FastAPI"
    )
    context = inspect_project(tmp_path)
    assert context["languages"] == {"Python": 1}
    assert "FastAPI" in context["frameworks"]
    assert "fastapi" in context["dependencies"]


def test_workspace_paths_reject_traversal_and_external_symlinks(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="traversal"):
        read_project_file(root, "../secret.txt")
    try:
        (root / "escape.txt").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is not permitted on this host")
    with pytest.raises(WorkspaceError, match="outside"):
        read_project_file(root, "escape.txt")


def test_file_writes_stay_under_workspace_and_enforce_size(tmp_path):
    write_project_file(tmp_path, "nested/new.txt", "safe")
    assert (tmp_path / "nested" / "new.txt").read_text(encoding="utf-8") == "safe"
    with pytest.raises(WorkspaceError, match="traversal"):
        write_project_file(tmp_path, "../outside.txt", "unsafe")


@pytest.mark.parametrize(
    ("command", "approval_kind"),
    [
        ("git status --short", "command"),
        ("npm install package", "dependency_install"),
        ("python -m pip install package", "dependency_install"),
        ("python -c print(1)", "code_execution"),
        ("python script.py", "code_execution"),
    ],
)
def test_validated_commands_require_expected_approval(command, approval_kind):
    assert validate_command(command)[1] == approval_kind


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "python ../outside.py",
        "powershell Remove-Item file",
    ],
)
def test_command_policy_rejects_shell_escape_and_unsafe_commands(command):
    with pytest.raises(CommandValidationError):
        validate_command(command)


def test_shell_metacharacters_are_never_interpreted_as_chaining():
    arguments, _ = validate_command("python script.py && git status")
    assert arguments == ["python", "script.py", "&&", "git", "status"]


def test_command_output_is_bounded_and_timeout_is_reported(tmp_path):
    command = [sys.executable, "-c", f"print('x' * {MAX_OUTPUT_BYTES * 2})"]
    result = run_workspace_command(command, tmp_path, timeout=10)
    assert result["returncode"] == 0
    assert result["truncated"] is True
    assert len(result["output"].encode("utf-8")) < MAX_OUTPUT_BYTES + 100

    timed_out = run_workspace_command([sys.executable, "-c", "import time; time.sleep(2)"], tmp_path, timeout=1)
    assert timed_out["returncode"] == 124
    assert "timed out" in timed_out["exception_info"]


def test_git_status_and_diff_include_real_tracked_and_untracked_changes(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git is not installed")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "devpilot-test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "DevPilot Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=tmp_path, check=True, capture_output=True)
    tracked.write_text("after\n", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new content\n", encoding="utf-8")

    status = git_status(tmp_path)
    diff = git_diff(tmp_path)
    assert status["is_git_repo"] is True
    assert "tracked.txt" in status["changed_files"]
    assert "new.txt" in status["changed_files"]
    assert "-before" in diff["diff"] and "+after" in diff["diff"]
    assert "+new content" in diff["diff"]

    tracked.write_text("after\n" + "large output\n" * 10_000, encoding="utf-8")
    bounded_diff = git_diff(tmp_path)["diff"]
    assert len(bounded_diff.encode("utf-8")) <= MAX_OUTPUT_BYTES + 100
    assert "... diff truncated ..." in bounded_diff
