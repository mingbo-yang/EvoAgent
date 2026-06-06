<div align="center">

# EvoAgent

**An async, modular LLM agent framework for tool use, deterministic retrieval, multi-agent orchestration, and reproducible evaluation.**

[![English](https://img.shields.io/badge/docs-English-blue)](README.md)
[![中文](https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87-red)](README_zh.md)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-649%20passing-brightgreen)](#testing)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Style](https://img.shields.io/badge/lint-ruff-000000)](https://github.com/astral-sh/ruff)

</div>

---

EvoAgent is a Python framework for building autonomous LLM agents around a single, inspectable **ReAct loop**. It ships a broad built-in toolset, a deterministic-first code-retrieval stack, an MCP client, parallel sub-agents, real token-level streaming, crash-safe resume, and an OpenTelemetry-compatible tracing layer — all verified end-to-end against a live model API.

Every component (models, tools, memory, retrieval, workflow nodes, evaluators) is replaceable, and every run is traceable, making EvoAgent suitable for both production automation and agent research.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [CLI](#cli)
- [Built-in Tools](#built-in-tools)
- [Advanced Capabilities](#advanced-capabilities)
- [Testing](#testing)
- [Security Model](#security-model)
- [Project Layout](#project-layout)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Features

- **Canonical ReAct engine** — one read–decide–act loop with permission checks, context compaction, cost tracking, and a provider-safe message history (every `tool_calls` turn is answered).
- **Rich tool suite** — file editing, patching with undo, shell/Python execution, test running, glob, AST symbol outlines, deterministic code search, and web fetch/search with SSRF protection.
- **Deterministic-first retrieval** — symbol-aware code chunking + keyword ranking, with an optional persistent vector store and hashing embeddings layered on top.
- **MCP client** — connect to any [Model Context Protocol](https://modelcontextprotocol.io) server over stdio JSON-RPC and expose its tools to the agent.
- **Parallel sub-agents** — a `task` tool that fans out independent sub-tasks to fresh, isolated agents running concurrently.
- **Real streaming** — token-level SSE with streamed tool-call assembly (no dropped tool calls).
- **Interrupt & steering** — inject instructions, stop after the current tool, cancel a long-running command, or forbid edits to specific files, all mid-run.
- **Crash recovery** — atomic per-run checkpoints with `agent.resume(run_id)`.
- **Reliability & safety** — HTTP retry with `Retry-After` backoff, recursive secret redaction before any persistence, and a deny/ask/allow permission policy.
- **Observability** — dependency-optional OpenTelemetry tracing for run, LLM, and tool spans.
- **Evaluation** — a Docker-free SWE-bench-style harness that produces a patch and verifies it against the instance's tests on a clean checkout.

## Architecture

```
                          ┌──────────────────────────┐
        user task ───────▶│         Agent            │
                          │  (memory, checkpoints,   │
                          │   tracing, steering)     │
                          └────────────┬─────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │       ReAct Engine       │
                          │  loop · compaction · cost│
                          └──┬───────────┬───────────┘
                             │           │
              ┌──────────────▼──┐   ┌────▼─────────────┐
              │  Model Router    │   │  Tool Registry   │
              │ (OpenAI-compat / │   │ files · shell ·  │
              │   DeepSeek)      │   │ web · code_search│
              └────────┬─────────┘   │ · MCP · task     │
                       │             └────┬─────────────┘
                       │                  │
              ┌────────▼─────────┐  ┌─────▼──────────┐
              │ Permission Policy│  │  Retrieval +   │
              │  deny>ask>allow  │  │  Vector Store  │
              └──────────────────┘  └────────────────┘
```

## Installation

Requires **Python 3.11+**.

```bash
git clone https://github.com/mingbo-yang/EvoAgent.git
cd EvoAgent
pip install -e .

# optional extras
pip install -e ".[dev]"            # tests, linting
pip install -e ".[observability]"  # OpenTelemetry tracing
```

## Quick Start

Set an API key (DeepSeek or any OpenAI-compatible endpoint):

```bash
export DEEPSEEK_API_KEY="sk-..."
```

Run a one-shot task from Python:

```python
import asyncio
from pathlib import Path

from evoagent.core.agent import Agent
from evoagent.models.schema import ModelConfig
from evoagent.models.factory import ProviderFactory
from evoagent.models.router import ModelRouter
from evoagent.tools.builtin import create_builtin_registry


async def main():
    workspace = Path(".")
    provider = ProviderFactory.create(ModelConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
    ))
    router = ModelRouter(providers={"default": provider})
    registry = create_builtin_registry(workspace, auto_approve=True)

    agent = Agent(model_router=router, tool_registry=registry, workspace=workspace)
    result = await agent.run("Find the failing test in this project and fix it.")
    print(result.final_answer)


asyncio.run(main())
```

Or from the terminal:

```bash
evoagent run "Summarize the structure of this repository"
evoagent chat        # interactive session
```

## Configuration

EvoAgent reads configuration from `evoagent.yaml` and environment variables. Initialize a project with:

```bash
evoagent init
```

API keys are referenced by environment-variable name (`api_key_env`) and are **never** written to source, logs, traces, or session files.

| Variable | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `EVOAGENT_EGRESS_ALLOWLIST` | Optional comma-separated host allowlist for web tools |

## CLI

| Command | Description |
| --- | --- |
| `evoagent run <task>` | Run a one-shot agent task |
| `evoagent chat` | Start an interactive chat session |
| `evoagent code <task>` | Run the code agent on a software task |
| `evoagent eval <suite>` | Run an evaluation benchmark suite |
| `evoagent init` | Initialize EvoAgent in the current directory |
| `evoagent config` | Manage configuration |
| `evoagent memory` | Manage agent memories |
| `evoagent trace` | Inspect execution traces |

## Built-in Tools

| Category | Tools |
| --- | --- |
| **Files** | `read_file`, `write_file`, `edit_file`, `multi_edit`, `apply_patch`, `undo_last` |
| **Navigation** | `list_directory`, `grep`, `glob`, `outline`, `code_search` |
| **Execution** | `bash`, `python`, `run_tests` |
| **Version control** | `git_status`, `git_diff` |
| **Planning** | `write_todos`, `list_todos` |
| **Web** | `web_fetch`, `web_search` (SSRF-guarded) |
| **Orchestration** | `task` (parallel sub-agents), plus any MCP server tools |

## Advanced Capabilities

<details>
<summary><b>Interrupt &amp; steering</b></summary>

```python
from evoagent.core.steering import SteeringController

steering = SteeringController()
agent = Agent(..., steering=steering)

steering.inject("Also update the changelog")  # queue an instruction
steering.forbid_file("config.py")             # protect a file
steering.request_stop()                       # stop after the current tool
steering.cancel()                             # cancel an in-flight tool
```
</details>

<details>
<summary><b>Crash recovery &amp; resume</b></summary>

```python
agent = Agent(..., checkpoint_dir=".runs")
result = await agent.run("Long multi-step task")
# After a crash/restart:
result = await agent.resume(result.run_id, follow_up="Continue where you left off")
```
</details>

<details>
<summary><b>MCP client</b></summary>

```python
from evoagent.mcp import MCPClient, register_mcp_tools

client = MCPClient(["python", "my_mcp_server.py"])
await register_mcp_tools(registry, client)   # tools registered under mcp__*
```
</details>

<details>
<summary><b>Observability</b></summary>

```python
from evoagent.observability import Tracer, configure_otel

configure_otel("evoagent")           # if opentelemetry SDK is installed
tracer = Tracer(use_otel=True)
agent = Agent(..., tracer=tracer)
# tracer.spans_named("tool.execute") -> recorded spans
```
</details>

## Testing

```bash
pip install -e ".[dev]"
ruff check evoagent tests
pytest -q
```

The suite contains **649 tests**. Every major capability is additionally verified end-to-end against a live model API rather than mocks alone.

## Security Model

- **Permission policy** — deny > ask > allow, with safe defaults that block destructive shell commands and writes to system paths.
- **Workspace sandboxing** — file tools reject paths that escape the workspace; `glob` rejects `..` traversal.
- **Egress protection** — web tools block requests to private, loopback, link-local, and reserved addresses (re-checked on every redirect) and honor an optional host allowlist.
- **Secret redaction** — API keys, tokens, and credentials are recursively redacted before any logging, tracing, or session persistence.

> EvoAgent is research-grade software. Review the [Security Policy](SECURITY.md) before running it against untrusted inputs or in production.

## Project Layout

```
evoagent/
├── core/            # ReAct engine, agent, steering, checkpoints, cost, redaction
├── models/          # provider abstraction, OpenAI-compatible + DeepSeek, streaming
├── tools/           # built-in tool registry and implementations
├── sandbox/         # permission policy + egress (SSRF) protection
├── retrieval/       # code retriever, vector store, embeddings, keyword index
├── rag/             # document loading, chunking, query engine
├── mcp/             # Model Context Protocol stdio client
├── observability/   # OpenTelemetry-compatible tracing
├── conversation/    # sessions, runtime, context compaction
├── memory/          # experience/reflection memory store
├── planning/        # planner, executor, critic, reflector
├── workflow/        # workflow graph + runtime
├── multi_agent/     # multi-agent roles and protocols
├── eval/            # evaluation harness + SWE-bench-style runner
├── skills/          # reusable agent skills
├── code/            # code-agent helpers (repo map, patching, diagnostics)
├── logging/         # JSONL events, traces, diffs
├── config/          # configuration models and loading
└── cli/             # Typer CLI and terminal UI
```

## Roadmap

See [ROADMAP.md](ROADMAP.md). Native Anthropic and Gemini adapters are planned; today they are reachable via any OpenAI-compatible gateway.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md), run `ruff` and `pytest` before opening a pull request, and keep changes covered by tests.

## License

Released under the [MIT License](LICENSE).
