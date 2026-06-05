# EvoAgent

<p align="center">
  <strong>A research-friendly, modular LLM agent framework for tool use, trace-driven execution, self-evolving memory, workflow orchestration, code-agent experiments, and reproducible evaluation.</strong>
</p>

<p align="center">
  <a href="README.md">
    <img alt="English" src="https://img.shields.io/badge/docs-English-blue">
  </a>
  <a href="README_zh.md">
    <img alt="中文版本" src="https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87%E7%89%88%E6%9C%AC-red">
  </a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Status" src="https://img.shields.io/badge/status-research%20MVP-yellow">
  <img alt="Tests" src="https://img.shields.io/badge/tests-384%20passed-brightgreen">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

> **Current status:** EvoAgent is an experimental research MVP. It is designed for agent research, rapid prototyping, reproducible evaluation, and framework-level experimentation. It is **not yet production-hardened** for untrusted workloads.

---

## Table of Contents

- [Overview](#overview)
- [Why EvoAgent?](#why-evoagent)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Installation](#installation)
- [API Key Configuration](#api-key-configuration)
- [Quick Start](#quick-start)
- [CLI Usage](#cli-usage)
- [Configuration](#configuration)
- [Module Details](#module-details)
- [Examples](#examples)
- [Testing](#testing)
- [Safety Model](#safety-model)
- [Current Status](#current-status)
- [Roadmap](#roadmap)
- [Comparison with Existing Frameworks](#comparison-with-existing-frameworks)
- [Advantages of EvoAgent](#advantages-of-evoagent)
- [Known Limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)
- [Citation](#citation)

---

## Overview

**EvoAgent** is a modular LLM agent framework built around four principles:

1. **Inspectable execution** — every run can be traced through structured events.
2. **Composable components** — models, tools, memory, workflow nodes, skills, and evaluators are all replaceable.
3. **Research-friendly design** — mock-first tests, reproducible traces, and evaluation harnesses make it suitable for agent research.
4. **Memory evolution focus** — EvoAgent treats memory not as a passive chat history, but as an evolving system of task experience, procedures, reflections, and reusable knowledge.

EvoAgent currently provides a complete framework skeleton with working implementations for core schemas, model routing, tool execution, permissions, tracing, memory, RAG, workflow graphs, multi-agent protocols, code-agent experiments, skills, evaluation, and CLI commands.

The framework is designed for researchers and engineers who want to study questions such as:

- How should agents record and reuse past experience?
- How can failed executions be converted into reusable reflection memory?
- How can tool-use agents be evaluated in a reproducible way?
- How can code agents be debugged through traces and test feedback?
- How can different planning, memory, retrieval, and critique modules be swapped and compared?

---

## Why EvoAgent?

Many agent systems focus mainly on orchestration, multi-agent chat, workflow UI, or software engineering automation. EvoAgent focuses on a different but complementary goal:

> **Make agent behavior modular, traceable, testable, and experimentally reproducible.**

EvoAgent is especially suitable for:

- agent memory research;
- self-evolving memory and skill studies;
- tool-use and code-agent experiments;
- benchmark construction;
- controlled ablation studies;
- DeepSeek/OpenAI-compatible model routing;
- mock-first development without API keys;
- building custom agent frameworks rather than only using application-level wrappers.

EvoAgent does **not** aim to replace mature frameworks such as LangGraph, AutoGen, OpenHands, SWE-agent, or Dify. Instead, it provides a research-oriented framework where internal states, memory updates, tool calls, and evaluation traces are first-class objects.

---

## Key Features

### 1. Model-Agnostic LLM Layer

EvoAgent separates model access from agent logic.

Core components:

- `BaseLLMProvider`
- `OpenAICompatibleProvider`
- `DeepSeekProvider`
- `MockLLMProvider`
- `ProviderFactory`
- `ModelRouter`

Supported design:

- OpenAI-compatible APIs;
- DeepSeek API through environment variables;
- mock provider for offline tests;
- role-based model routing.

Role-based routing allows different models for different responsibilities:

```yaml
models:
  planner:
    provider: deepseek
    model: deepseek-reasoner
  executor:
    provider: deepseek
    model: deepseek-chat
  critic:
    provider: deepseek
    model: deepseek-reasoner
  summarizer:
    provider: deepseek
    model: deepseek-chat
```

This means the agent loop does not directly call a specific vendor API. Instead, all model calls go through a unified `LLMRequest` / `LLMResponse` interface.

---

### 2. Tool System

EvoAgent includes a structured tool system with Pydantic validation and unified results.

Core components:

- `BaseTool`
- `ToolRegistry`
- Pydantic input schemas
- OpenAI-compatible tool schema export
- unified `ToolCall` and `ToolResult`

Built-in tools include:

| Tool | Purpose |
|---|---|
| `read_file` | Read files inside the workspace |
| `write_file` | Write files with overwrite control |
| `edit_file` | Replace exact text spans safely |
| `list_directory` | Inspect workspace directories |
| `grep` | Search text patterns in files |
| `bash` | Run shell commands through permission checks |
| `python` | Run Python snippets or scripts |
| `git_status` | Inspect repository state |
| `git_diff` | Inspect code modifications |

Every tool call returns a structured result:

```python
ToolResult(
    call_id="...",
    name="read_file",
    success=True,
    output="...",
    error=None,
    metadata={...},
)
```

This makes tool behavior easy to log, test, replay, and evaluate.

---

### 3. Safety and Permissions

EvoAgent uses a safety-first permission layer for shell commands, file writes, Python execution, Git operations, and evaluation commands.

Core components:

- `PermissionPolicy`
- `PermissionRule`
- `Workspace`
- `LocalSandbox`
- `DockerSandbox` interface / experimental implementation

Permission modes:

| Mode | Behavior |
|---|---|
| `review` | Ask before risky or unknown operations |
| `auto` | Allow low-risk operations, ask or deny risky operations |
| `yolo` | Allow more operations, but deny rules are still enforced |

Rule priority:

```text
deny > ask > allow > fallback
```

Typical deny rules include:

- `rm -rf*`
- `sudo*`
- `git push*`
- `shutdown*`
- `reboot*`
- writes outside the workspace
- writes to system paths such as `/etc`, `/usr`, `/bin`

All file operations are constrained by the workspace boundary. Path traversal through `../` is rejected after path resolution.

---

### 4. Trace-Driven Runtime

EvoAgent treats execution traces as first-class artifacts.

Core components:

- `RuntimeState`
- `Event`
- `JSONLEventLogger`
- `TraceRecorder`
- `CheckpointManager`
- `DiffRecorder`

A typical run creates:

```text
.runs/
  run_20260604_xxxxxx/
    events.jsonl
    state.json
    final_result.json
    metadata.json
    patches/
      step_003.patch
    artifacts/
```

Common event types include:

- `run_started`
- `plan_created`
- `tool_call_started`
- `tool_call_finished`
- `shell_exec`
- `file_write`
- `memory_read`
- `memory_write`
- `critic_feedback`
- `checkpoint_created`
- `error`
- `final_result`

This design makes every agent run inspectable and suitable for debugging, benchmark analysis, and research logging.

---

### 5. Planner / Executor / Critic / Reflector Loop

EvoAgent implements an agent loop based on explicit planning and feedback.

```text
Task
  ↓
Planner
  ↓
Structured Plan
  ↓
Executor
  ↓
Observation / Tool Result
  ↓
Critic
  ├── passed → continue / finish
  └── failed → Reflector → revised plan
```

Core components:

- `Planner`
- `Executor`
- `Critic`
- `Reflector`
- `AgentLoop`
- `Agent`

A plan is represented as structured data rather than free text:

```json
{
  "task": "Inspect this repository",
  "risk_level": "low",
  "steps": [
    {
      "id": "step_1",
      "goal": "List top-level files",
      "action_type": "tool",
      "tool_name": "list_directory",
      "arguments": {"path": "."},
      "expected_result": "Repository structure is visible"
    }
  ]
}
```

Supported step types:

- `llm`
- `tool`
- `code`
- `ask_user`
- `finish`

Stop conditions include:

- task solved;
- max steps reached;
- max reflections reached;
- waiting for human input;
- unrecoverable error.

---

### 6. Five-Layer Memory System

EvoAgent includes a memory system designed for research on long-term and self-evolving agents.

Memory types:

| Memory Type | Purpose |
|---|---|
| `WorkingMemory` | Short-term state for the current task |
| `EpisodicMemory` | Past task experiences |
| `SemanticMemory` | Long-term facts and concepts |
| `ProceduralMemory` | Reusable procedures and skills |
| `ReflectionMemory` | Failure analysis and correction strategies |

Core components:

- `MemoryItem`
- `BaseMemoryStore`
- `SQLiteMemoryStore`
- `MemoryRetriever`
- `MemoryWriter`
- `MemoryConsolidator`
- `MemoryEvolution`

A memory item contains:

```python
MemoryItem(
    memory_type="reflection",
    content="When pytest fails with FileNotFoundError, inspect cwd and relative paths first.",
    importance=0.8,
    confidence=0.9,
    source_run_id="run_xxx",
    metadata={...},
)
```

Memory flow:

```text
Agent Run
  ↓
Trace / RuntimeState
  ↓
MemoryWriter
  ↓
Candidate Memories
  ↓
MemoryConsolidator
  ↓
MemoryEvolution
  ↓
MemoryStore
  ↓
Future Retrieval
```

The current retrieval implementation supports keyword and hybrid retrieval depending on configuration. Real embedding backends can be added through the retrieval interface.

---

### 7. RAG / Knowledge Base

EvoAgent provides a lightweight RAG pipeline for document-grounded agents.

Core components:

- `Document`
- `DocumentChunk`
- `TextLoader`
- `DirectoryLoader`
- `SimpleTextChunker`
- `KeywordIndex`
- `Retriever`
- `QueryEngine`
- `CitationBuilder`

RAG flow:

```text
Documents
  ↓
Loader
  ↓
Chunker
  ↓
Index
  ↓
Retriever
  ↓
QueryEngine
  ↓
AgentContext
```

The first implementation emphasizes simple, inspectable retrieval. Hybrid/vector retrieval is designed as an extension path.

---

### 8. Multi-Agent System

EvoAgent supports multi-agent coordination through role-based agents and protocols.

Built-in role agents:

- `PlannerAgent`
- `CoderAgent`
- `TesterAgent`
- `CriticAgent`
- `ResearcherAgent`
- `MemoryAgent`
- `ManagerAgent`

Protocols:

| Protocol | Description |
|---|---|
| `PipelineProtocol` | Agents work sequentially, e.g. Planner → Coder → Tester → Critic |
| `DebateProtocol` | Multiple agents propose answers and a judge selects or synthesizes |
| `SupervisorProtocol` | A manager assigns tasks to specialized agents |

All multi-agent runs share a common run ID and event log, making collaboration traceable.

---

### 9. Workflow Graph

EvoAgent includes a lightweight workflow engine inspired by graph-based agent runtimes.

Core components:

- `WorkflowNode`
- `WorkflowEdge`
- `WorkflowGraph`
- `WorkflowRuntime`
- `HumanInterrupt`

Supported features:

- node-based execution;
- conditional edges;
- checkpoint after nodes;
- resume interface;
- human interrupt for risky steps;
- integration with planner/executor/critic nodes.

Example workflow:

```text
START
  ↓
load_context
  ↓
retrieve_memory
  ↓
plan
  ↓
execute_step
  ↓
critic
  ├── pass → memory_write → END
  ├── fail → reflect → plan
  └── risky_action → human_interrupt
```

---

### 10. Code Agent

EvoAgent includes a code-agent module for software engineering experiments.

Core components:

- `RepoMap`
- `CodeSearch`
- `PatchManager`
- `TestRunner`
- `Diagnostics`
- `CodeAgent`

Code-agent loop:

```text
Task / Issue
  ↓
Repository Scan
  ↓
Relevant File Search
  ↓
Patch Planning
  ↓
File Edit / Patch Apply
  ↓
Test Runner
  ↓
Diagnostics
  ↓
Revise Patch
  ↓
Final Diff + Summary
```

The current implementation is experimental. It is suitable for toy repository debugging, patch-loop research, and benchmark construction. For untrusted repositories, use strict permissions and Docker sandboxing.

---

### 11. Skill System

EvoAgent supports reusable skills written as Markdown or YAML-style files.

A skill can use YAML front matter:

```markdown
---
name: debugging_python
description: How to debug Python pytest failures
triggers:
  - pytest failed
  - traceback
  - assertion error
---

1. Read the full traceback.
2. Locate the failing assertion.
3. Inspect the function under test.
4. Make a minimal patch.
5. Re-run the failing test first.
```

Core components:

- `Skill`
- `SkillLoader`
- `SkillRegistry`
- `SkillRetriever`
- `SkillUsageTracker`
- `SkillEvolution`

Skills can be retrieved based on task text, error messages, and context, then injected into the agent context.

---

### 12. Evaluation Harness

EvoAgent includes a benchmark and evaluation system for reproducible agent experiments.

Core components:

- `EvalTask`
- `EvalSuite`
- `EvalResult`
- `EvalHarness`
- `EvalReport`
- checkers
- metrics
- regression comparison

Supported checkers:

| Checker | Purpose |
|---|---|
| `ExactMatchChecker` | Exact output matching |
| `ContainsChecker` | Output contains expected text |
| `RegexChecker` | Regex-based validation |
| `TestCommandChecker` | Runs a test command through sandbox/permissions |

Common metrics:

- success rate;
- average score;
- runtime;
- number of steps;
- number of tool calls;
- number of LLM calls;
- memory hit rate;
- recovery success rate;
- cost estimate, if usage is available.

---

## Architecture

```text
User Task
  │
  ▼
Agent Runtime
  │
  ├── Context Builder
  │     ├── system prompt
  │     ├── conversation messages
  │     ├── retrieved memories
  │     ├── retrieved documents
  │     ├── available tools
  │     └── relevant skills
  │
  ├── Planner
  │     └── structured JSON plan
  │
  ├── Executor
  │     ├── LLM call
  │     ├── tool call
  │     ├── sandbox execution
  │     ├── file operation
  │     └── Python / shell / Git execution
  │
  ├── Critic
  │     ├── pass
  │     ├── needs revision
  │     └── needs more information
  │
  ├── Reflector
  │     └── revised plan / revised step
  │
  ├── Memory Writer
  │     └── episodic / semantic / procedural / reflection memory
  │
  └── Trace Recorder
        ├── events.jsonl
        ├── state.json
        ├── final_result.json
        └── patches/*.patch
```

The runtime is designed to be state-driven. `RuntimeState` is updated after each step, while `EventLogger` records the full execution history. This makes EvoAgent suitable for debugging, checkpointing, evaluation, and memory extraction.

---

## Installation

### From Source

```bash
git clone https://github.com/mingbo-yang/EvoAgent.git
cd EvoAgent
pip install -e .
```

### Development Installation

If the project defines a development extra:

```bash
pip install -e ".[dev]"
```

Otherwise install development dependencies manually according to `pyproject.toml`.

### Requirements

- Python 3.11+
- pip
- Git
- Docker, optional, only for Docker sandbox mode

---

## Quick Start

### Interactive Mode (v0.4.0)

```bash
evoagent
```

Opens a persistent interactive session with slash commands:

```
EvoAgent[default]> Inspect the CLI implementation.
EvoAgent[default]> /mode plan
EvoAgent[plan]> Refactor the memory subsystem.
EvoAgent[auto]> Fix all lint and test failures.
```

**Slash commands:**

| Command | Action |
|---------|--------|
| `/mode default` | Normal multi-turn mode with tools |
| `/mode plan` | Plan-first mode, requires approval to edit files |
| `/mode auto` | Autonomous mode, no per-action confirmation |
| `/plan` | Show current plan |
| `/sessions` | List saved sessions |
| `/resume latest` | Resume last session |
| `/new` | Start a new session |
| `/status` | Show session info |
| `/clear` | Clear conversation history |
| `/exit` | Save session and exit |

### One-Shot Mode (compatible)

```bash
evoagent run "List files in the current workspace" --mock
evoagent code "Fix the division-by-zero bug" --mock
```

### Mock Mode (no API key)

```bash
evoagent                    # auto-detects and uses mock if no key
evoagent run "hello" --mock
```

---

## API Key Configuration

EvoAgent reads secrets from environment variables.

### DeepSeek

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
```

### OpenAI-Compatible Providers

```bash
export OPENAI_API_KEY="your_openai_api_key"
```

### `.env` Example

Create `.env` locally if needed:

```env
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
```

Never commit `.env` or real API keys. Keep only `.env.example` in the repository.

---

## Quick Start

### 1. Initialize a Project

```bash
evoagent init
```

This creates project-level configuration and runtime directories, typically:

```text
evoagent.yaml
.evoagent/
.runs/
```

### 2. Run in Mock Mode

Mock mode requires no API key and is recommended for first-time testing.

```bash
evoagent run "List files in the current workspace" --mock
```

### 3. Run with DeepSeek

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
evoagent run "Read README.md and summarize this project"
```

### 4. Start an Interactive Chat

```bash
evoagent chat --mock
```

or with a real model:

```bash
evoagent chat
```

### 5. Use the Code Agent

```bash
evoagent code "Find the failing test and propose a minimal fix" --mock
```

For real code modifications, use a clean Git branch and inspect the diff before committing.

### 6. Run Evaluation

```bash
evoagent eval --suite examples/eval_toy_tasks.jsonl --mock
```

---

## CLI Usage

| Command | Description | Example |
|---|---|---|
| `evoagent init` | Initialize EvoAgent config and runtime directories | `evoagent init` |
| `evoagent config show` | Show resolved configuration | `evoagent config show` |
| `evoagent run` | Run a one-shot task | `evoagent run "Summarize README.md" --mock` |
| `evoagent chat` | Start interactive chat | `evoagent chat --mock` |
| `evoagent code` | Run code-agent workflow | `evoagent code "Fix failing tests" --mock` |
| `evoagent eval` | Run an evaluation suite | `evoagent eval --suite tasks.jsonl --mock` |
| `evoagent memory list` | List stored memories | `evoagent memory list --type episodic` |
| `evoagent memory search` | Search memories | `evoagent memory search "pytest failure"` |
| `evoagent trace list` | List recorded runs | `evoagent trace list` |
| `evoagent trace show` | Show run summary | `evoagent trace show <run_id>` |
| `evoagent trace events` | Show events for a run | `evoagent trace events <run_id> --type error` |

Use `--help` for command-specific options:

```bash
evoagent --help
evoagent run --help
evoagent code --help
evoagent eval --help
```

---

## Configuration

A typical `evoagent.yaml` looks like this:

```yaml
project:
  name: evoagent
  work_dir: "."

models:
  default:
    provider: deepseek
    model: deepseek-chat
    api_key_env: DEEPSEEK_API_KEY
  planner:
    provider: deepseek
    model: deepseek-reasoner
    api_key_env: DEEPSEEK_API_KEY
  executor:
    provider: deepseek
    model: deepseek-chat
    api_key_env: DEEPSEEK_API_KEY
  critic:
    provider: deepseek
    model: deepseek-reasoner
    api_key_env: DEEPSEEK_API_KEY

runtime:
  max_turns: 20
  max_reflections: 3
  checkpoint_enabled: true

permissions:
  mode: auto
  deny:
    - action: shell
      pattern: "rm -rf*"
      decision: deny
    - action: shell
      pattern: "sudo*"
      decision: deny
    - action: shell
      pattern: "git push*"
      decision: deny
  ask:
    - action: shell
      pattern: "*install*"
      decision: ask
  allow:
    - action: shell
      pattern: "echo*"
      decision: allow
    - action: shell
      pattern: "git status*"
      decision: allow
    - action: file_read
      pattern: "*"
      decision: allow

memory:
  enabled: true
  store: sqlite
  path: ".evoagent/memory.sqlite"
  top_k: 5

logging:
  traces_dir: ".runs"
  save_checkpoints: true
  save_diffs: true

retrieval:
  embedding_model: mock
  hybrid_alpha: 0.5
```

Configuration can be extended for custom models, tools, retrieval settings, sandbox backends, evaluation suites, and skills.

---

## Module Details

### Core

The `core` module defines shared runtime objects used across the framework.

Important objects:

- `Message`
- `ContentBlock`
- `RuntimeState`
- `AgentContext`
- `AgentResult`
- framework-level error types
- ID and timestamp utilities

Implementation details:

- Pydantic models for serialization and validation;
- JSON-compatible state persistence;
- shared schema objects to avoid inconsistent data formats;
- explicit runtime status values such as `created`, `running`, `waiting_for_human`, `succeeded`, `failed`, and `cancelled`.

---

### Models

The `models` module provides a vendor-independent LLM interface.

Important objects:

- `LLMRequest`
- `LLMResponse`
- `BaseLLMProvider`
- `OpenAICompatibleProvider`
- `DeepSeekProvider`
- `MockLLMProvider`
- `ModelRouter`

Implementation details:

- all provider calls use a unified request/response schema;
- role-based routing allows different models for planning, execution, critique, and summarization;
- `MockLLMProvider` enables deterministic tests without network calls;
- provider factory creates model providers from configuration.

---

### Tools

The `tools` module defines executable actions available to agents.

Implementation details:

- each tool has a Pydantic input schema;
- arguments are validated before execution;
- output is wrapped in `ToolResult`;
- schemas can be exported to OpenAI-compatible tool definitions;
- file operations are restricted to the workspace.

Custom tool example:

```python
from pydantic import BaseModel, Field
from evoagent.tools.base import BaseTool
from evoagent.tools.schema import ToolResult

class WordCountInput(BaseModel):
    text: str = Field(description="Text to count words from")

class WordCountTool(BaseTool):
    name = "word_count"
    description = "Count words in a text string."
    input_schema = WordCountInput
    risk_level = "low"

    async def run(self, text: str) -> ToolResult:
        count = len(text.split())
        return ToolResult(
            call_id="manual",
            name=self.name,
            success=True,
            output=str(count),
        )
```

---

### Sandbox and Permissions

The `sandbox` module controls where and how code or commands are executed.

Implementation details:

- `Workspace` resolves and validates paths;
- `PermissionPolicy` checks actions before execution;
- `LocalSandbox` executes commands locally with restrictions;
- `DockerSandbox` is designed for stronger isolation;
- all high-risk actions should pass through the same permission layer.

Typical dangerous commands are denied by default.

---

### Logging and Trace

The `logging` module records agent behavior.

Implementation details:

- JSONL events are append-only;
- each run has a unique `run_id`;
- checkpoints store serialized runtime state;
- diffs record file modifications;
- trace directories allow debugging and post-hoc evaluation.

Inspect recent runs:

```bash
evoagent trace list
evoagent trace show <run_id>
evoagent trace events <run_id>
```

---

### Planning

The `planning` module implements the agent decision loop.

Implementation details:

- planner asks the model for a structured plan;
- executor runs plan steps;
- critic evaluates whether each step succeeded;
- reflector revises failed steps;
- loop stops according to success, failure, max steps, or human intervention.

The module is designed so different planners or critics can be swapped in.

---

### Memory

The `memory` module is one of EvoAgent's core research components.

Implementation details:

- memories are stored as structured `MemoryItem` objects;
- SQLite is used as the default local memory backend;
- retrieval can use keyword or hybrid scoring;
- memory writer extracts reusable experience from runtime traces;
- consolidator merges duplicates and updates importance;
- evolution module adjusts memory priority based on success/failure signals.

This enables experiments on whether agents can improve across related tasks by reusing past traces.

---

### RAG

The `rag` module supports document-grounded context construction.

Implementation details:

- loaders convert files into `Document` objects;
- chunkers split documents into retrievable chunks;
- index stores chunk-level searchable data;
- retriever returns top-k relevant chunks;
- query engine formats retrieved context;
- citation builder preserves source metadata.

---

### Multi-Agent

The `multi_agent` module supports role-based collaboration.

Implementation details:

- each role agent has a name, role prompt, model role, tools, and optional memory;
- protocols define communication patterns;
- all messages and actions can be logged under a shared run ID;
- max-turn limits prevent infinite loops.

---

### Workflow

The `workflow` module organizes agent execution as a graph.

Implementation details:

- nodes transform `RuntimeState`;
- edges define control flow;
- conditional edges branch based on state;
- checkpoints support interruption and resume;
- human interrupt nodes can pause execution for approval.

---

### Code Agent

The `code` module provides the foundation for software-engineering agents.

Implementation details:

- `RepoMap` summarizes repository structure;
- `CodeSearch` locates text and symbols;
- `PatchManager` applies and records file modifications;
- `TestRunner` runs test commands;
- `Diagnostics` parses failures;
- `CodeAgent` coordinates patch-test-revise loops.

Recommended workflow:

```bash
git checkout -b agent-fix
evoagent code "Fix the failing pytest tests" --mock
git diff
pytest
```

Always inspect generated changes before committing.

---

### Skills

The `skills` module stores reusable instructions.

Implementation details:

- skills are loaded from Markdown/YAML;
- triggers are used for retrieval;
- usage tracker records skill success/failure;
- skill evolution adjusts priorities over time.

Example use cases:

- Python debugging;
- code review;
- test-driven fixes;
- memory reflection;
- paper-writing workflows.

---

### Evaluation

The `eval` module supports reproducible agent evaluation.

A JSONL task may look like:

```json
{"task_id":"readme_contains","instruction":"Summarize README.md","expected_check":{"type":"contains","value":"EvoAgent"}}
```

Run evaluation:

```bash
evoagent eval --suite examples/eval_toy_tasks.jsonl --mock
```

Reports can include success rate, runtime, steps, tool calls, LLM calls, and task-level errors.

---

## Examples

Run examples directly from the project root.

| Example | Description |
|---|---|
| `examples/basic_agent.py` | Minimal agent with mock model |
| `examples/tool_agent.py` | Built-in tool usage |
| `examples/memory_agent.py` | Add and retrieve memories |
| `examples/self_evolving_memory.py` | Generate memory from traces |
| `examples/rag_agent.py` | Document ingestion and retrieval |
| `examples/code_agent.py` | Code-agent workflow |
| `examples/multi_agent_debugging.py` | Pipeline multi-agent debugging |
| `examples/multi_agent_debate.py` | Debate protocol |
| `examples/skill_agent.py` | Skill loading and retrieval |
| `examples/workflow_agent.py` | Graph workflow execution |
| `examples/eval_toy.py` | Toy evaluation run |

Example:

```bash
python examples/basic_agent.py
python examples/tool_agent.py
python examples/memory_agent.py
python examples/eval_toy.py
```

---

## Testing

Run all tests:

```bash
python -m compileall evoagent
pytest
ruff check .
```

Current reported status:

```text
360 tests passed
```

Testing principles:

- mock-first;
- no real API key required;
- no network call in unit tests;
- deterministic model outputs through `MockLLMProvider`;
- module-level tests for core, models, tools, sandbox, planning, memory, RAG, workflow, code agent, skills, eval, and CLI.

---

## Safety Model

EvoAgent includes safety controls, but it should still be treated as an experimental research framework.

Safety mechanisms:

1. **Workspace boundary**
   - file operations are restricted to the workspace;
   - path traversal is rejected after path resolution.

2. **Permission policy**
   - high-risk actions pass through deny/ask/allow rules;
   - deny rules override all other rules.

3. **Sandbox abstraction**
   - local execution is available for development;
   - Docker execution is recommended for untrusted tasks.

4. **Secret handling**
   - API keys are read from environment variables;
   - `.env` should be ignored by Git;
   - tests use mock providers.

5. **Evaluation caution**
   - untrusted evaluation tasks may contain malicious test commands;
   - test commands should run through sandbox and permission policy.

Do not run EvoAgent with unrestricted permissions on untrusted repositories.

---

## Current Status

| Component | Status | Notes |
|---|---|---|
| Core Schema | Stable | Shared Pydantic schemas |
| Model Router | Stable | DeepSeek/OpenAI-compatible/Mock design |
| Tool System | Stable | Built-in tools and registry |
| Permission Policy | Stable | deny/ask/allow model |
| Local Sandbox | Experimental | Useful for development |
| Docker Sandbox | Experimental | Recommended for untrusted commands |
| Event Logging | Stable | JSONL event traces |
| Checkpointing | Experimental | Runtime state persistence |
| Planner Loop | Experimental | Depends on structured model output |
| Memory System | Feature-complete experimental | 5 memory types |
| RAG | Experimental | Keyword/hybrid retrieval depending on config |
| Multi-Agent | Experimental | Pipeline/Debate/Supervisor protocols |
| Workflow Graph | Experimental | Node/edge/checkpoint/human interrupt |
| Code Agent | Prototype/Experimental | Suitable for toy and research tasks |
| Skill System | Experimental | Markdown/YAML skills |
| Eval Harness | Stable experimental | JSONL tasks and reports |
| CLI | Experimental | Main workflows supported |

---

## Roadmap

### v0.1.1 — Safety and Reliability Hotfix

- unify BashTool and sandbox permission logic;
- sandbox all evaluation test commands;
- add event log pagination;
- fix configuration loading outside project root;
- replace system `grep` dependency with pure Python grep;
- improve fallback reflection.

### v0.2.0 — Core Capability Upgrade

- hybrid retrieval for memory and RAG;
- real embedding model integration;
- DockerSandbox hardening;
- LLM-powered code patch loop;
- toy code benchmark.

### v0.3.0 — Benchmark and Release Readiness

- benchmark suites for tool use, memory, RAG, and code tasks;
- Markdown/CSV/JSON reports;
- MkDocs or Sphinx documentation site;
- CI workflow;
- release readiness report.

### v0.4.0 — Advanced Agent Research

- SWE-bench Lite integration;
- structured multi-agent messages;
- trace viewer;
- stronger workflow resume;
- real vector database backends such as FAISS or Qdrant;
- memory ablation studies.

### v1.0.0 — Stable Research Framework

- stable public API;
- full documentation;
- benchmark results;
- plugin examples;
- community contribution guidelines.

---

## Comparison with Existing Frameworks

EvoAgent is not intended to replace mature frameworks. It focuses on research-friendly design, traceability, modular memory, mock-first testing, and reproducible experiments.

| Framework | Primary Focus |
|---|---|
| LangGraph | Durable graph-based agent workflows |
| AutoGen | Multi-agent conversation and collaboration |
| OpenHands | Software engineering agents |
| SWE-agent | Repository-level bug fixing benchmarks |
| Dify | LLM application platform and workflow UI |
| EvoAgent | Research-friendly modular agents, trace-driven execution, self-evolving memory, mock-first evaluation |

EvoAgent's main value is not that it has the largest feature set. Its value is that internal agent behavior is represented through typed states, event traces, memory items, tool results, and evaluation records.

---

## Advantages of EvoAgent

### 1. Research-Friendly by Design

EvoAgent is built for experimentation:

- modular components;
- mock-first tests;
- trace logging;
- evaluation harness;
- explicit memory objects;
- replaceable planners, critics, retrievers, tools, and model providers.

### 2. Trace-Driven Execution

Every run can produce:

- `events.jsonl`;
- `state.json`;
- `final_result.json`;
- patches and diffs;
- event-level records for tools, memory, LLM calls, and errors.

This makes it easier to debug agent failures and analyze behavior across benchmarks.

### 3. Memory Evolution Focus

EvoAgent treats memory as an evolving system:

- experience extraction;
- reflection memory;
- procedural memory;
- consolidation;
- importance and confidence updates;
- future retrieval.

This makes it a strong foundation for research on self-improving agents.

### 4. Safe-by-Default Direction

EvoAgent includes:

- permission policies;
- workspace boundary checks;
- deny rules;
- sandbox abstraction;
- mock-first testing;
- environment-based secret loading.

### 5. Model-Agnostic Design

The framework supports:

- DeepSeek;
- OpenAI-compatible APIs;
- mock providers;
- future LiteLLM or local model integration.

### 6. Extensible Interfaces

Users can add:

- custom model providers;
- custom tools;
- custom memory stores;
- custom workflow nodes;
- custom skills;
- custom evaluation checkers;
- custom retrievers.

### 7. Testing Quality

The project is designed around deterministic testing:

- no real network calls in unit tests;
- no real API key required;
- module-level isolation;
- CLI mock mode;
- reproducible toy evaluations.

---

## Known Limitations

EvoAgent is still experimental. Important limitations include:

1. **Retrieval quality**
   - keyword retrieval is limited;
   - hybrid retrieval may use mock embeddings unless configured with a real embedding backend.

2. **Sandboxing**
   - local sandbox is not strong isolation;
   - Docker sandbox should be used for untrusted tasks;
   - production-grade sandboxing requires further hardening.

3. **Code Agent maturity**
   - LLM patch generation is experimental;
   - rule-based fallback covers only limited bug patterns;
   - real repository repair still requires careful human inspection.

4. **Planning reliability**
   - planner depends on structured model output;
   - JSON repair and fallback plans are useful but not perfect.

5. **Multi-agent reliability**
   - current protocols are useful for experiments;
   - structured multi-agent messages are a future improvement.

6. **Production readiness**
   - EvoAgent is a research MVP;
   - do not run it with unrestricted permissions on untrusted inputs.

---

## Contributing

Contributions are welcome.

Recommended workflow:

```bash
git checkout -b feature/your-feature
python -m compileall evoagent
pytest
ruff check .
```

Contribution guidelines:

- add tests for every new module or tool;
- do not commit real API keys;
- update documentation for user-facing changes;
- keep APIs typed and serializable;
- prefer mock-first tests;
- ensure risky actions pass through `PermissionPolicy`.

If the repository includes `CONTRIBUTING.md`, please read it before opening a pull request.

---

## License

MIT License. See [LICENSE](LICENSE).

---

## Citation

If you use EvoAgent in research or experiments, you may cite it as:

```bibtex
@software{evoagent2026,
  title = {EvoAgent: A Research-Friendly Modular LLM Agent Framework},
  year = {2026},
  url = {https://github.com/mingbo-yang/EvoAgent}
}
```
