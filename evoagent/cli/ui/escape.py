"""Escape action resolver — unified Esc key handling."""

import time
from enum import StrEnum

from pydantic import BaseModel


class EscapeAction(StrEnum):
    IGNORE = "ignore"
    ARM_EXIT = "arm_exit"
    EXIT = "exit"
    INTERRUPT = "interrupt"


class EscapeState(BaseModel):
    armed: bool = False
    last_escape_at: float | None = None
    timeout_ms: int = 800
    is_executing: bool = False
    buffer_empty: bool = True


class EscapeActionResolver:
    """Unified resolver for Escape key actions.

    Priority: completion → detail → approval → plan → interrupt → exit
    """

    def __init__(self, timeout_ms: int = 800):
        self.state = EscapeState(timeout_ms=timeout_ms)

    def resolve(self, is_executing: bool = False, buffer_empty: bool = True,
                in_modal: bool = False) -> EscapeAction:
        """Determine the action for an Escape key press."""
        self.state.is_executing = is_executing
        self.state.buffer_empty = buffer_empty

        # Modal contexts: single Esc cancels, never exits
        if in_modal:
            self.state.armed = False
            self.state.last_escape_at = None
            return EscapeAction.IGNORE  # handled by modal

        # During execution: interrupt
        if is_executing:
            self.state.armed = False
            self.state.last_escape_at = None
            return EscapeAction.INTERRUPT

        # Buffer non-empty: clear, don't exit
        if not buffer_empty:
            self.state.armed = False
            self.state.last_escape_at = None
            return EscapeAction.IGNORE

        # Idle + empty buffer: check double-Esc
        now = time.monotonic()
        if self.state.armed and self.state.last_escape_at is not None:
            elapsed_ms = (now - self.state.last_escape_at) * 1000
            if elapsed_ms <= self.state.timeout_ms:
                self.state.armed = False
                self.state.last_escape_at = None
                return EscapeAction.EXIT

        self.state.armed = True
        self.state.last_escape_at = now
        return EscapeAction.ARM_EXIT

    def reset(self) -> None:
        self.state.armed = False
        self.state.last_escape_at = None

    def is_armed(self) -> bool:
        if not self.state.armed or self.state.last_escape_at is None:
            return False
        elapsed = (time.monotonic() - self.state.last_escape_at) * 1000
        if elapsed > self.state.timeout_ms:
            self.state.armed = False
            self.state.last_escape_at = None
            return False
        return True
