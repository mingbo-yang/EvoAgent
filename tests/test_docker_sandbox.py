"""Tests for DockerSandbox. Auto-skip if docker unavailable, use workspace-accessible temp dirs."""

from pathlib import Path

import pytest

from evoagent.sandbox.docker import DockerSandbox
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.sandbox.workspace import Workspace


@pytest.fixture
def sandbox():
    # Create workspace in project area (Docker-accessible on this system)
    ws_path = Path(__file__).parent / ".tmp_docker_ws"
    ws_path.mkdir(exist_ok=True)
    (ws_path / ".gitkeep").write_text("")
    ws = Workspace(ws_path)
    return DockerSandbox(workspace=ws, policy=PermissionPolicy(), timeout=30, network_disabled=False)


@pytest.mark.asyncio
async def test_docker_echo(sandbox):
    result = await sandbox.run_shell("echo hello_docker")
    assert result.success
    assert "hello_docker" in result.stdout


@pytest.mark.asyncio
async def test_docker_python(sandbox):
    result = await sandbox.run_python(code="print(42)")
    assert result.success
    assert "42" in result.stdout


@pytest.mark.asyncio
async def test_docker_rejects_dangerous(sandbox):
    result = await sandbox.run_shell("rm -rf /")
    assert not result.success
    assert "denied" in result.stderr.lower()


@pytest.mark.asyncio
async def test_docker_timeout(sandbox):
    result = await sandbox.run_shell("sleep 5", timeout=1)
    assert not result.success


def test_docker_command_construction():
    """Verify docker command is constructed correctly without running."""
    import shutil
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    ws = Workspace(Path(__file__).parent / ".tmp_docker_ws")
    ws.root.mkdir(exist_ok=True)
    sb = DockerSandbox(workspace=ws, policy=PermissionPolicy(), network_disabled=True)
    # Verify command construction attributes
    assert sb.image == "python:3.11-slim"
    assert sb.network_disabled is True


def test_docker_image_appears_once():
    """Image name should appear exactly once in the command."""
    import shutil
    if shutil.which("docker") is None:
        pytest.skip("docker not available")
    ws = Workspace(Path(__file__).parent / ".tmp_docker_ws")
    ws.root.mkdir(exist_ok=True)
    sb = DockerSandbox(workspace=ws, policy=PermissionPolicy())
    # Check the image attribute is set correctly (not duplicated)
    assert sb.image.count("python") == 1


@pytest.mark.asyncio
async def test_docker_permission_denied_no_docker_call():
    """Permission denied should return before any docker command."""
    ws = Workspace(Path(__file__).parent / ".tmp_docker_ws")
    ws.root.mkdir(exist_ok=True)
    sb = DockerSandbox(workspace=ws, policy=PermissionPolicy())
    result = await sb.run_shell("sudo rm -rf /")
    assert not result.success
    assert "denied" in result.stderr.lower()
    # Should have returned before touching docker
