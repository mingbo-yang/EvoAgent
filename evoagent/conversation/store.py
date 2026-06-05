"""SessionStore — persist and load ConversationSessions."""

import json
from pathlib import Path

from evoagent.conversation.session import ConversationSession


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
            "turns": [t.model_dump() for t in session.turns],
            "messages": [
                {"role": m.role.value, "content": m.content, "tool_call_id": m.tool_call_id, "name": m.name}
                for m in session.messages[-100:]
            ],
        }
        (session_dir / "session.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return session.session_id

    def load(self, session_id: str) -> ConversationSession | None:
        session_dir = self.dir / session_id
        if not session_dir.exists():
            return None
        data = json.loads((session_dir / "session.json").read_text())
        session = ConversationSession(session_id=data["session_id"], workspace=data.get("workspace", "."))
        session.mode = __import__("evoagent.conversation.schema", fromlist=["AgentMode"]).AgentMode(data.get("mode", "default"))
        session.created_at = data.get("created_at", "")
        session.updated_at = data.get("updated_at", "")
        return session

    def list_sessions(self) -> list[str]:
        if not self.dir.exists():
            return []
        return sorted([d.name for d in self.dir.iterdir() if d.is_dir()], reverse=True)

    def latest(self) -> ConversationSession | None:
        sessions = self.list_sessions()
        return self.load(sessions[0]) if sessions else None
