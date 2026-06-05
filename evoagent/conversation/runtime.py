"""ConversationRuntime — execute one user turn within a persistent session.

Supports multi-tool loops within a single turn, mode-aware
execution, and preserves full message history.
"""

import json

from evoagent.conversation.schema import AgentMode
from evoagent.conversation.session import ConversationSession
from evoagent.core.message import Message, MessageRole
from evoagent.models.router import ModelRouter
from evoagent.models.schema import LLMRequest
from evoagent.sandbox.policy import PermissionPolicy
from evoagent.tools.registry import ToolRegistry


class ConversationRuntime:
    """Executes one user turn within a persistent session.

    The runtime loops: model → tool calls → model → ... → final reply.
    """

    def __init__(
        self,
        session: ConversationSession,
        model_router: ModelRouter,
        tool_registry: ToolRegistry,
        permission_policy: PermissionPolicy | None = None,
        max_tool_rounds: int = 50,
        max_steps: int = 100,
    ):
        self.session = session
        self.model_router = model_router
        self.tool_registry = tool_registry
        self.permission_policy = permission_policy or PermissionPolicy()
        self.max_tool_rounds = max_tool_rounds
        self.max_steps = max_steps

    async def handle_user_message(self, text: str) -> str:
        """Process one user message and return a final response.

        Loops internally for tool calls within the same turn.
        """
        self.session.append_user_message(text)

        # Build system prompt with mode information
        system = self._build_system_prompt()
        tools_schema = self.tool_registry.get_tool_schemas()

        tool_rounds = 0
        step = 0
        final_response = ""

        while tool_rounds < self.max_tool_rounds and step < self.max_steps:
            step += 1

            # Assemble messages for model
            model_messages = [{"role": MessageRole.SYSTEM.value, "content": system}]
            for m in self.session.messages[-50:]:
                msg_dict: dict = {"role": m.role.value, "content": m.content}
                if m.tool_call_id:
                    msg_dict["tool_call_id"] = m.tool_call_id
                if m.name:
                    msg_dict["name"] = m.name
                if m.tool_calls:
                    msg_dict["tool_calls"] = [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in m.tool_calls
                    ]
                model_messages.append(msg_dict)

            provider = self._get_provider("executor")
            response = await provider.chat(LLMRequest(messages=model_messages, tools=tools_schema))

            # Build assistant message from response
            assistant_msg = Message(role=MessageRole.ASSISTANT, content=response.content or "",
                                   tool_calls=response.tool_calls)
            self.session.messages.append(assistant_msg)

            if response.tool_calls:
                tool_rounds += 1
                for tc in response.tool_calls:
                    # Check permission
                    if self.session.mode != AgentMode.AUTO:
                        decision = self.permission_policy.check("tool", tc.name, risk_level="medium")
                        if decision.value == "deny":
                            self.session.append_tool_message(tc.id, "Permission denied.", tc.name)
                            continue

                    try:
                        result = await self.tool_registry.run_tool(tc.name, tc.arguments)
                    except Exception as e:
                        result = type('obj', (object,), {'success': False, 'output': '', 'error': str(e)})()

                    tool_content = result.output or result.error or ""
                    self.session.append_tool_message(tc.id, str(tool_content), tc.name)
                continue  # loop back to model

            final_response = response.content or ""
            break

        self.session.record_turn(text, final_response, tool_rounds)
        return final_response

    def _build_system_prompt(self) -> str:
        mode_hint = {
            AgentMode.DEFAULT: "You are an interactive coding agent. Use tools when needed. Plan complex tasks.",
            AgentMode.PLAN: "You are in plan mode. Inspect first. Create a plan before making changes. Ask for approval before editing files.",
            AgentMode.AUTO: "You are in auto mode. Execute tasks autonomously. Fix errors automatically. Run tests without asking.",
        }
        base = mode_hint.get(self.session.mode, mode_hint[AgentMode.DEFAULT])
        if self.session.current_plan:
            steps = [f"{i+1}. {s.goal}" for i, s in enumerate(self.session.current_plan.steps)]
            base += "\n\nCurrent Plan:\n" + "\n".join(steps)
        if self.session.mode == AgentMode.PLAN:
            base += "\n\nDo NOT edit files or run shell commands until the user approves your plan."
        return base

    def _get_provider(self, role: str):
        try:
            return self.model_router._get_provider(role)
        except Exception:
            return self.model_router._get_provider("default")
