"""ConversationSession — persistent multi-turn conversation state."""

from pathlib import Path
from typing import Any

from evoagent.conversation.schema import AgentMode, TurnRecord
from evoagent.core.ids import generate_id
from evoagent.core.message import Message, MessageRole
from evoagent.core.time import utc_now_iso
from evoagent.planning.schema import Plan


class ConversationSession:
    """Persistent interactive conversation across many user turns.

    Holds full message history, current mode, plan, and metadata.
    """

    def __init__(self, session_id: str | None = None, workspace: str = "."):
        self.session_id = session_id or generate_id("sess")
        self.workspace = Path(workspace)
        self.mode: AgentMode = AgentMode.DEFAULT
        self.messages: list[Message] = []
        self.current_plan: Plan | None = None
        self.turns: list[TurnRecord] = []
        self.metadata: dict[str, Any] = {}
        self.created_at = utc_now_iso()
        self.updated_at = self.created_at

    def append_user_message(self, text: str) -> Message:
        msg = Message(role=MessageRole.USER, content=text)
        self.messages.append(msg)
        self.updated_at = utc_now_iso()
        return msg

    def append_assistant_message(self, text: str) -> Message:
        msg = Message(role=MessageRole.ASSISTANT, content=text)
        self.messages.append(msg)
        self.updated_at = utc_now_iso()
        return msg

    def append_tool_message(self, tool_call_id: str, content: str, name: str = "") -> Message:
        msg = Message(role=MessageRole.TOOL, content=content, tool_call_id=tool_call_id, name=name)
        self.messages.append(msg)
        self.updated_at = utc_now_iso()
        return msg

    def set_mode(self, mode: AgentMode) -> None:
        self.mode = mode

    def set_plan(self, plan: Plan) -> None:
        self.current_plan = plan

    def clear_plan(self) -> None:
        self.current_plan = None

    def record_turn(self, user_message: str, response: str, tool_count: int = 0) -> None:
        self.turns.append(TurnRecord(
            turn_id=generate_id("turn"),
            user_message=user_message[:200],
            assistant_response=response[:200],
            tool_calls_count=tool_count,
            started_at=utc_now_iso(),
            finished_at=utc_now_iso(),
        ))
