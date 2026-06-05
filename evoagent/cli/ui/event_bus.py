"""Async EventBus — decoupled communication between Runtime and UI."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from evoagent.cli.ui.events import UIEvent


class EventBus:
    """Simple async pub/sub event bus.

    ConversationRuntime publishes events.
    Terminal UI subscribes and renders.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable[[UIEvent], Coroutine[Any, Any, None]]]] = {}

    def subscribe(self, event_type: str, handler: Callable[[UIEvent], Coroutine[Any, Any, None]]) -> None:
        """Register a handler for an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    async def publish(self, event: UIEvent) -> None:
        """Publish an event to all subscribers."""
        handlers = self._subscribers.get(event.type.value, [])
        results = [h(event) for h in handlers]
        if results:
            return await asyncio.gather(*results)
        return []
