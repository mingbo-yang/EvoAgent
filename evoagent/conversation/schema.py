"""Conversation schema — AgentMode, PlanningPolicy, TurnRecord."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class AgentMode(StrEnum):
    DEFAULT = "default"
    PLAN = "plan"
    AUTO = "auto"


class PlanningPolicy(StrEnum):
    ADAPTIVE = "adaptive"
    MANDATORY = "mandatory"


class TurnRecord(BaseModel):
    turn_id: str
    user_message: str = ""
    assistant_response: str = ""
    tool_calls_count: int = 0
    started_at: str = ""
    finished_at: str = ""
