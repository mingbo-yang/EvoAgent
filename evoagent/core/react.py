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

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from evoagent.conversation.context import (
    DEFAULT_KEEP_RECENT_TOKENS,
    DEFAULT_TOKEN_BUDGET,
    compact_messages,
    estimate_tokens,
)
from evoagent.core.cost import CostSnapshot
from evoagent.core.message import Message, MessageRole
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMRequest
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.sandbox.schema import PermissionDecision
from evoagent.tools.schema import ToolResult

ApprovalHook = Callable[[str, dict], Awaitable[bool]]
ToolEventHook = Callable[[str, str, dict], Awaitable[Any]]


class _ToolCancelled(Exception):
    """Raised internally when a tool execution is cancelled via steering."""

# Tools that only read state and have no side effects, so several of them may
# be executed concurrently within a single tool-call round. ``git_status`` is
# deliberately excluded: ``git status`` can refresh and write the git index.
READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {"read_file", "list_directory", "grep", "list_todos", "glob", "outline",
     "code_search", "web_fetch", "web_search"}
)


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
    if n in ("write_file", "edit_file", "multi_edit", "apply_patch", "undo_last",
             "create_file", "delete_file"):
        return "file_write", str(args.get("path", "") or args.get("file_path", "")), "medium"
    if n in ("read_file", "list_directory", "grep", "glob", "outline", "code_search",
             "search", "git_status", "git_diff"):
        return "file_read", str(args.get("path", "") or args.get("pattern", "")
                                or args.get("query", "")), "low"
    if n in ("web_fetch", "web_search", "fetch", "http_get"):
        return "network", str(args.get("url", "") or args.get("query", "")), "high"
    if n in ("python", "run_python"):
        return "python", str(args.get("code", ""))[:200], "medium"
    if n in ("run_tests", "test", "pytest"):
        return "shell", str(args.get("command", "") or "run_tests"), "medium"
    if n in ("write_todos", "list_todos", "update_todo", "create_todo"):
        return "todo", n, "low"
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
    compactions: int = 0
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

    A leading compaction summary (``metadata.compacted``) is pinned as an
    anchor and always kept, so a long kept window can never push the digest of
    the original task out of the request.
    """
    anchor: Message | None = None
    if messages and messages[0].metadata.get("compacted"):
        anchor = messages[0]
        messages = messages[1:]
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
    return [anchor, *safe] if anchor is not None else safe


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
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        keep_recent_tokens: int = DEFAULT_KEEP_RECENT_TOKENS,
        enable_compaction: bool = True,
        tool_timeout: float | None = None,
        steering: Any = None,
        checkpointer: Any = None,
        tracer: Any = None,
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
        self.token_budget = token_budget
        self.keep_recent_tokens = keep_recent_tokens
        self.enable_compaction = enable_compaction
        # Optional wall-clock cap per tool execution (None = no outer cap; tools
        # still enforce their own internal timeouts).
        self.tool_timeout = tool_timeout
        # Optional out-of-band steering/interrupt controller (see
        # evoagent.core.steering.SteeringController). None disables steering.
        self.steering = steering
        # Optional crash-recovery checkpointer (see
        # evoagent.core.checkpoint.RunCheckpointer). None disables checkpointing.
        self.checkpointer = checkpointer
        # Optional observability tracer (evoagent.observability.Tracer). None
        # disables span emission.
        self.tracer = tracer
        # Serializes event emission so concurrent read-only tools cannot
        # interleave/corrupt a shared event sink.
        self._emit_lock = asyncio.Lock()

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

        # Reserve budget for the parts of the request that are not the message
        # history (system prompt + tool schemas) so the combined request stays
        # within the model's context window.
        overhead = estimate_tokens(system_prompt)
        try:
            overhead += estimate_tokens(json.dumps(tools_schema))
        except (TypeError, ValueError):
            pass
        effective_budget = max(2000, self.token_budget - overhead)

        tool_rounds, step = 0, 0
        while tool_rounds < self.max_tool_rounds and step < self.max_steps:
            step += 1
            # Steering checkpoint: inject queued user messages, then honor a
            # graceful stop / cancel before issuing another model call.
            if self.steering is not None:
                for text in self.steering.drain_injections():
                    messages.append(Message(role=MessageRole.USER, content=text))
                    await self._emit("steering_injected", "", {"text": text[:200]})
                if self.steering.stop_requested:
                    result.stop_reason = "interrupted"
                    result.final_text = (
                        self._last_text(messages) or "Execution interrupted by user."
                    )
                    self._save_checkpoint(messages, "interrupted", "interrupted",
                                          system_prompt)
                    return result
            if self.enable_compaction:
                compacted, changed = compact_messages(
                    messages,
                    token_budget=effective_budget,
                    keep_recent_tokens=self.keep_recent_tokens,
                    state_provider=self._context_state,
                )
                if changed:
                    messages[:] = compacted
                    result.compactions += 1
                    await self._emit("context_compacted", "",
                                     {"messages": len(messages)})
            request_msgs: list[Message] = []
            if system_prompt:
                request_msgs.append(Message(role=MessageRole.SYSTEM, content=system_prompt))
            request_msgs.extend(safe_messages(messages, self.history_window))

            try:
                with self._span("llm.chat", model=self.role) as sp:
                    response = await provider.chat(
                        LLMRequest(messages=request_msgs, tools=tools_schema)
                    )
                    if sp is not None:
                        u = getattr(response, "usage", {}) or {}
                        sp.attributes["model"] = getattr(response, "model", "") or ""
                        sp.attributes["prompt_tokens"] = u.get("prompt_tokens", 0)
                        sp.attributes["completion_tokens"] = u.get("completion_tokens", 0)
                        sp.attributes["cached_tokens"] = u.get("prompt_cache_hit_tokens", 0)
            except Exception as e:  # provider/network failure
                result.stop_reason = "provider_error"
                result.errors.append(f"Provider error: {e}")
                if messages and messages[-1].content and not result.final_text:
                    result.final_text = messages[-1].content
                self._save_checkpoint(messages, "error", "provider_error", system_prompt)
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
                # Consecutive read-only calls may run concurrently.
                result.tool_calls += len(response.tool_calls)
                tool_msgs = await self._run_tool_calls(response.tool_calls, result)
                messages.extend(tool_msgs)
                # Checkpoint after a completed tool round so a crash mid-run is
                # recoverable from the last consistent assistant+tool group.
                self._save_checkpoint(messages, "running", "", system_prompt)
                continue

            result.final_text = response.content or ""
            result.stop_reason = "final"
            self._save_checkpoint(messages, "done", "final", system_prompt)
            return result

        result.stop_reason = (
            "max_tool_rounds" if tool_rounds >= self.max_tool_rounds else "max_steps"
        )
        result.errors.append(f"Stopped without final answer: {result.stop_reason}.")
        if messages and messages[-1].content:
            result.final_text = messages[-1].content
        self._save_checkpoint(messages, "incomplete", result.stop_reason, system_prompt)
        return result

    def _save_checkpoint(self, messages, status: str, stop_reason: str,
                         system_prompt: str | None) -> None:
        """Persist resumable state; never let a checkpoint failure break a run."""
        if self.checkpointer is None:
            return
        try:
            self.checkpointer.save(messages, status=status, stop_reason=stop_reason,
                                   system_prompt=system_prompt)
        except Exception:
            pass

    def _is_read_only(self, tc) -> bool:
        """True if a tool call only reads state (safe to run concurrently)."""
        return (tc.name or "").lower() in READ_ONLY_TOOLS

    async def _authorize(self, tc) -> tuple[ToolResult, Message, list[str]] | None:
        """Run permission checks for one tool call.

        Returns a resolved ``(tool_result, tool_message, errors)`` triple when
        the call is denied or its ASK approval is refused; returns ``None`` when
        the call is cleared to execute. Must be awaited **serially** so ASK
        prompts are never issued concurrently.
        """
        action_type, target, risk = classify_tool(tc.name, tc.arguments)

        if (
            self.steering is not None
            and action_type == "file_write"
            and self.steering.is_forbidden(target)
        ):
            note = f"User forbade modifying '{target}'."
            tr = ToolResult(call_id=tc.id, name=tc.name, success=False, error=note)
            msg = Message(role=MessageRole.TOOL, tool_call_id=tc.id, name=tc.name,
                          content=note)
            return tr, msg, [f"{tc.name}: {note}"]

        decision = self.permission_policy.check(action_type, target, risk_level=risk)

        if decision == PermissionDecision.DENY:
            tr = ToolResult(call_id=tc.id, name=tc.name, success=False,
                            error=f"Permission denied for '{tc.name}'.")
            msg = Message(role=MessageRole.TOOL, tool_call_id=tc.id, name=tc.name,
                          content=f"Permission denied for '{tc.name}'.")
            return tr, msg, [f"{tc.name}: permission denied"]

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
                msg = Message(
                    role=MessageRole.TOOL, tool_call_id=tc.id, name=tc.name,
                    content=f"Approval required for '{tc.name}'. The action was not approved.",
                )
                return tr, msg, []
        return None

    async def _execute(self, tc) -> tuple[ToolResult, Message, list[str]]:
        """Execute one *authorized* tool call.

        Side-effect free with respect to engine state — returns its own
        ``(tool_result, tool_message, errors)`` so the caller can commit results
        in deterministic order even when several calls run concurrently.
        """
        errors: list[str] = []
        await self._emit("tool_call_started", tc.name, {"arguments": tc.arguments})
        sp = None
        try:
            with self._span("tool.execute", tool=tc.name) as sp:
                coro = self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
                tr = await self._await_tool(coro)
            ok = bool(getattr(tr, "success", False))
            out = getattr(tr, "output", "") or getattr(tr, "error", "") or ""
            if not isinstance(tr, ToolResult):
                tr = ToolResult(call_id=tc.id, name=tc.name, success=ok,
                                output=str(getattr(tr, "output", "") or ""),
                                error=getattr(tr, "error", None))
            if not ok and getattr(tr, "error", None):
                errors.append(f"{tc.name}: {tr.error}")
            if sp is not None:
                sp.attributes["success"] = ok
        except _ToolCancelled:
            ok, out = False, f"Tool '{tc.name}' was cancelled by user."
            tr = ToolResult(call_id=tc.id, name=tc.name, success=False, error=str(out))
            errors.append(f"{tc.name}: cancelled")
        except TimeoutError:
            ok, out = False, f"Tool '{tc.name}' timed out after {self.tool_timeout}s."
            tr = ToolResult(call_id=tc.id, name=tc.name, success=False, error=str(out))
            errors.append(f"{tc.name}: timeout")
        except Exception as e:
            ok, out = False, f"Tool execution error: {e}"
            tr = ToolResult(call_id=tc.id, name=tc.name, success=False, error=str(e))
            errors.append(f"{tc.name}: {e}")

        await self._emit(
            "tool_call_finished" if ok else "tool_call_failed",
            tc.name, {"output": str(out)[:200]},
        )
        msg = Message(role=MessageRole.TOOL, tool_call_id=tc.id, name=tc.name, content=str(out))
        return tr, msg, errors

    async def _await_tool(self, coro):
        """Await a tool coroutine, honoring tool_timeout and steering cancel.

        Without steering this is a plain ``wait_for`` (or direct await). With a
        steering controller, the execution races the controller's cancel event
        so a long-running tool (e.g. a shell command) can be interrupted.
        """
        if self.steering is None:
            if self.tool_timeout is not None:
                return await asyncio.wait_for(coro, timeout=self.tool_timeout)
            return await coro

        task = asyncio.ensure_future(coro)
        cancel_wait = asyncio.ensure_future(self.steering.cancel_event.wait())
        try:
            done, _ = await asyncio.wait(
                {task, cancel_wait},
                timeout=self.tool_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            cancel_wait.cancel()

        if task in done:
            return task.result()

        # Either cancelled or timed out: stop the in-flight tool.
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        if self.steering.cancelled:
            raise _ToolCancelled()
        raise TimeoutError()

    @staticmethod
    def _last_text(messages) -> str:
        for m in reversed(messages):
            if getattr(m, "content", ""):
                return m.content
        return ""

    async def _run_tool_calls(self, tool_calls, result: ReActRunResult) -> list[Message]:
        """Execute a round of tool calls and return one message per call.

        Authorization (including ASK prompts) is done serially. Authorized
        calls then execute preserving the original order, except that runs of
        *consecutive* read-only calls are dispatched concurrently. Tool results
        and errors are committed to ``result`` in the original call order so the
        assistant/tool atomic group stays deterministic.
        """
        n = len(tool_calls)
        trs: list[ToolResult | None] = [None] * n
        msgs: list[Message | None] = [None] * n
        errs: list[list[str]] = [[] for _ in range(n)]

        # Phase 1 — authorize serially; resolve denials, plan the rest.
        to_exec: list[int] = []
        for idx, tc in enumerate(tool_calls):
            resolved = await self._authorize(tc)
            if resolved is not None:
                trs[idx], msgs[idx], errs[idx] = resolved
            else:
                to_exec.append(idx)

        # Phase 2 — execute, batching consecutive read-only calls concurrently.
        j = 0
        while j < len(to_exec):
            idx = to_exec[j]
            if self._is_read_only(tool_calls[idx]):
                batch = [idx]
                j += 1
                while j < len(to_exec) and self._is_read_only(tool_calls[to_exec[j]]):
                    batch.append(to_exec[j])
                    j += 1
                outcomes = await asyncio.gather(
                    *(self._execute(tool_calls[b]) for b in batch)
                )
                for b, (tr, msg, e) in zip(batch, outcomes, strict=True):
                    trs[b], msgs[b], errs[b] = tr, msg, e
            else:
                tr, msg, e = await self._execute(tool_calls[idx])
                trs[idx], msgs[idx], errs[idx] = tr, msg, e
                j += 1

        # Phase 3 — commit in original order.
        for idx in range(n):
            if trs[idx] is not None:
                result.tool_results.append(trs[idx])
            result.errors.extend(errs[idx])
        return [m for m in msgs if m is not None]

    def _span(self, name: str, **attributes: Any):
        """Return a tracing span context manager, or a no-op when untraced."""
        if self.tracer is None:
            return nullcontext()
        return self.tracer.span(name, **attributes)

    def _track_cost(self, response) -> None:
        usage = getattr(response, "usage", None) or {}
        if isinstance(usage, dict):
            pt = usage.get("prompt_tokens", 0) or 0
            ct = usage.get("completion_tokens", 0) or 0
            cached = usage.get("prompt_cache_hit_tokens", 0) or 0
        else:
            pt = getattr(usage, "prompt_tokens", 0) or 0
            ct = getattr(usage, "completion_tokens", 0) or 0
            cached = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        model = getattr(response, "model", "") or ""
        self.cost.add_call(model, pt, ct, cached_tokens=cached)

    async def _emit(self, event_type: str, tool_name: str, payload: dict) -> None:
        if self.tool_event_hook is None:
            return
        # Serialize emission so concurrent read-only tools cannot interleave
        # writes to a shared event sink.
        async with self._emit_lock:
            try:
                await self.tool_event_hook(event_type, tool_name, payload)
            except Exception:
                pass

    def _context_state(self) -> str | None:
        """Snapshot of durable state to preserve across compaction (todos)."""
        store = getattr(self.tool_registry, "todo_store", None)
        if store is not None and getattr(store, "items", None):
            return "Current task list:\n" + store.format()
        return None

    def _get_provider(self, role: str):
        try:
            return self.model_router._get_provider(role)
        except Exception:
            try:
                return self.model_router._get_provider("default")
            except Exception:
                return None
