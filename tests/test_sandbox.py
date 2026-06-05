"""Tests for Sandbox (LocalSandbox and Workspace)."""

import tempfile
from pathlib import Path

import pytest

from evoagent.sandbox.local import LocalSandbox
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.sandbox.workspace import Workspace


@pytest.fixture
def tmp_workspace():
    with tempfile.TemporaryDirectory() as tmp:
        yield Workspace(tmp)


@pytest.fixture
def sandbox(tmp_workspace):
    policy = PermissionPolicy()
    return LocalSandbox(workspace=tmp_workspace, policy=policy)


# ── Workspace ─────────────────────────────────────────────────────────


def test_workspace_resolve_normal(tmp_workspace):
    (tmp_workspace.root / "file.txt").write_text("data")
    resolved = tmp_workspace.resolve_path("file.txt")
    assert resolved == (tmp_workspace.root / "file.txt").resolve()


def test_workspace_reject_escape(tmp_workspace):
    with pytest.raises(PermissionError, match="outside workspace"):
        tmp_workspace.resolve_path("../etc/passwd")


def test_workspace_reject_absolute_escape(tmp_workspace):
    with pytest.raises(PermissionError, match="outside workspace"):
        tmp_workspace.resolve_path("/etc/passwd")


def test_workspace_is_inside(tmp_workspace):
    assert tmp_workspace.is_inside_workspace("file.txt")
    assert not tmp_workspace.is_inside_workspace("/etc/passwd")


def test_workspace_relative_path(tmp_workspace):
    sub = tmp_workspace.root / "sub"
    sub.mkdir()
    rel = tmp_workspace.relative_path(sub)
    assert rel == Path("sub")


# ── LocalSandbox shell ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_run_echo(sandbox):
    result = await sandbox.run_shell("echo hello_world")
    assert result.success
    assert "hello_world" in result.stdout


@pytest.mark.asyncio
async def test_sandbox_run_rejects_dangerous(sandbox):
    result = await sandbox.run_shell("rm -rf /tmp")
    assert not result.success
    assert "denied" in result.stderr.lower()


@pytest.mark.asyncio
async def test_sandbox_run_timeout(sandbox):
    result = await sandbox.run_shell("sleep 3", timeout=1)
    assert not result.success
    assert "timeout" in result.stderr.lower()


@pytest.mark.asyncio
async def test_sandbox_run_nonzero_exit(sandbox):
    result = await sandbox.run_shell("exit 1")
    assert not result.success
    assert result.exit_code == 1


# ── LocalSandbox python ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_run_python(sandbox):
    result = await sandbox.run_python(code="print(42)")
    assert result.success
    assert "42" in result.stdout


@pytest.mark.asyncio
async def test_sandbox_run_python_script(sandbox):
    (sandbox.workspace.root / "s.py").write_text("print('script_ok')")
    result = await sandbox.run_python(script_path="s.py")
    assert result.success
    assert "script_ok" in result.stdout


# ── LocalSandbox file I/O ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_read_file(sandbox):
    (sandbox.workspace.root / "r.txt").write_text("content")
    content = await sandbox.read_file("r.txt")
    assert content == "content"


@pytest.mark.asyncio
async def test_sandbox_write_file(sandbox):
    await sandbox.write_file("w.txt", "new_content")
    assert (sandbox.workspace.root / "w.txt").read_text() == "new_content"


@pytest.mark.asyncio
async def test_sandbox_write_file_no_overwrite(sandbox):
    (sandbox.workspace.root / "exist.txt").write_text("old")
    with pytest.raises(FileExistsError):
        await sandbox.write_file("exist.txt", "new", overwrite=False)


@pytest.mark.asyncio
async def test_sandbox_read_outside_workspace(sandbox):
    with pytest.raises(PermissionError, match="outside workspace"):
        await sandbox.read_file("../etc/passwd")
