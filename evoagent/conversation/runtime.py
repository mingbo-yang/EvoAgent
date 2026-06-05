"""ConversationRuntime — execute one user turn within a persistent session.

Uses internal Message/ToolCall format throughout.
Provider wire format is handled ONLY by provider adapters.
Supports streaming, public reasoning, and activity grouping.
"""

from collections.abc import AsyncIterator

from evoagent.conversation.session import ConversationSession
from evoagent.core.message import Message, MessageRole
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMRequest
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.sandbox.schema import PermissionDecision
from evoagent.tools.registry import ToolRegistry


class ConversationRuntime:
    def __init__(self, session: ConversationSession, model_router: ModelRouter,
                 tool_registry: ToolRegistry, permission_policy: PermissionPolicy | None = None,
                 max_tool_rounds: int = 50, max_steps: int = 100, event_bus=None):
        self.session = session
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.permission_policy = permission_policy or PermissionPolicy()
        self.max_tool_rounds = max_tool_rounds
        self.max_steps = max_steps
        self.event_bus = event_bus
        self._tool_names_this_turn: list[str] = []

    async def handle_user_message(self, text: str) -> str:
        """Process one user message. Non-streaming, backward compatible."""
        self._tool_names_this_turn = []
        self.session.append_user_message(text)
        system = self._build_system_prompt()
        tools_schema = self.tool_registry.get_tool_schemas()
        tool_rounds, step = 0, 0
        final_response = ""

        while tool_rounds < self.max_tool_rounds and step < self.max_steps:
            step += 1
            safe_msgs = self._safe_messages()
            request_msgs = [Message(role=MessageRole.SYSTEM, content=system)]
            request_msgs.extend(safe_msgs)
            provider = self._get_provider("executor")
            response = await provider.chat(LLMRequest(messages=request_msgs, tools=tools_schema))

            assistant_msg = Message(role=MessageRole.ASSISTANT, content=response.content or "",
                                   tool_calls=response.tool_calls,
                                   reasoning_content=response.reasoning_content)
            self.session.messages.append(assistant_msg)

            if response.tool_calls:
                tool_rounds += 1
                for tc in response.tool_calls:
                    self._tool_names_this_turn.append(tc.name)
                    decision = self.permission_policy.check("tool", tc.name, risk_level="medium")
                    if decision == PermissionDecision.DENY:
                        self.session.append_tool_message(tc.id, "Permission denied.", tc.name)
                        continue
                    if decision == PermissionDecision.ASK:
                        approval_results = await self._publish_tool_event(
                            "approval_requested", tc.name,
                            {"tool_call_id": tc.id, "arguments": tc.arguments},
                        )
                        approved = any(
                            r == "yes" or r == "remember" or r is True
                            for r in approval_results if r is not None
                        )
                        if approved:
                            await self._publish_tool_event("tool_call_started", tc.name, tc.arguments)
                            try:
                                result = await self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
                            except Exception as e:
                                result = type('obj', (object,), {'success': False, 'output': '', 'error': str(e)})()
                            out = getattr(result, 'output', '') or getattr(result, 'error', '') or ""
                            self.session.append_tool_message(tc.id, str(out), tc.name)
                            await self._publish_tool_event("tool_call_finished" if getattr(result, 'success', False) else "tool_call_failed", tc.name, {"output": out[:200]})
                        else:
                            self.session.append_tool_message(tc.id,
                                f"Approval required for: {tc.name}. Reply 'yes' to approve.", tc.name)
                        continue
                    await self._publish_tool_event("tool_call_started", tc.name, tc.arguments)
                    try:
                        result = await self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
                    except Exception as e:
                        result = type('obj', (object,), {'success': False, 'output': '', 'error': str(e)})()
                    out = getattr(result, 'output', '') or getattr(result, 'error', '') or ""
                    self.session.append_tool_message(tc.id, str(out), tc.name)
                    await self._publish_tool_event("tool_call_finished" if getattr(result, 'success', False) else "tool_call_failed", tc.name, {"output": out[:200]})
                continue

            final_response = response.content or ""
            break

        self.session.record_turn(text, final_response, tool_rounds)
        return final_response

    async def handle_user_message_stream(self, text: str) -> AsyncIterator[str]:
        """Process one user message, yielding text chunks for streaming.

        Yields reasoning summaries and final response chunks.
        """
        self._tool_names_this_turn = []
        self.session.append_user_message(text)
        system = self._build_system_prompt()
        tools_schema = self.tool_registry.get_tool_schemas()
        tool_rounds, step = 0, 0

        while tool_rounds < self.max_tool_rounds and step < self.max_steps:
            step += 1
            safe_msgs = self._safe_messages()
            request_msgs = [Message(role=MessageRole.SYSTEM, content=system)]
            request_msgs.extend(safe_msgs)
            provider = self._get_provider("executor")

            # Try streaming for final text response
            if step == 1 or True:
                response = await provider.chat(LLMRequest(messages=request_msgs, tools=tools_schema))
            else:
                response = await provider.chat(LLMRequest(messages=request_msgs, tools=tools_schema))

            assistant_msg = Message(role=MessageRole.ASSISTANT, content=response.content or "",
                                   tool_calls=response.tool_calls, reasoning_content=response.reasoning_content)
            self.session.messages.append(assistant_msg)

            if response.tool_calls:
                tool_rounds += 1
                for tc in response.tool_calls:
                    self._tool_names_this_turn.append(tc.name)
                    decision = self.permission_policy.check("tool", tc.name, risk_level="medium")
                    if decision == PermissionDecision.DENY:
                        self.session.append_tool_message(tc.id, "Permission denied.", tc.name)
                        continue
                    if decision == PermissionDecision.ASK:
                        approval_results = await self._publish_tool_event(
                            "approval_requested", tc.name,
                            {"tool_call_id": tc.id, "arguments": tc.arguments},
                        )
                        approved = any(
                            r == "yes" or r == "remember" or r is True
                            for r in approval_results if r is not None
                        )
                        if approved:
                            await self._publish_tool_event("tool_call_started", tc.name, tc.arguments)
                            try:
                                result = await self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
                            except Exception as e:
                                result = type('obj', (object,), {'success': False, 'output': '', 'error': str(e)})()
                            out = getattr(result, 'output', '') or getattr(result, 'error', '') or ""
                            self.session.append_tool_message(tc.id, str(out), tc.name)
                            await self._publish_tool_event("tool_call_finished" if getattr(result, 'success', False) else "tool_call_failed", tc.name, {"output": out[:200]})
                        else:
                            self.session.append_tool_message(tc.id,
                                f"Approval required for: {tc.name}. Reply 'yes' to approve.", tc.name)
                        continue
                    await self._publish_tool_event("tool_call_started", tc.name, tc.arguments)
                    try:
                        result = await self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
                    except Exception as e:
                        result = type('obj', (object,), {'success': False, 'output': '', 'error': str(e)})()
                    out = getattr(result, 'output', '') or getattr(result, 'error', '') or ""
                    self.session.append_tool_message(tc.id, str(out), tc.name)
                    await self._publish_tool_event("tool_call_finished" if getattr(result, 'success', False) else "tool_call_failed", tc.name, {"output": out[:200]})
                # Yield reasoning for this tool phase
                if self._tool_names_this_turn:
                    yield self._generate_reasoning()
                continue

            # Final text response — yield chunk by chunk
            text = response.content or ""
            for i in range(0, len(text), 80):
                yield text[i:i+80]
            break

        self.session.record_turn(text, text if 'text' in dir() else "", tool_rounds)

    _last_reasoning: str = ""

    def _generate_reasoning(self) -> str:
        """Generate public reasoning summary — deduplicated."""
        names = self._tool_names_this_turn
        if not names:
            return ""
        if "list_directory" in names or "grep" in names:
            msg = "· Exploring repository structure..."
        elif "read_file" in names:
            msg = "· Reading relevant files..."
        elif "bash" in names or "python" in names:
            msg = "· Running commands..."
        elif "write_file" in names or "edit_file" in names:
            msg = "· Applying changes..."
        else:
            msg = f"· Executing: {', '.join(names[:3])}..."
        if msg == self._last_reasoning:
            return ""
        self._last_reasoning = msg
        return msg

    def _safe_messages(self) -> list[Message]:
        history = self.session.messages[-50:]
        safe, has_tc = [], False
        for m in history:
            if m.role == MessageRole.ASSISTANT and m.tool_calls:
                has_tc = True
            if m.role == MessageRole.TOOL and not has_tc:
                continue
            safe.append(m)
            if m.role == MessageRole.TOOL:
                has_tc = False
        return safe

    async def _publish_tool_event(self, etype: str, name: str, payload: dict | None = None):
        if not self.event_bus:
            return []
        from evoagent.cli.ui.events import UIEvent, UIEventType
        return await self.event_bus.publish(UIEvent(type=UIEventType(etype), session_id=self.session.session_id,
                                                    payload={"tool_name": name, **(payload or {})}))

    def _build_system_prompt(self) -> str:
        from evoagent.conversation.schema import AgentMode
        hints = {AgentMode.DEFAULT: "You are an interactive coding agent. Use tools.",
                 AgentMode.PLAN: "Plan mode: inspect first. Create plan before changes. Ask before editing.",
                 AgentMode.AUTO: "Auto mode: execute autonomously."}
        base = hints.get(self.session.mode, hints[AgentMode.DEFAULT])
        if self.session.current_plan:
            base += "\nPlan:\n" + "\n".join(f"{i+1}. {s.goal}" for i, s in enumerate(self.session.current_plan.steps))
        if self.session.mode == AgentMode.PLAN:
            base += "\nDo NOT edit files until the user approves."
        return base

    def _get_provider(self, role: str):
        try:
            return self.model_router._get_provider(role)
        except Exception:
            return self.model_router._get_provider("default")
