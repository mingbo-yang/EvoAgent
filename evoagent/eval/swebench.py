"""SWE-bench-style evaluation harness.

Runs an agent against bug-fixing instances and evaluates the produced patch the
SWE-bench way: the model's unified diff is applied to a clean checkout of the
repository and the instance's FAIL_TO_PASS tests must pass (and PASS_TO_PASS
tests must keep passing).

This module deliberately avoids any hard dependency on Docker or the
``swebench`` package so it can run a local prediction→evaluation loop; instances
reference a prepared git working tree (one per instance).
"""

import json
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

_PROMPT_SUFFIX = (
    "\n\nFix the bug described above by editing the repository files using your "
    "tools. Make the failing tests pass without breaking others. When done, stop."
)


@dataclass
class SWEBenchInstance:
    instance_id: str
    workspace: Path  # a git working tree checked out at the (buggy) base state
    problem_statement: str
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    test_cmd: str = "python -m pytest -q"


@dataclass
class Prediction:
    instance_id: str
    model_name_or_path: str
    model_patch: str


@dataclass
class EvalResult:
    instance_id: str
    resolved: bool = False
    fail_to_pass_ok: bool = False
    pass_to_pass_ok: bool = True
    patch_applied: bool = False
    error: str = ""


def _run(cmd: list[str], cwd: str | Path, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


_DIFF_EXCLUDES = [
    ":(exclude).evoagent",
    ":(exclude).evoagent/**",
    ":(exclude)**/__pycache__/**",
    ":(exclude)**/*.pyc",
    ":(exclude).pytest_cache/**",
    ":(exclude).runs/**",
]


def git_diff(workspace: str | Path) -> str:
    """Return a unified diff of source changes (excluding caches/artifacts).

    New files are included, but agent/test artifacts (``__pycache__``, ``.pyc``,
    ``.evoagent``, ``.pytest_cache``, ``.runs``) are excluded so the patch
    applies cleanly to a fresh checkout (binary ``.pyc`` files in particular
    would otherwise make ``git apply`` fail).
    """
    _run(["git", "add", "-A", "--", ".", *_DIFF_EXCLUDES], workspace)
    proc = _run(["git", "diff", "--cached", "--", ".", *_DIFF_EXCLUDES], workspace)
    return proc.stdout


class SWEBenchHarness:
    """Produces predictions by running an agent on each instance in place."""

    def __init__(
        self,
        agent_factory: Callable[[Path], object],
        model_name: str = "evoagent",
    ):
        # agent_factory(workspace) -> an object with an async run(task) method.
        self.agent_factory = agent_factory
        self.model_name = model_name

    async def run_instance(self, inst: SWEBenchInstance) -> Prediction:
        agent = self.agent_factory(inst.workspace)
        run: Callable[[str], Awaitable] = agent.run
        await run(inst.problem_statement + _PROMPT_SUFFIX)
        patch = git_diff(inst.workspace)
        return Prediction(inst.instance_id, self.model_name, patch)

    async def run(self, instances: list[SWEBenchInstance]) -> list[Prediction]:
        preds = []
        for inst in instances:
            preds.append(await self.run_instance(inst))
        return preds

    @staticmethod
    def save_predictions(preds: list[Prediction], path: str | Path) -> None:
        lines = [
            json.dumps({
                "instance_id": p.instance_id,
                "model_name_or_path": p.model_name_or_path,
                "model_patch": p.model_patch,
            }, ensure_ascii=False)
            for p in preds
        ]
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


class SWEBenchEvaluator:
    """Evaluates a prediction by applying its patch to a clean checkout."""

    def evaluate(self, inst: SWEBenchInstance, prediction: Prediction) -> EvalResult:
        result = EvalResult(instance_id=inst.instance_id)
        tmp = Path(tempfile.mkdtemp(prefix="swebench_eval_"))
        clone = tmp / "repo"
        try:
            # A fresh clone reflects the committed (base) state, excluding any
            # working-tree edits, so the patch alone must fix the bug.
            cp = _run(["git", "clone", "--quiet", str(inst.workspace), str(clone)], tmp)
            if cp.returncode != 0:
                result.error = f"clone failed: {cp.stderr[:300]}"
                return result

            if prediction.model_patch.strip():
                patch_file = tmp / "model.patch"
                patch_file.write_text(prediction.model_patch, encoding="utf-8")
                ap = _run(["git", "apply", "--whitespace=nowarn", str(patch_file)], clone)
                if ap.returncode != 0:
                    result.error = f"patch did not apply: {ap.stderr[:300]}"
                    return result
            result.patch_applied = True

            base_cmd = inst.test_cmd.split()
            if inst.fail_to_pass:
                f2p = _run(base_cmd + inst.fail_to_pass, clone)
                result.fail_to_pass_ok = f2p.returncode == 0
                if not result.fail_to_pass_ok:
                    result.error = (f2p.stdout + f2p.stderr)[-400:]
            else:
                result.fail_to_pass_ok = True

            if inst.pass_to_pass:
                p2p = _run(base_cmd + inst.pass_to_pass, clone)
                result.pass_to_pass_ok = p2p.returncode == 0

            result.resolved = result.fail_to_pass_ok and result.pass_to_pass_ok
            return result
        except subprocess.TimeoutExpired:
            result.error = "evaluation timed out"
            return result
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def load_instances(jsonl_path: str | Path) -> list[SWEBenchInstance]:
    """Load instances from a JSONL file.

    Each line must provide: instance_id, workspace, problem_statement,
    fail_to_pass (list), and optionally pass_to_pass and test_cmd.
    """
    instances: list[SWEBenchInstance] = []
    for line in Path(jsonl_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        instances.append(SWEBenchInstance(
            instance_id=d["instance_id"],
            workspace=Path(d["workspace"]),
            problem_statement=d["problem_statement"],
            fail_to_pass=d.get("fail_to_pass", []),
            pass_to_pass=d.get("pass_to_pass", []),
            test_cmd=d.get("test_cmd", "python -m pytest -q"),
        ))
    return instances


def resolved_rate(results: list[EvalResult]) -> float:
    """Fraction of instances marked resolved."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.resolved) / len(results)
