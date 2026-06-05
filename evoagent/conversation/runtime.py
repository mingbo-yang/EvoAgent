"""ConversationRuntime — execute one user turn within a persistent session.

Uses internal Message/ToolCall format throughout.
Provider wire format is handled ONLY by provider adapters.
"""

from evoagent.conversation.session import ConversationSession
from evoagent.core.message import Message, MessageRole
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMRequest
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.sandbox.schema import PermissionDecision
from evoagent.tools.registry import ToolRegistry


class ConversationRuntime:
    """Executes one user turn within a persistent session.

    Loops: model → tool calls → model → ... → final reply.
    All messages use internal Message/ToolCall format.
    """

    def __init__(
        self,
        session: ConversationSession,
        model_router: ModelRouter,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy | None = None,
        max_tool_rounds: int = 50,
        max_steps: int = 100,
        event_bus=None,
    ):
        self.session = session
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.permission_policy = permission_policy or PermissionPolicy()
        self.max_tool_rounds = max_tool_rounds
        self.max_steps = max_steps
        self.event_bus = event_bus

    async def handle_user_message_stream(self, text: str):
        """Process one user message, yielding text chunks as they arrive."""
        self.session.append_user_message(text)
        system = self._build_system_prompt()
        tools_schema = self.tool_registry.get_tool_schemas()
        tool_rounds = 0
        step = 0
        final_text = ""

        while tool_rounds < self.max_tool_rounds and step < self.max_steps:
            step += 1
            history = self.session.messages[-50:]
            safe_messages = []
            has_tc = False
            for m in history:
                if m.role == MessageRole.ASSISTANT and m.tool_calls:
                    has_tc = True
                if m.role == MessageRole.TOOL and not has_tc:
                    continue
                safe_messages.append(m)
                if m.role == MessageRole.TOOL:
                    has_tc = False
            request_messages = [Message(role=MessageRole.SYSTEM, content=system)]
            request_messages.extend(safe_messages)

            provider = self._get_provider("executor")
            response = await provider.chat(LLMRequest(messages=request_messages, tools=tools_schema))

            assistant_msg = Message(role=MessageRole.ASSISTANT, content=response.content or "",
                                   tool_calls=response.tool_calls,
                                   reasoning_content=response.reasoning_content)
            self.session.messages.append(assistant_msg)

            if response.tool_calls:
                tool_rounds += 1
                for tc in response.tool_calls:
                    decision = self.permission_policy.check("tool", tc.name, risk_level="medium")
                    if decision.value == "deny":
                        self.session.append_tool_message(tc.id, "Permission denied.", tc.name)
                        continue
                    if decision.value == "ask":
                        self.session.append_tool_message(tc.id,
                            f"Approval required for: {tc.name}. Try alternative approach.", tc.name)
                        continue
                    if self.event_bus:
                        from evoagent.cli.ui.events import UIEvent, UIEventType
                        await self.event_bus.publish(UIEvent(type=UIEventType.TOOL_CALL_STARTED,
                            session_id=self.session.session_id,
                            payload={"tool_name": tc.name, "arguments": tc.arguments}))
                    try:
                        result = await self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
                    except Exception as e:
                        result = type('obj', (object,), {'success': False, 'output': '', 'error': str(e)})()
                    tool_content = getattr(result, 'output', '') or getattr(result, 'error', '') or ""
                    self.session.append_tool_message(tc.id, str(tool_content), tc.name)
                continue

            final_text = response.content or ""
            yield final_text
            break

        self.session.record_turn(text, final_text, tool_rounds)

    async def handle_user_message(self, text: str) -> str:
        """Process one user message. Multiple tool calls within one turn."""
        """Process one user message. Multiple tool calls within one turn."""
        self.session.append_user_message(text)

        system = self._build_system_prompt()
        tools_schema = self.tool_registry.get_tool_schemas()

        tool_rounds = 0
        step = 0
        final_response = ""

        while tool_rounds < self.max_tool_rounds and step < self.max_steps:
            step += 1

            # Build request — ensure no orphaned tool messages
            # (every tool message must follow an assistant with tool_calls)
            history = self.session.messages[-50:]
            safe_messages = []
            has_pending_tool_call = False
            for m in history:
                if m.role == MessageRole.ASSISTANT and m.tool_calls:
                    has_pending_tool_call = True
                if m.role == MessageRole.TOOL and not has_pending_tool_call:
                    continue  # skip orphaned tool message
                safe_messages.append(m)
                if m.role == MessageRole.TOOL:
                    has_pending_tool_call = False  # consumed

            request_messages = [Message(role=MessageRole.SYSTEM, content=system)]
            request_messages.extend(safe_messages)

            provider = self._get_provider("executor")
            response = await provider.chat(LLMRequest(messages=request_messages, tools=tools_schema))

            # Build assistant message from response (internal format only)
            assistant_msg = Message(
                role=MessageRole.ASSISTANT,
                content=response.content or "",
                tool_calls=response.tool_calls,
                reasoning_content=response.reasoning_content,
            )
            self.session.messages.append(assistant_msg)

            if response.tool_calls:
                tool_rounds += 1
                for tc in response.tool_calls:
                    # Permission check
                    decision = self.permission_policy.check("tool", tc.name, risk_level="medium")
                    if decision == PermissionDecision.DENY:
                        self.session.append_tool_message(tc.id, "Permission denied.", tc.name)
                        continue
                    if decision == PermissionDecision.ASK:
                        self.session.append_tool_message(
                            tc.id,
                            f"Approval required for: {tc.name}. "
                            "Please try an alternative approach or use a read-only tool instead.",
                            tc.name)
                        continue  # model will see this tool result and retry

                    # Publish tool_call_started event
                    if self.event_bus:
                        from evoagent.cli.ui.events import UIEvent, UIEventType
                        await self.event_bus.publish(UIEvent(
                            type=UIEventType.TOOL_CALL_STARTED,
                            session_id=self.session.session_id,
                            payload={"tool_name": tc.name, "arguments": tc.arguments},
                        ))

                    # Execute tool — pass call_id for ToolResult.call_id consistency
                    try:
                        result = await self.tool_registry.run_tool(tc.name, tc.arguments, call_id=tc.id)
                    except Exception as e:
                        result = type('obj', (object,), {'success': False, 'output': '', 'error': str(e)})()

                    # Publish tool_call_finished event
                    if self.event_bus:
                        from evoagent.cli.ui.events import UIEvent, UIEventType
                        await self.event_bus.publish(UIEvent(
                            type=UIEventType.TOOL_CALL_FINISHED if getattr(result, 'success', False) else UIEventType.TOOL_CALL_FAILED,
                            session_id=self.session.session_id,
                            payload={"tool_name": tc.name, "output": str(getattr(result, 'output', '') or getattr(result, 'error', ''))[:200]},
                        ))

                    tool_content = getattr(result, 'output', '') or getattr(result, 'error', '') or ""
                    self.session.append_tool_message(tc.id, str(tool_content), tc.name)
                continue

            final_response = response.content or ""
            break

        self.session.record_turn(text, final_response, tool_rounds)
        return final_response

    def _build_system_prompt(self) -> str:
        from evoagent.conversation.schema import AgentMode
        mode_hint = {
            AgentMode.DEFAULT: "You are an interactive coding agent. Use tools when needed.",
            AgentMode.PLAN: "Plan mode: inspect first. Create a plan before changes. Ask before editing.",
            AgentMode.AUTO: "Auto mode: execute autonomously. Fix errors automatically.",
        }
        base = mode_hint.get(self.session.mode, mode_hint[AgentMode.DEFAULT])
        if self.session.current_plan:
            steps = [f"{i+1}. {s.goal}" for i, s in enumerate(self.session.current_plan.steps)]
            base += "\n\nCurrent Plan:\n" + "\n".join(steps)
        if self.session.mode == AgentMode.PLAN:
            base += "\nDo NOT edit files until the user approves your plan."
        return base

    def _get_provider(self, role: str):
        try:
            return self.model_router._get_provider(role)
        except Exception:
            return self.model_router._get_provider("default")
