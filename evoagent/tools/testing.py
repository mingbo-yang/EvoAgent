"""Model-facing test-in-loop tool (P0.5).

Gives the agent a first-class ``run_tests`` action so the ReAct loop can do
edit → test → read-failure → fix → re-test explicitly. Wraps
``evoagent.code.test_runner.CodeTestRunner`` and condenses the (often huge)
test output into a concise, failure-focused summary the model can act on.

To keep the tool safe to run without per-command approval, the command must
invoke a recognised test runner (pytest, unittest, jest, go test, ...). For
anything else the model should use the ``bash`` tool, which is permission
gated.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from evoagent.code.test_runner import CodeTestRunner
from evoagent.core.ids import generate_id
from evoagent.tools.base import BaseTool, RiskLevel
from evoagent.tools.schema import ToolResult

# Recognised test-runner invocations. The command must contain one of these
# (case-insensitive) so run_tests cannot be used as an unrestricted shell.
_ALLOWED_RUNNERS = (
    "pytest", "py.test", "unittest", "tox", "nox", "npm test", "npm run test",
    "yarn test", "pnpm test", "jest", "vitest", "mocha", "go test",
    "cargo test", "make test", "ctest", "rspec", "phpunit", "gotestsum",
)

# Shell metacharacters that would allow chaining extra commands onto the test
# runner (the underlying runner uses shell=True). Rejected so run_tests stays a
# single test invocation rather than an unrestricted shell.
_SHELL_META = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n", "\r", "&")

# Keep the tail of the output (pytest prints failures + summary at the end).
_MAX_OUTPUT_CHARS = 16_000

# pytest summary line, e.g. "= 2 failed, 5 passed, 1 error in 0.30s ="
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)")
# pytest failing-test node ids, e.g. "FAILED tests/test_x.py::test_y - assert ..."
_FAILED_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def _is_test_command(command: str) -> bool:
    low = command.lower()
    return any(runner in low for runner in _ALLOWED_RUNNERS)


def _has_shell_chaining(command: str) -> bool:
    return any(meta in command for meta in _SHELL_META)


def _tail(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    return "... (output truncated, showing tail)\n" + text[-_MAX_OUTPUT_CHARS:]


def _parse_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for num, kind in _COUNT_RE.findall(text):
        key = "error" if kind in ("error", "errors") else kind
        counts[key] = counts.get(key, 0) + int(num)
    return counts


class RunTestsInput(BaseModel):
    command: str = Field(
        default="python -m pytest -q",
        description="Test command to run. Must invoke a known test runner "
        "(pytest, unittest, jest, go test, ...). Append a path/node id to run "
        "directed tests, e.g. 'python -m pytest -q tests/test_foo.py::test_bar'.",
    )
    timeout: int = Field(default=120, description="Timeout in seconds.")


class RunTestsTool(BaseTool):
    name = "run_tests"
    description = (
        "Run the project's tests and get a concise pass/fail summary with the "
        "names of failing tests and the relevant failure output. Use this to "
        "close the edit -> test -> fix loop: run after a change, read the "
        "failures, patch, and re-run until green. Pass a specific file or test "
        "node id in the command to run only the relevant (directed) tests."
    )
    input_schema = RunTestsInput
    risk_level = RiskLevel.MEDIUM

    def __init__(self, workspace: str | Path,
                 default_command: str = "python -m pytest -q"):
        self.runner = CodeTestRunner(workspace, default_command=default_command)

    async def run(self, command: str = "python -m pytest -q",
                  timeout: int = 120) -> ToolResult:
        command = (command or self.runner.default_command).strip()
        if _has_shell_chaining(command):
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False,
                error="run_tests does not allow shell operators (; && | > ...). "
                "Provide a single test-runner command, or use 'bash' for "
                "anything more complex.",
                metadata={"command": command},
            )
        if not _is_test_command(command):
            return ToolResult(
                call_id=generate_id("call"), name=self.name, success=False,
                error="run_tests only runs recognised test runners (pytest, "
                "unittest, jest, go test, ...). Use the 'bash' tool for other "
                "commands.",
                metadata={"command": command},
            )
        result = self.runner.run(command=command, timeout=timeout)
        combined = result.stdout
        if result.stderr:
            combined += ("\n[stderr]\n" + result.stderr) if combined else result.stderr
        combined = combined.strip()

        counts = _parse_counts(combined)
        failing = _FAILED_RE.findall(combined)
        if counts:
            summary = ", ".join(f"{v} {k}" for k, v in counts.items())
        elif result.success:
            summary = "tests passed"
        else:
            summary = f"exit code {result.exit_code}"

        header = (("PASS" if result.success else "FAIL") + f" — {summary} "
                  f"({result.duration_ms} ms)\n$ {command}")
        if failing:
            shown = failing[:25]
            header += "\nFailing: " + ", ".join(shown)
            if len(failing) > len(shown):
                header += f", ... (+{len(failing) - len(shown)} more)"
        output = header + "\n\n" + _tail(combined) if combined else header

        return ToolResult(
            call_id=generate_id("call"), name=self.name,
            success=result.success, output=output,
            error=None if result.success else f"Tests failed: {summary}",
            metadata={
                "command": command,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "counts": counts,
                "failing": failing,
            },
        )
