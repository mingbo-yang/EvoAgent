"""Comprehensive tests for all core schema types."""

import json

import pytest

from evoagent.core import (
    ActionType,
    AgentContext,
    AgentResult,
    Checkpoint,
    ConfigError,
    ContentBlock,
    ContentBlockType,
    EvalResult,
    EvalTask,
    EvaluationError,
    Event,
    EventType,
    EvoAgentError,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    MemoryError,
    MemoryItem,
    MemoryType,
    Message,
    MessageRole,
    ModelProviderError,
    PermissionDeniedError,
    Plan,
    PlanningError,
    PlanStep,
    RiskLevel,
    RunStatus,
    RuntimeState,
    SandboxError,
    StepResult,
    ToolCall,
    ToolError,
    ToolResult,
    generate_id,
    safe_json_dumps,
    truncate_text,
    utc_now_iso,
)

# ── ID & time utilities ───────────────────────────────────────────────


def test_generate_id_no_prefix():
    assert len(generate_id()) == 12


def test_generate_id_with_prefix():
    result = generate_id("run")
    assert result.startswith("run_")
    assert len(result) == 16  # "run_" + 12 hex


def test_generate_id_unique():
    ids = {generate_id() for _ in range(100)}
    assert len(ids) == 100


def test_utc_now_iso():
    result = utc_now_iso()
    assert "T" in result
    assert "+" in result or "Z" in result


def test_safe_json_dumps():
    data = {"key": "value", "num": 42}
    assert json.loads(safe_json_dumps(data)) == data


def test_safe_json_dumps_non_serializable():
    """Non-serializable objects are converted via str() fallback."""
    result = safe_json_dumps(object())
    # Should produce a valid JSON string (the str() repr of the object)
    assert result.startswith('"')
    assert json.loads(result)  # valid JSON


def test_truncate_text_short():
    assert truncate_text("hello") == "hello"


def test_truncate_text_long():
    result = truncate_text("x" * 10000, max_length=100)
    assert len(result) <= 100
    assert "truncated" in result


# ── Exceptions ────────────────────────────────────────────────────────


def test_evoagent_error_base():
    with pytest.raises(EvoAgentError):
        raise EvoAgentError("base")


def test_config_error():
    with pytest.raises(ConfigError):
        raise ConfigError("bad config")


def test_model_provider_error():
    with pytest.raises(ModelProviderError):
        raise ModelProviderError("api down")


def test_tool_error():
    with pytest.raises(ToolError):
        raise ToolError("tool failed")


def test_permission_denied_error():
    with pytest.raises(PermissionDeniedError):
        raise PermissionDeniedError("not allowed")


def test_sandbox_error():
    with pytest.raises(SandboxError):
        raise SandboxError("sandbox crash")


def test_memory_error():
    with pytest.raises(MemoryError):
        raise MemoryError("memory full")


def test_planning_error():
    with pytest.raises(PlanningError):
        raise PlanningError("plan failed")


def test_evaluation_error():
    with pytest.raises(EvaluationError):
        raise EvaluationError("eval broken")


def test_error_chain():
    """All errors should inherit from EvoAgentError."""
    for cls in [
        ConfigError,
        ModelProviderError,
        ToolError,
        PermissionDeniedError,
        SandboxError,
        MemoryError,
        PlanningError,
        EvaluationError,
    ]:
        assert issubclass(cls, EvoAgentError)


# ── Message ───────────────────────────────────────────────────────────


def test_message_creation():
    msg = Message(role=MessageRole.USER, content="hello")
    assert msg.role == MessageRole.USER
    assert msg.content == "hello"
    assert msg.created_at


def test_message_serialization():
    msg = Message(role=MessageRole.ASSISTANT, content="hi", name="bot")
    data = msg.model_dump()
    restored = Message.model_validate(data)
    assert restored.content == "hi"
    assert restored.name == "bot"


def test_message_with_tool_calls():
    tc = ToolCall(id="call_1", name="read_file", arguments={"path": "test.py"})
    msg = Message(role=MessageRole.ASSISTANT, content="", tool_calls=[tc])
    data = msg.model_dump_json()
    restored = Message.model_validate_json(data)
    assert len(restored.tool_calls) == 1
    assert restored.tool_calls[0].name == "read_file"


def test_message_tool_role():
    msg = Message(
        role=MessageRole.TOOL,
        content="file contents",
        tool_call_id="call_1",
    )
    assert msg.role == MessageRole.TOOL
    assert msg.tool_call_id == "call_1"


def test_content_block():
    cb = ContentBlock(type=ContentBlockType.CODE, content="print(1)", metadata={"lang": "python"})
    data = cb.model_dump()
    restored = ContentBlock.model_validate(data)
    assert restored.type == ContentBlockType.CODE
    assert restored.metadata["lang"] == "python"


# ── ToolCall / ToolResult ─────────────────────────────────────────────


def test_tool_call_creation():
    tc = ToolCall(name="calculator", arguments={"expr": "1+1"}, raw='{"expr": "1+1"}')
    assert tc.id.startswith("call_")
    assert tc.name == "calculator"
    assert tc.arguments == {"expr": "1+1"}


def test_tool_result_creation():
    tr = ToolResult(
        call_id="call_1",
        name="calculator",
        success=True,
        output="2",
        duration_ms=100,
    )
    assert tr.success
    assert tr.output == "2"
    assert tr.duration_ms == 100


def test_tool_result_serialization():
    tr = ToolResult(call_id="call_1", name="test", success=False, error="timeout")
    data = tr.model_dump()
    restored = ToolResult.model_validate(data)
    assert restored.success is False
    assert restored.error == "timeout"


# ── Plan / PlanStep ──────────────────────────────────────────────────


def test_plan_step_creation():
    step = PlanStep(goal="Read the file", action_type=ActionType.TOOL, tool_name="read_file")
    assert step.goal == "Read the file"
    assert step.status == "pending"


def test_plan_creation():
    steps = [
        PlanStep(goal="Step 1", action_type=ActionType.TOOL, tool_name="list_dir"),
        PlanStep(goal="Step 2", action_type=ActionType.FINISH),
    ]
    plan = Plan(task="List directory", steps=steps, risk_level=RiskLevel.LOW)
    assert len(plan.steps) == 2
    assert plan.risk_level == "low"


def test_plan_serialization():
    plan = Plan(task="test", steps=[PlanStep(goal="do it")])
    data = plan.model_dump()
    restored = Plan.model_validate(data)
    assert restored.task == "test"
    assert len(restored.steps) == 1


def test_step_status_transition():
    step = PlanStep(goal="test")
    assert step.status == "pending"
    step.status = "completed"
    assert step.status == "completed"


# ── RuntimeState ─────────────────────────────────────────────────────


def test_runtime_state_creation():
    state = RuntimeState(task="Test task")
    assert state.run_id.startswith("run_")
    assert state.status == RunStatus.CREATED
    assert state.messages == []
    assert state.plan is None


def test_runtime_state_update():
    state = RuntimeState(task="Test")
    state.status = RunStatus.RUNNING
    state.messages.append(Message(role=MessageRole.USER, content="hello"))
    assert state.status == RunStatus.RUNNING
    assert len(state.messages) == 1


def test_runtime_state_serialization():
    state = RuntimeState(task="Test", status=RunStatus.SUCCEEDED)
    data = state.model_dump()
    restored = RuntimeState.model_validate(data)
    assert restored.task == "Test"
    assert restored.status == RunStatus.SUCCEEDED


def test_step_result_creation():
    sr = StepResult(step_id="step_1", success=True, output="done", duration_ms=50)
    assert sr.step_id == "step_1"
    assert sr.success


def test_checkpoint_creation():
    state = RuntimeState(task="checkpoint test")
    chk = Checkpoint(state=state, can_resume=True)
    assert chk.id.startswith("chk_")
    assert chk.can_resume


# ── AgentResult ──────────────────────────────────────────────────────


def test_agent_result_creation():
    result = AgentResult(
        run_id="run_abc",
        task="do stuff",
        success=True,
        final_answer="Done!",
        steps_taken=3,
        total_tokens=1500,
    )
    assert result.success
    assert result.steps_taken == 3


def test_agent_result_serialization():
    result = AgentResult(run_id="run_1", task="x", success=False, error="fail")
    data = result.model_dump()
    restored = AgentResult.model_validate(data)
    assert restored.success is False


# ── LLM types ────────────────────────────────────────────────────────


def test_llm_request_creation():
    req = LLMRequest(
        messages=[Message(role=MessageRole.USER, content="hi")],
        model="deepseek-chat",
    )
    assert req.model == "deepseek-chat"
    assert len(req.messages) == 1


def test_llm_response_creation():
    resp = LLMResponse(
        content="Hello!",
        finish_reason="stop",
        usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model="deepseek-chat",
        latency_ms=200,
    )
    assert resp.content == "Hello!"
    assert resp.usage.total_tokens == 15


def test_llm_response_with_tool_calls():
    tc = ToolCall(id="c1", name="search", arguments={"q": "test"})
    resp = LLMResponse(
        content="",
        tool_calls=[tc],
        finish_reason="tool_calls",
        model="deepseek-chat",
    )
    assert len(resp.tool_calls) == 1


# ── AgentContext ─────────────────────────────────────────────────────


def test_agent_context_creation():
    ctx = AgentContext(
        task="build a web app",
        system_prompt="You are a helpful assistant.",
        messages=[Message(role=MessageRole.USER, content="go")],
    )
    assert ctx.task == "build a web app"
    assert len(ctx.messages) == 1


# ── Event ────────────────────────────────────────────────────────────


def test_event_creation():
    evt = Event(
        run_id="run_1",
        step_id="step_1",
        event_type=EventType.TOOL_CALL_STARTED,
        payload={"tool": "read_file", "args": {"path": "a.py"}},
    )
    assert evt.id.startswith("evt_")
    assert evt.event_type == EventType.TOOL_CALL_STARTED


def test_event_serialization_json():
    evt = Event(
        run_id="run_1",
        event_type=EventType.RUN_FINISHED,
        payload={"success": True},
    )
    json_str = evt.model_dump_json()
    assert "run_1" in json_str
    restored = Event.model_validate_json(json_str)
    assert restored.event_type == EventType.RUN_FINISHED


# ── MemoryItem ───────────────────────────────────────────────────────


def test_memory_item_creation():
    item = MemoryItem(
        memory_type=MemoryType.EPISODIC,
        content="I fixed the bug in auth.py",
        importance=0.8,
        confidence=0.9,
    )
    assert item.memory_type == MemoryType.EPISODIC
    assert item.importance == 0.8


def test_memory_item_serialization():
    item = MemoryItem(
        memory_type=MemoryType.WORKING,
        content="current context",
        success_count=3,
        failure_count=1,
    )
    data = item.model_dump()
    restored = MemoryItem.model_validate(data)
    assert restored.memory_type == MemoryType.WORKING
    assert restored.success_count == 3


# ── EvalTask / EvalResult ────────────────────────────────────────────


def test_eval_task_creation():
    task = EvalTask(
        instruction="Write a function that returns 42",
        expected_check="function returns 42",
        test_command="python -m pytest test_solution.py",
    )
    assert task.task_id.startswith("eval_")


def test_eval_result_creation():
    result = EvalResult(
        task_id="eval_abc",
        run_id="run_1",
        success=True,
        score=0.95,
        metrics={"steps": 3, "tokens": 500},
    )
    assert result.success
    assert result.score == 0.95


def test_eval_task_serialization():
    task = EvalTask(instruction="test", metadata={"difficulty": "easy"})
    data = task.model_dump()
    restored = EvalTask.model_validate(data)
    assert restored.metadata["difficulty"] == "easy"
