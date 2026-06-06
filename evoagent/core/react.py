"""ReActEngine — the canonical iterative ReAct tool-calling loop.

A single source of truth for the read-decide-act agent loop. The engine:
  - calls the LLM with the running message history + tool schemas,
  - executes any returned tool calls (with permission checks),
  - appends assistant/tool messages so the history stays provider-valid
    (every ``tool_calls`` turn is answered by one tool message per id),
  - tracks token cost per call,
  - stops on a final text answer or a resource limit.

``Agent.run`` uses this engine directly. ``ConversationRuntime`` shares the
:func:`safe_messages` helper so the provider-safety logic lives in one place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from evoagent.core.cost import CostSnapshot
from evoagent.core.message import Message, MessageRole
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMRequest
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.sandbox.schema import PermissionDecision
from evoagent.tools.schema import ToolResult

ApprovalHook = Callable[[str, dict], Awaitable[bool]]
ToolEventHook = Callable[[str, str, dict], Awaitable[Any]]


def classify_tool(name: str, arguments: dict) -> tuple[str, str, str]:
    """Map a tool call to ``(action_type, target, risk_level)``.

    Used so permission rules written for real action types (``shell``,
    ``file_write``, ...) actually apply to tool calls — e.g. a ``bash`` tool
    running ``rm -rf`` is checked against the ``shell`` deny rules.
    """
    n = (name or "").lower()
    args = arguments or {}
    if n in ("bash", "shell", "run_shell", "execute_bash", "run_command"):
        return "shell", str(args.get("command", "")), "medium"
    if n in ("write_file", "edit_file", "multi_edit", "apply_patch", "create_file", "delete_file"):
        return "file_write", str(args.get("path", "") or args.get("file_path", "")), "medium"
    if n in ("read_file", "list_directory", "grep", "glob", "search", "git_status", "git_diff"):
        return "file_read", str(args.get("path", "") or args.get("pattern", "")), "low"
    if n in ("python", "run_python"):
        return "python", str(args.get("code", ""))[:200], "medium"
    if n.startswith("git"):
        return "git", str(args.get("command", "") or name), "medium"
    return "tool", name or "", "medium"


@dataclass
class ReActRunResult:
    """Structured outcome of one engine turn.

    ``success`` is *operational*: the loop reached a final assistant answer
    without an engine-level failure. Semantic task correctness is judged
    elsewhere (the eval harness). A tool that failed but from which the model
    recovered does not make the run unsuccessful.
    """

    final_text: str = ""
    messages: list[Message] = field(default_factory=list)
    stop_reason: str = "final"  # final | max_tool_rounds | max_steps | provider_error | no_provider
    tool_calls: int = 0
    llm_calls: int = 0
    tool_results: list[ToolResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cost: CostSnapshot = field(default_factory=CostSnapshot)

    @property
    def success(self) -> bool:
        return self.stop_reason == "final"


def safe_messages(messages: list[Message], window: int = 50) -> list[Message]:
    """Build a provider-safe message history from a trailing window.

    Guarantees that every assistant message carrying ``tool_calls`` is
    immediately followed by exactly one tool message per ``tool_call_id``,
    and that no orphan tool messages remain. The trailing window may split an
    assistant/tool group, so incomplete groups are dropped to keep the request
    valid (a ``tool_calls`` message must be answered for *every* id). Extra or
    duplicate tool responses for an id are also dropped.
    """
    history = messages[-window:] if window and window > 0 else list(messages)
    # Drop leading orphan tool messages (the window may start mid-group).
    start = 0
    while start < len(history) and history[start].role == MessageRole.TOOL:
        start += 1
    history = history[start:]

    safe: list[Message] = []
    i, n = 0, len(history)
    while i < n:
        m = history[i]
        if m.role == MessageRole.ASSISTANT and m.tool_calls:
            tool_msgs: list[Message] = []
            j = i + 1
            while j < n and history[j].role == MessageRole.TOOL:
                tool_msgs.append(history[j])
                j += 1
            required = {tc.id for tc in m.tool_calls}
            # Keep exactly one tool message per required id, in call order.
            by_id: dict[str, Message] = {}
            for t in tool_msgs:
                if t.tool_call_id in required and t.tool_call_id not in by_id:
                    by_id[t.tool_call_id] = t
            if required and required.issubset(by_id.keys()):
                safe.append(m)
                safe.extend(by_id[tc.id] for tc in m.tool_calls)
            # else: incomplete group — drop the assistant turn and its partial
            # tool messages so the request stays valid.
            i = j
            continue
        if m.role == MessageRole.TOOL:
            # Orphan tool message without a preceding tool_calls turn.
            i += 1
            continue
        safe.append(m)
        i += 1
    return safe


class ReActEngine:
    """Iterative ReAct loop shared by batch and (eventually) interactive runs."""

    def __init__(
        self,
        model_router: ModelRouter,
        tool_registry: Any,
        permission_policy: PermissionPolicy | None = None,
        *,
        role: str = "executor",
        max_tool_rounds: int = 50,
        max_steps: int = 100,
        cost: CostSnapshot | None = None,
        approval_hook: ApprovalHook | None = None,
        tool_event_hook: ToolEventHook | None = None,
        ask_fallback: str = "deny",
        history_window: int = 50,
    ):
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.permission_policy = permission_policy or PermissionPolicy()
        self.role = role
        self.max_tool_rounds = max_tool_rounds
        self.max_steps = max_steps
        self.cost = cost or CostSnapshot()
        self.approval_hook = approval_hook
        self.tool_event_hook = tool_event_hook
        # What to do for an ASK decision when no approval_hook is given:
        # "deny" (safe library default) or "allow" (non-interactive Agent.run).
        self.ask_fallback = ask_fallback
        self.history_window = history_window

    async def run_turn(
        self,
        messages: list[Message],
        tools_schema: list[dict] | None = None,
        system_prompt: str | None = None,
    ) -> ReActRunResult:
        """Run the loop until a final answer or a resource limit.

        ``messages`` is mutated in place (assistant/tool messages appended) so
        callers backed by a session keep a faithful history.
        """
        result = ReActRunResult(messages=messages, cost=self.cost)
        if tools_schema is None:
            tools_schema = self.tool_registry.get_tool_schemas()

        provider = self._get_provider(self.role)
        if provider is None:
            result.stop_reason = "no_provider"
            result.errors.append("No model provider configured.")
            return result

        tool_rounds, step = 0, 0
        while tool_rounds < self.max_tool_rounds and step < self.max_steps:
            step += 1
            request_msgs: list[Message] = []
            if system_prompt:
                request_msgs.append(Message(role=MessageRole.SYSTEM, content=system_prompt))
            request_msgs.extend(safe_messages(messages, self.history_window))

            try:
                response = await provider.chat(
                    LLMRequest(messages=request_msgs, tools=tools_schema)
                )
            except Exception as e:  # provider/network failure
                result.stop_reason = "provider_error"
                result.errors.append(f"Provider error: {e}")
                if messages and messages[-1].content and not result.final_text:
                    result.final_text = messages[-1].content
                return result

            result.llm_calls += 1
            self._track_cost(response)

            assistant_msg = Message(
                role=MessageRole.ASSISTANT,
                content=response.content or "",
                tool_calls=response.tool_calls,
                reasoning_content=response.reasoning_content,
            )
            messages.append(assistant_msg)

            if response.tool_calls:
                tool_rounds += 1
                # Atomic group: append exactly one tool message per call,
                # in the original tool_calls order, regardless of outcome.
                for tc in response.tool_calls:
                    result.tool_calls += 1
                    tool_msg = await self._run_one_tool(tc, result)
                    messages.append(tool_msg)
                continue

            result.final_text = response.content or ""
            result.stop_reason = "final"
            return result

        result.stop_reason = (
            "max_tool_rounds" if tool_rounds >= self.max_tool_rounds else "max_steps"
        )
        result.errors.append(f"Stopped without final answer: {result.stop_reason}.")
        if messages and messages[-1].content:
            result.final_text = messages[-1].content
        return result

    async def _run_one_tool(self, tc, result: ReActRunResult) -> Message:
        """Execute one tool call and return its tool message.

        Always returns a tool message for ``tc.id`` (even on denial or error)
        so the assistant/tool group stays complete.
        """
        action_type, target, risk = classify_tool(tc.name, tc.arguments)
        decision = self.permission_policy.check(action_type, target, risk_level=risk)

        if decision == PermissionDecision.DENY:
            tr = ToolResult(call_id=tc.id, name=tc.name, success=False,
                            error=f"Permission denied for '{tc.name}'.")
            result.tool_results.append(tr)
            result.errors.append(f"{tc.name}: permission denied")
            return Message(role=MessageRole.TOOL, tool_call_id=tc.id, name=tc.name,
                           content=f"Permission denied for '{tc.name}'.")

        if decision == PermissionDecision.ASK:
            approved = False
            if self.approval_hook is not None:
                try:
                    approved = bool(await self.approval_hook(tc.name, tc.arguments))
                except Exception:
                    approved = False
            elif self.ask_fallback == "allow":
                approved = True
            if not approved:
                tr = ToolResult(call_id=tc.id, name=tc.name, success=False,
                                error=f"Approval required for '{tc.name}'; not approved.")
                result.tool_results.append(tr)
                return Message(
                    role=MessageRole.TOOL, tool_call_id=tc.id, name=tc.name,
                    content=f"Approval required for '{tc.name}'. The action was not approved.",
                )

        await self._emit("tool_call_started", tc.name, {"arguments": tc.arguments})
        try:
            tr = await self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
            ok = bool(getattr(tr, "success", False))
            out = getattr(tr, "output", "") or getattr(tr, "error", "") or ""
            if not isinstance(tr, ToolResult):
                tr = ToolResult(call_id=tc.id, name=tc.name, success=ok,
                                output=str(getattr(tr, "output", "") or ""),
                                error=getattr(tr, "error", None))
            if not ok and getattr(tr, "error", None):
                result.errors.append(f"{tc.name}: {tr.error}")
        except Exception as e:
            ok, out = False, f"Tool execution error: {e}"
            tr = ToolResult(call_id=tc.id, name=tc.name, success=False, error=str(e))
            result.errors.append(f"{tc.name}: {e}")

        result.tool_results.append(tr)
        await self._emit(
            "tool_call_finished" if ok else "tool_call_failed",
            tc.name, {"output": str(out)[:200]},
        )
        return Message(role=MessageRole.TOOL, tool_call_id=tc.id, name=tc.name, content=str(out))

    def _track_cost(self, response) -> None:
        usage = getattr(response, "usage", None) or {}
        if isinstance(usage, dict):
            pt = usage.get("prompt_tokens", 0) or 0
            ct = usage.get("completion_tokens", 0) or 0
        else:
            pt = getattr(usage, "prompt_tokens", 0) or 0
            ct = getattr(usage, "completion_tokens", 0) or 0
        model = getattr(response, "model", "") or ""
        self.cost.add_call(model, pt, ct)

    async def _emit(self, event_type: str, tool_name: str, payload: dict) -> None:
        if self.tool_event_hook is None:
            return
        try:
            await self.tool_event_hook(event_type, tool_name, payload)
        except Exception:
            pass

    def _get_provider(self, role: str):
        try:
            return self.model_router._get_provider(role)
        except Exception:
            try:
                return self.model_router._get_provider("default")
            except Exception:
                return None
