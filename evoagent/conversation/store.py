"""SessionStore — persist and load ConversationSessions."""

import json
from pathlib import Path

from evoagent.conversation.schema import TurnRecord
from evoagent.conversation.session import ConversationSession
from evoagent.core.message import Message
from evoagent.planning.schema import Plan


class SessionStore:
    """JSON-file-based session persistence."""

    def __init__(self, sessions_dir: str = ".evoagent/sessions"):
        self.dir = Path(sessions_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, session: ConversationSession) -> str:
        session_dir = self.dir / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "session_id": session.session_id,
            "workspace": str(session.workspace),
            "mode": session.mode.value,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "current_plan": session.current_plan.model_dump() if session.current_plan else None,
            "metadata": session.metadata,
            "turns": [t.model_dump() for t in session.turns],
            "messages": [m.model_dump() for m in session.messages[-100:]],
        }
        (session_dir / "session.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return session.session_id

    def load(self, session_id: str) -> ConversationSession | None:
        session_dir = self.dir / session_id
        if not session_dir.exists():
            return None
        data = json.loads((session_dir / "session.json").read_text())
        session = ConversationSession(
            session_id=data["session_id"],
            workspace=data.get("workspace", "."),
        )
        session.mode = __import__(
            "evoagent.conversation.schema",
            fromlist=["AgentMode"],
        ).AgentMode(data.get("mode", "default"))
        session.created_at = data.get("created_at", "")
        session.updated_at = data.get("updated_at", "")
        session.current_plan = (
            Plan.model_validate(data["current_plan"]) if data.get("current_plan") else None
        )
        session.metadata = data.get("metadata", {})
        session.turns = [
            TurnRecord.model_validate(t)
            for t in data.get("turns", [])
        ]
        session.messages = [
            Message.model_validate(m)
            for m in data.get("messages", [])
        ]
        return session

    def list_sessions(self) -> list[str]:
        if not self.dir.exists():
            return []
        return sorted([d.name for d in self.dir.iterdir() if d.is_dir()], reverse=True)

    def latest(self) -> ConversationSession | None:
        sessions = self.list_sessions()
        return self.load(sessions[0]) if sessions else None
