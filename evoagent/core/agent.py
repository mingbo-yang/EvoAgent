"""Top-level Agent class — assembles all modules into a runnable agent."""

from pathlib import Path
from typing import Any

from evoagent.conversation.context import (
    DEFAULT_KEEP_RECENT_TOKENS,
    DEFAULT_TOKEN_BUDGET,
)
from evoagent.core.result import AgentResult
from evoagent.logging.trace import TraceRecorder
from evoagent.models.factory import MockLLMProvider
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMRequest
from evoagent.planning.critic import Critic
from evoagent.planning.executor import Executor
from evoagent.planning.loop import AgentLoop
from evoagent.planning.planner import Planner
from evoagent.planning.reflector import Reflector
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.tools.builtin import create_builtin_registry
from evoagent.tools.registry import ToolRegistry


class Agent:
    """EvoAgent — a complete agent that can run tasks and chat.

    Usage:
        agent = Agent(model_router=router, tool_registry=registry)
        result = await agent.run("List the files in the current directory")
    """

    def __init__(
        self,
        model_router: ModelRouter | None = None,
        tool_registry: ToolRegistry | None = None,
        trace_recorder: TraceRecorder | None = None,
        workspace: str | Path = ".",
        permission_policy: PermissionPolicy | None = None,
        config: Any = None,
        memory_store: Any = None,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        keep_recent_tokens: int = DEFAULT_KEEP_RECENT_TOKENS,
        steering: Any = None,
        checkpoint_dir: str | Path | None = None,
        tracer: Any = None,
    ):
        self.workspace = Path(workspace)
        self.tool_registry = tool_registry or create_builtin_registry(self.workspace)
        self.trace_recorder = trace_recorder

        # Model router: use the provided one or a mock
        self.model_router = model_router or ModelRouter(
            providers={"default": MockLLMProvider(fixed_text="OK")}
        )

        # Shared cost snapshot across planner/executor/loop
        from evoagent.core.cost import CostSnapshot
        self.cost = CostSnapshot()

        # Planning components
        planner_llm = self._get_provider("planner")
        self.planner = Planner(planner_llm, event_logger=trace_recorder, cost=self.cost)

        executor_llm = self._get_provider("executor")
        self.executor = Executor(self.tool_registry, llm=executor_llm, event_logger=trace_recorder, cost=self.cost)

        critic_llm = self._get_provider("critic")
        self.critic = Critic(llm=critic_llm, mode="rule", event_logger=trace_recorder)

        reflector_llm = self._get_provider("planner")
        self.reflector = Reflector(llm=reflector_llm, event_logger=trace_recorder)

        self._loop = AgentLoop(
            tool_registry=self.tool_registry,
            planner=self.planner,
            executor=self.executor,
            critic=self.critic,
            reflector=self.reflector,
            trace_recorder=trace_recorder,
            cost=self.cost,
        )

        self.permission_policy = permission_policy
        self.memory_store = memory_store
        self._config = config
        self._memory_context: str = ""
        self._token_budget = token_budget
        self._keep_recent_tokens = keep_recent_tokens
        self.steering = steering
        # Directory for crash-recovery checkpoints (one subdir per run_id).
        # None disables checkpointing.
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        # Optional observability tracer (evoagent.observability.Tracer).
        self.tracer = tracer

    def _get_provider(self, role: str):
        """Get a provider for a role, falling back to default."""
        try:
            return self.model_router._get_provider(role)
        except Exception:
            return self.model_router._get_provider("default") if self.model_router._providers else None

    # ── Core API ──────────────────────────────────────────────────────

    async def run(self, task: str) -> AgentResult:
        """Run a task on the iterative ReAct loop, with memory.

        The agent reads the task, calls the LLM with the available tools, runs
        any tool calls it requests, feeds the results back, and repeats until
        the model produces a final answer (read-decide-act). This replaces the
        older static plan-ahead path so the agent can inspect results before
        deciding its next action.

        Args:
            task: Natural language task description.

        Returns:
            AgentResult with success, final_answer, state, and cost.
        """
        from evoagent.core.cost import CostSnapshot
        from evoagent.core.ids import generate_id
        from evoagent.core.message import Message, MessageRole
        from evoagent.core.react import ReActEngine

        # Pre-run: retrieve relevant memories
        self._memory_context = ""
        if self.memory_store:
            try:
                from evoagent.memory.retriever import MemoryRetriever
                retriever = MemoryRetriever(self.memory_store)
                memories = retriever.retrieve(task)
                self._memory_context = retriever.format_for_prompt(memories)
            except Exception:
                pass

        run_id = generate_id("run")
        if self.trace_recorder:
            try:
                run_id = self.trace_recorder.start_run(task)
            except Exception:
                pass

        # Fresh per-run cost so AgentResult totals are not cumulative.
        run_cost = CostSnapshot()
        checkpointer = None
        if self._checkpoint_dir is not None:
            from evoagent.core.checkpoint import CheckpointStore
            checkpointer = CheckpointStore(self._checkpoint_dir).checkpointer(run_id, task)
        engine = ReActEngine(
            model_router=self.model_router,
            tool_registry=self.tool_registry,
            permission_policy=self.permission_policy or PermissionPolicy(),
            role="executor",
            cost=run_cost,
            # Non-interactive: auto-approve ASK actions (deny rules still apply),
            # matching the legacy plan-ahead loop which ran tools unconditionally.
            ask_fallback="allow",
            token_budget=self._token_budget,
            keep_recent_tokens=self._keep_recent_tokens,
            steering=self.steering,
            checkpointer=checkpointer,
            tracer=self.tracer,
        )

        user_content = task
        if self._memory_context:
            user_content = f"{task}\n\n{self._memory_context}"
        messages = [Message(role=MessageRole.USER, content=user_content)]
        system_prompt = self._build_system_prompt()
        if self.tracer is not None:
            with self.tracer.span("agent.run", task=task[:120]):
                run_result = await engine.run_turn(messages, system_prompt=system_prompt)
        else:
            run_result = await engine.run_turn(messages, system_prompt=system_prompt)

        agent_result = self._build_agent_result(
            run_id, task, messages, run_result, run_cost
        )

        if self.trace_recorder:
            try:
                self.trace_recorder.save_final_result(agent_result)
            except Exception:
                pass

        # Post-run: write memory
        if self.memory_store and agent_result.state:
            try:
                from evoagent.memory.writer import MemoryWriter
                writer = MemoryWriter(self.memory_store)
                writer.write_from_run(agent_result.state, agent_result.success)
            except Exception:
                pass

        return agent_result

    def _build_agent_result(self, run_id, task, messages, run_result, run_cost):
        """Assemble a RuntimeState snapshot and AgentResult from a run."""
        from evoagent.core.state import RunStatus, RuntimeState

        state = RuntimeState(run_id=run_id, task=task)
        state.messages = messages
        state.tool_results = list(run_result.tool_results)
        state.errors = list(run_result.errors)
        state.status = RunStatus.SUCCEEDED if run_result.success else RunStatus.FAILED
        return AgentResult(
            run_id=run_id,
            task=task,
            success=run_result.success,
            final_answer=run_result.final_text,
            state=state,
            steps_taken=run_result.llm_calls,
            tool_calls=run_result.tool_calls,
            total_tokens=run_cost.total_tokens,
            total_cost=run_cost.cost_usd,
            error="; ".join(run_result.errors) if not run_result.success else None,
            metadata={"cost": run_cost.summary(), "stop_reason": run_result.stop_reason},
        )

    async def resume(self, run_id: str, follow_up: str | None = None) -> AgentResult:
        """Resume a previously checkpointed run and continue to completion.

        Loads the last consistent message history saved by the checkpointer,
        optionally appends a follow-up user message, then continues the ReAct
        loop. Requires the agent to have been constructed with
        ``checkpoint_dir``.

        Args:
            run_id: The run_id whose checkpoint should be resumed.
            follow_up: Optional extra user instruction to inject before
                continuing.

        Returns:
            AgentResult for the continued run.

        Raises:
            ValueError: If checkpointing is disabled or no checkpoint exists.
        """
        from evoagent.core.checkpoint import CheckpointStore
        from evoagent.core.cost import CostSnapshot
        from evoagent.core.message import Message, MessageRole
        from evoagent.core.react import ReActEngine

        if self._checkpoint_dir is None:
            raise ValueError("resume() requires the agent to be built with checkpoint_dir.")
        store = CheckpointStore(self._checkpoint_dir)
        data = store.load(run_id)
        if not data:
            raise ValueError(f"No checkpoint found for run_id '{run_id}'.")

        task = data.get("task", "")
        messages = [Message.model_validate(m) for m in data.get("messages", [])]
        if follow_up:
            messages.append(Message(role=MessageRole.USER, content=follow_up))
        system_prompt = data.get("system_prompt") or self._build_system_prompt()

        run_cost = CostSnapshot()
        engine = ReActEngine(
            model_router=self.model_router,
            tool_registry=self.tool_registry,
            permission_policy=self.permission_policy or PermissionPolicy(),
            role="executor",
            cost=run_cost,
            ask_fallback="allow",
            token_budget=self._token_budget,
            keep_recent_tokens=self._keep_recent_tokens,
            steering=self.steering,
            checkpointer=store.checkpointer(run_id, task),
            tracer=self.tracer,
        )
        run_result = await engine.run_turn(messages, system_prompt=system_prompt)
        return self._build_agent_result(run_id, task, messages, run_result, run_cost)

    def _build_system_prompt(self) -> str:
        """System prompt for the iterative coding agent."""
        prompt = (
            "You are EvoAgent, an autonomous coding agent operating in a "
            f"workspace at '{self.workspace}'. Complete the user's task by "
            "calling the available tools. Inspect the workspace (read files, "
            "list directories, search) before making changes, then act. After "
            "each tool result, decide the next action. When the task is fully "
            "done, reply with a concise final answer and no further tool calls. "
            "Do not claim success without verifying via tools. For any task with "
            "multiple steps, call write_todos first to plan the subtasks, keep "
            "exactly one in_progress, and update it as you complete each step. "
            "After changing code, run the project's tests with run_tests, read "
            "any failures, fix them, and re-run until they pass."
        )
        store = getattr(self.tool_registry, "todo_store", None)
        if store is not None and store.items:
            prompt += ("\n\nCurrent task list (carried over — continue from here, "
                       "update with write_todos):\n" + store.format())
        return prompt

    async def chat(self, message: str) -> str:
        """Simple chat without tool calling.

        Args:
            message: User message.

        Returns:
            Agent response text.
        """
        provider = self._get_provider("default")
        if not provider:
            return "No model provider configured."
        response = await provider.chat(LLMRequest(
            messages=[{"role": "user", "content": message}]
        ))
        return response.content

    def add_tool(self, tool: Any) -> None:
        """Register a tool."""
        self.tool_registry.register(tool)

    def save_trace(self, path: str | Path) -> None:
        """Save trace to a directory (reserved for future use)."""
        pass
