"""Planner — decompose a task into a structured Plan."""

import json
import re
from typing import Any

from evoagent.core.errors import PlanningError
from evoagent.core.ids import generate_id
from evoagent.logging.event import EventType
from evoagent.models.base import BaseLLMProvider
from evoagent.models.schema import LLMRequest
from evoagent.planning.prompts import PLANNER_SYSTEM_PROMPT, PLANNER_USER_TEMPLATE
from evoagent.planning.schema import ActionType, Plan, PlanStep, RiskLevel


class Planner:
    """Task-to-plan decomposition using an LLM.

    Generates a structured Plan from a task description and
    the list of available tools.

    Falls back to a simple plan if LLM output cannot be parsed.
    """

    def __init__(
        self,
        llm: BaseLLMProvider,
        max_steps: int = 10,
        event_logger: Any = None,
    ):
        self.llm = llm
        self.max_steps = max_steps
        self.event_logger = event_logger

    async def plan(self, task: str, tools_schema: list[dict[str, Any]], context: str = "") -> Plan:
        """Generate a plan for the given task.

        Args:
            task: The user's task description.
            tools_schema: List of available tool schemas.
            context: Additional context (memories, docs, etc.).

        Returns:
            A Plan with ordered steps.

        Raises:
            PlanningError: If the plan cannot be generated.
        """
        tools_text = json.dumps([t.get("function", {}).get("name", "?") for t in tools_schema])
        user_msg = PLANNER_USER_TEMPLATE.format(task=task, tools=tools_text, context=context)

        request = LLMRequest(
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.0,
        )

        try:
            response = await self.llm.chat(request)
        except Exception as e:
            raise PlanningError(f"Planner LLM call failed: {e}") from e

        plan = self._parse_plan(response.content, task)
        if self.event_logger:
            self.event_logger.log(EventType.PLAN_CREATED, payload={"task": task})

        return plan

    def _parse_plan(self, content: str, task: str) -> Plan:
        """Parse LLM output into a Plan. Tries to fix common JSON issues."""
        json_str = content.strip()

        # Extract JSON from code blocks if present
        code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", json_str)
        if code_match:
            json_str = code_match.group(1).strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            data = self._repair_json(json_str, task)

        if not data or "steps" not in data:
            data = self._fallback_plan(task)

        steps = []
        for s in data.get("steps", [])[:self.max_steps]:
            step = PlanStep(
                goal=s.get("goal", "Unknown step"),
                action_type=ActionType(s.get("action_type", "tool")),
                tool_name=s.get("tool_name"),
                arguments=s.get("arguments", {}),
                expected_result=s.get("expected_result"),
            )
            steps.append(step)

        if not steps or steps[-1].action_type != ActionType.FINISH:
            steps.append(PlanStep(goal="Finish the task", action_type=ActionType.FINISH))

        return Plan(
            id=generate_id("plan"),
            task=task,
            steps=steps,
            risk_level=RiskLevel(data.get("risk_level", "low")),
        )

    def _repair_json(self, text: str, task: str) -> dict:
        """Attempt to repair common JSON errors."""
        # Try extracting just the JSON object
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        raise PlanningError(f"Failed to parse planner output as JSON: {text[:200]}")

    def _fallback_plan(self, task: str) -> dict:
        """Create a safe inspect-first fallback plan.

        Never uses arbitrary bash — only safe inspection tools.
        """
        return {"risk_level": "medium", "steps": [
            {"goal": "Inspect workspace to understand the task context",
             "action_type": "tool", "tool_name": "list_directory",
             "arguments": {"path": "."}, "expected_result": "See available files"},
            {"goal": "Request clarification for the task",
             "action_type": "ask_user",
             "expected_result": f"Task was: {task}"},
            {"goal": "Finish", "action_type": "finish"},
        ]}
