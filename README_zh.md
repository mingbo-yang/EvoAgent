# EvoAgent

<p align="center">
  <strong>一个面向研究的模块化 LLM Agent 框架，支持工具调用、可追踪执行、自进化记忆、工作流编排、代码 Agent 实验与可复现实验评测。</strong>
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

> **当前状态：** EvoAgent 是一个实验性的 research MVP。它面向 Agent 研究、快速原型开发、可复现实验评测与框架级实验设计，目前**尚未达到生产级安全加固**，不建议直接用于不可信工作负载。

---

## 目录

- [项目概览](#项目概览)
- [为什么选择 EvoAgent？](#为什么选择-evoagent)
- [核心特性](#核心特性)
- [整体架构](#整体架构)
- [安装方式](#安装方式)
- [API Key 配置](#api-key-配置)
- [快速开始](#快速开始)
- [CLI 使用说明](#cli-使用说明)
- [配置文件](#配置文件)
- [模块详解](#模块详解)
- [示例](#示例)
- [测试](#测试)
- [安全模型](#安全模型)
- [当前状态](#当前状态)
- [Roadmap](#roadmap)
- [与现有 Agent 框架的比较](#与现有-agent-框架的比较)
- [EvoAgent 的优势](#evoagent-的优势)
- [已知限制](#已知限制)
- [贡献指南](#贡献指南)
- [许可证](#许可证)
- [引用](#引用)

---

## 项目概览

**EvoAgent** 是一个模块化 LLM Agent 框架，围绕以下四个原则构建：

1. **可检查的执行过程**：每一次运行都可以通过结构化事件完整追踪。
2. **可组合的组件设计**：模型、工具、记忆、工作流节点、技能和评测器都可以替换。
3. **研究友好的框架设计**：mock-first 测试、可复现 trace 和评测框架使其适合 Agent 研究。
4. **记忆演化导向**：EvoAgent 不把 memory 视为被动聊天历史，而是将其建模为由任务经验、操作流程、反思和可复用知识组成的演化系统。

EvoAgent 当前提供了一套较完整的 Agent 框架骨架，并包含核心 schema、模型路由、工具执行、权限控制、trace、memory、RAG、workflow graph、multi-agent protocols、code-agent experiments、skills、evaluation 和 CLI 命令等实现。

该框架适合希望研究或工程化探索以下问题的开发者和研究者：

- Agent 应该如何记录并复用过往经验？
- 失败的执行过程如何转化为可复用的 reflection memory？
- 工具调用型 Agent 如何进行可复现实验评测？
- Code Agent 如何通过 trace 和测试反馈进行调试？
- 不同的 planning、memory、retrieval 和 critique 模块如何被替换和对比？

---

## 为什么选择 EvoAgent？

许多 Agent 系统主要关注 orchestration、多 Agent 对话、工作流 UI 或软件工程自动化。EvoAgent 的目标与它们互补：

> **让 Agent 行为模块化、可追踪、可测试、可复现实验。**

EvoAgent 尤其适合：

- Agent memory 研究；
- self-evolving memory 与 skill 研究；
- 工具调用和 Code Agent 实验；
- benchmark 构建；
- 可控消融实验；
- DeepSeek / OpenAI-compatible 模型路由；
- 无 API Key 的 mock-first 开发；
- 构建自定义 Agent 框架，而不只是使用应用层封装。

EvoAgent **并不旨在替代** LangGraph、AutoGen、OpenHands、SWE-agent 或 Dify 等成熟框架。它更强调研究导向：将内部状态、memory 更新、工具调用和评测 trace 作为一等公民。

---

## 核心特性

### 1. 模型无关的 LLM 层

EvoAgent 将模型访问与 Agent 逻辑解耦。

核心组件：

- `BaseLLMProvider`
- `OpenAICompatibleProvider`
- `DeepSeekProvider`
- `MockLLMProvider`
- `ProviderFactory`
- `ModelRouter`

支持的设计：

- OpenAI-compatible API；
- 通过环境变量接入 DeepSeek API；
- 用于离线测试的 mock provider；
- 基于角色的模型路由。

Role-based routing 允许不同角色使用不同模型：

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

这意味着 Agent loop 不会直接调用某个具体厂商 API，而是统一通过 `LLMRequest` / `LLMResponse` 接口完成模型调用。

---

### 2. 工具系统

EvoAgent 提供结构化工具系统，支持 Pydantic 参数校验和统一结果格式。

核心组件：

- `BaseTool`
- `ToolRegistry`
- Pydantic input schemas
- OpenAI-compatible tool schema export
- 统一的 `ToolCall` 与 `ToolResult`

内置工具包括：

| 工具 | 作用 |
|---|---|
| `read_file` | 读取 workspace 内文件 |
| `write_file` | 写入文件，并支持 overwrite 控制 |
| `edit_file` | 安全替换精确文本片段 |
| `list_directory` | 查看 workspace 目录结构 |
| `grep` | 在文件中搜索文本模式 |
| `bash` | 通过权限检查运行 shell 命令 |
| `python` | 运行 Python 代码片段或脚本 |
| `git_status` | 查看 Git 仓库状态 |
| `git_diff` | 查看代码修改 diff |

每个工具调用都会返回结构化结果：

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

因此，工具行为可以被日志记录、测试、回放和评测。

---

### 3. 安全与权限

EvoAgent 为 shell 命令、文件写入、Python 执行、Git 操作和评测命令提供安全优先的权限层。

核心组件：

- `PermissionPolicy`
- `PermissionRule`
- `Workspace`
- `LocalSandbox`
- `DockerSandbox` interface / experimental implementation

权限模式：

| 模式 | 行为 |
|---|---|
| `review` | 对风险或未知操作进行确认 |
| `auto` | 自动允许低风险操作，对高风险操作询问或拒绝 |
| `yolo` | 允许更多操作，但 deny 规则始终生效 |

规则优先级：

```text
deny > ask > allow > fallback
```

典型 deny 规则包括：

- `rm -rf*`
- `sudo*`
- `git push*`
- `shutdown*`
- `reboot*`
- workspace 外写入
- 写入 `/etc`、`/usr`、`/bin` 等系统路径

所有文件操作都受 workspace 边界约束。通过 `../` 进行路径穿越会在路径解析后被拒绝。

---

### 4. Trace-Driven Runtime

EvoAgent 将执行 trace 作为核心产物。

核心组件：

- `RuntimeState`
- `Event`
- `JSONLEventLogger`
- `TraceRecorder`
- `CheckpointManager`
- `DiffRecorder`

一次典型运行会生成：

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

常见事件类型包括：

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

该设计使每次 Agent 运行都可检查，适合调试、benchmark 分析和研究日志记录。

---

### 5. Planner / Executor / Critic / Reflector 闭环

EvoAgent 实现了基于显式规划和反馈的 Agent loop。

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

核心组件：

- `Planner`
- `Executor`
- `Critic`
- `Reflector`
- `AgentLoop`
- `Agent`

Plan 被表示为结构化数据，而不是自由文本：

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

支持的 step 类型：

- `llm`
- `tool`
- `code`
- `ask_user`
- `finish`

停止条件包括：

- 任务完成；
- 达到最大步数；
- 达到最大 reflection 次数；
- 等待人工输入；
- 不可恢复错误。

---

### 6. 五层记忆系统

EvoAgent 提供一个面向长期 Agent 与自进化 Agent 研究的 memory system。

Memory 类型：

| Memory Type | 作用 |
|---|---|
| `WorkingMemory` | 当前任务的短期状态 |
| `EpisodicMemory` | 历史任务经验 |
| `SemanticMemory` | 长期事实与概念 |
| `ProceduralMemory` | 可复用流程与技能 |
| `ReflectionMemory` | 失败分析与修正策略 |

核心组件：

- `MemoryItem`
- `BaseMemoryStore`
- `SQLiteMemoryStore`
- `MemoryRetriever`
- `MemoryWriter`
- `MemoryConsolidator`
- `MemoryEvolution`

Memory item 示例：

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

Memory flow：

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

当前检索实现会根据配置支持 keyword 或 hybrid retrieval。真实 embedding backend 可以通过 retrieval interface 继续扩展。

---

### 7. RAG / Knowledge Base

EvoAgent 提供轻量级 RAG pipeline，用于构建基于文档的 Agent context。

核心组件：

- `Document`
- `DocumentChunk`
- `TextLoader`
- `DirectoryLoader`
- `SimpleTextChunker`
- `KeywordIndex`
- `Retriever`
- `QueryEngine`
- `CitationBuilder`

RAG flow：

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

第一版实现强调简单、可检查的 retrieval。Hybrid/vector retrieval 被设计为后续扩展路径。

---

### 8. Multi-Agent System

EvoAgent 通过 role-based agents 和 protocols 支持多 Agent 协作。

内置角色 Agent：

- `PlannerAgent`
- `CoderAgent`
- `TesterAgent`
- `CriticAgent`
- `ResearcherAgent`
- `MemoryAgent`
- `ManagerAgent`

Protocols：

| Protocol | 说明 |
|---|---|
| `PipelineProtocol` | 多个 Agent 顺序工作，如 Planner → Coder → Tester → Critic |
| `DebateProtocol` | 多个 Agent 给出方案，再由 judge 选择或综合 |
| `SupervisorProtocol` | manager 将任务分配给专门 Agent |

所有 multi-agent runs 共享同一个 run ID 和 event log，因此协作过程可以被追踪。

---

### 9. Workflow Graph

EvoAgent 包含一个轻量级 workflow engine，灵感来自 graph-based agent runtimes。

核心组件：

- `WorkflowNode`
- `WorkflowEdge`
- `WorkflowGraph`
- `WorkflowRuntime`
- `HumanInterrupt`

支持能力：

- 基于节点的执行；
- 条件边；
- 节点后 checkpoint；
- resume interface；
- 风险步骤 human interrupt；
- 与 planner / executor / critic nodes 集成。

示例 workflow：

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

EvoAgent 包含用于软件工程实验的 code-agent module。

核心组件：

- `RepoMap`
- `CodeSearch`
- `PatchManager`
- `TestRunner`
- `Diagnostics`
- `CodeAgent`

Code-agent loop：

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

当前实现仍处于实验阶段，适合 toy repository debugging、patch-loop 研究与 benchmark 构建。对于不可信仓库，应使用严格权限和 Docker sandbox。

---

### 11. Skill System

EvoAgent 支持用 Markdown 或 YAML-style 文件编写可复用 skill。

Skill 可以使用 YAML front matter：

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

核心组件：

- `Skill`
- `SkillLoader`
- `SkillRegistry`
- `SkillRetriever`
- `SkillUsageTracker`
- `SkillEvolution`

Skill 可以根据 task text、error message 和 context 被检索，并注入 Agent context。

---

### 12. Evaluation Harness

EvoAgent 包含 benchmark 与 evaluation system，用于可复现 Agent 实验。

核心组件：

- `EvalTask`
- `EvalSuite`
- `EvalResult`
- `EvalHarness`
- `EvalReport`
- checkers
- metrics
- regression comparison

支持的 checkers：

| Checker | 作用 |
|---|---|
| `ExactMatchChecker` | 精确输出匹配 |
| `ContainsChecker` | 输出包含指定文本 |
| `RegexChecker` | 基于正则的验证 |
| `TestCommandChecker` | 通过 sandbox/permissions 运行测试命令 |

常见 metrics：

- success rate；
- average score；
- runtime；
- steps 数量；
- tool calls 数量；
- LLM calls 数量；
- memory hit rate；
- recovery success rate；
- cost estimate，如果 usage 可用。

---

## 整体架构

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

Runtime 采用 state-driven 设计。`RuntimeState` 会在每一步后更新，`EventLogger` 则记录完整执行历史。这使 EvoAgent 适用于调试、checkpoint、evaluation 和 memory extraction。

---

## 安装方式

### 从源码安装

```bash
git clone https://github.com/mingbo-yang/EvoAgent.git
cd EvoAgent
pip install -e .
```

### 开发模式安装

如果项目定义了 development extra：

```bash
pip install -e ".[dev]"
```

否则请根据 `pyproject.toml` 手动安装开发依赖。

### 环境要求

- Python 3.11+
- pip
- Git
- Docker，可选，仅 Docker sandbox 模式需要

---

## 快速开始

### 交互模式（v0.4.0 新增）

```bash
evoagent
```

直接进入持久交互会话，支持斜杠命令：

```
EvoAgent[default]> 检查 CLI 实现的代码
EvoAgent[default]> /mode plan
EvoAgent[plan]> 重构 memory 子系统
EvoAgent[auto]> 修复所有 lint 和测试失败
```

**斜杠命令：**

| 命令 | 功能 |
|------|------|
| `/mode default` | 普通多轮模式，带工具调用 |
| `/mode plan` | 计划优先模式，修改文件前需审批 |
| `/mode auto` | 自主模式，无需逐次确认 |
| `/plan` | 显示当前计划 |
| `/sessions` | 列出已保存会话 |
| `/resume latest` | 恢复最近会话 |
| `/new` | 创建新会话 |
| `/status` | 显示会话信息 |
| `/clear` | 清空对话历史 |
| `/exit` | 保存并退出 |

### 单次模式（兼容）

```bash
evoagent run "列出当前目录文件" --mock
evoagent code "修复除零 bug" --mock
```

### Mock 模式（无需 API key）

```bash
evoagent                    # 无 key 时自动使用 mock
evoagent run "hello" --mock
```

---

## API Key 配置

EvoAgent 从环境变量读取 secrets。

### DeepSeek

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
```

### OpenAI-Compatible Providers

```bash
export OPENAI_API_KEY="your_openai_api_key"
```

### `.env` 示例

如有需要，可以在本地创建 `.env`：

```env
DEEPSEEK_API_KEY=
OPENAI_API_KEY=
```

不要提交 `.env` 或真实 API keys。仓库中只保留 `.env.example`。

---

## 快速开始

### 1. 初始化项目

```bash
evoagent init
```

这会创建项目级配置和运行目录，通常包括：

```text
evoagent.yaml
.evoagent/
.runs/
```

### 2. 使用 Mock Mode 运行

Mock mode 不需要 API key，推荐首次测试使用。

```bash
evoagent run "List files in the current workspace" --mock
```

### 3. 使用 DeepSeek 运行

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
evoagent run "Read README.md and summarize this project"
```

### 4. 启动交互式 Chat

```bash
evoagent chat --mock
```

或使用真实模型：

```bash
evoagent chat
```

### 5. 使用 Code Agent

```bash
evoagent code "Find the failing test and propose a minimal fix" --mock
```

对于真实代码修改，建议在干净的 Git 分支上运行，并在提交前仔细检查 diff。

### 6. 运行 Evaluation

```bash
evoagent eval --suite examples/eval_toy_tasks.jsonl --mock
```

---

## CLI 使用说明

| Command | 说明 | 示例 |
|---|---|---|
| `evoagent init` | 初始化 EvoAgent 配置和运行目录 | `evoagent init` |
| `evoagent config show` | 显示解析后的配置 | `evoagent config show` |
| `evoagent run` | 执行一次性任务 | `evoagent run "Summarize README.md" --mock` |
| `evoagent chat` | 启动交互式聊天 | `evoagent chat --mock` |
| `evoagent code` | 运行 Code Agent workflow | `evoagent code "Fix failing tests" --mock` |
| `evoagent eval` | 运行 evaluation suite | `evoagent eval --suite tasks.jsonl --mock` |
| `evoagent memory list` | 列出已存储 memory | `evoagent memory list --type episodic` |
| `evoagent memory search` | 搜索 memory | `evoagent memory search "pytest failure"` |
| `evoagent trace list` | 列出已记录 runs | `evoagent trace list` |
| `evoagent trace show` | 查看 run 摘要 | `evoagent trace show <run_id>` |
| `evoagent trace events` | 查看某次 run 的 events | `evoagent trace events <run_id> --type error` |

使用 `--help` 查看命令选项：

```bash
evoagent --help
evoagent run --help
evoagent code --help
evoagent eval --help
```

---

## 配置文件

典型 `evoagent.yaml` 如下：

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

配置可以扩展到自定义模型、工具、检索设置、sandbox backend、evaluation suites 和 skills。

---

## 模块详解

### Core

`core` 模块定义整个框架共享的 runtime objects。

重要对象：

- `Message`
- `ContentBlock`
- `RuntimeState`
- `AgentContext`
- `AgentResult`
- 框架级 error types
- ID 与 timestamp 工具

实现方式：

- 使用 Pydantic models 进行序列化和校验；
- 支持 JSON-compatible state persistence；
- 共享 schema 避免模块间数据格式不一致；
- 显式 runtime status，例如 `created`、`running`、`waiting_for_human`、`succeeded`、`failed`、`cancelled`。

---

### Models

`models` 模块提供 vendor-independent LLM interface。

重要对象：

- `LLMRequest`
- `LLMResponse`
- `BaseLLMProvider`
- `OpenAICompatibleProvider`
- `DeepSeekProvider`
- `MockLLMProvider`
- `ModelRouter`

实现方式：

- 所有 provider calls 使用统一 request/response schema；
- 基于 role 的 routing 支持不同模型分别负责 planning、execution、critique 和 summarization；
- `MockLLMProvider` 支持无需网络的确定性测试；
- provider factory 从配置创建 model provider。

---

### Tools

`tools` 模块定义 Agent 可执行动作。

实现方式：

- 每个 tool 都有 Pydantic input schema；
- 执行前进行参数校验；
- 输出统一封装为 `ToolResult`；
- schema 可导出为 OpenAI-compatible tool definitions；
- 文件操作受 workspace 约束。

自定义工具示例：

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

`sandbox` 模块控制代码或命令在何处以及如何执行。

实现方式：

- `Workspace` 负责路径解析与校验；
- `PermissionPolicy` 在执行前检查 action；
- `LocalSandbox` 在本地受限执行命令；
- `DockerSandbox` 用于更强隔离；
- 所有高风险操作都应经过同一权限层。

典型危险命令默认被拒绝。

---

### Logging and Trace

`logging` 模块记录 Agent 行为。

实现方式：

- JSONL events 采用 append-only；
- 每次 run 拥有唯一 `run_id`；
- checkpoint 保存序列化 runtime state；
- diff 记录文件修改；
- trace directory 支持 debugging 和 post-hoc evaluation。

查看最近 runs：

```bash
evoagent trace list
evoagent trace show <run_id>
evoagent trace events <run_id>
```

---

### Planning

`planning` 模块实现 Agent decision loop。

实现方式：

- planner 请求模型生成结构化 plan；
- executor 执行 plan steps；
- critic 判断每一步是否成功；
- reflector 修订失败 step；
- loop 根据成功、失败、最大步数或人工介入停止。

该模块支持替换不同 planner 或 critic。

---

### Memory

`memory` 模块是 EvoAgent 的核心研究组件之一。

实现方式：

- memory 被存储为结构化 `MemoryItem` objects；
- 默认本地 memory backend 为 SQLite；
- retrieval 可使用 keyword 或 hybrid scoring；
- memory writer 从 runtime traces 中提取可复用经验；
- consolidator 合并重复 memory 并更新 importance；
- evolution module 根据成功/失败信号调整 memory priority。

这使我们可以研究 Agent 是否能通过复用过往 traces 在相关任务上逐步提升。

---

### RAG

`rag` 模块支持 document-grounded context construction。

实现方式：

- loaders 将文件转化为 `Document` objects；
- chunkers 将文档切分为可检索 chunks；
- index 保存 chunk-level searchable data；
- retriever 返回 top-k relevant chunks；
- query engine 格式化 retrieved context；
- citation builder 保留 source metadata。

---

### Multi-Agent

`multi_agent` 模块支持 role-based collaboration。

实现方式：

- 每个 role agent 拥有 name、role prompt、model role、tools 和可选 memory；
- protocols 定义通信模式；
- 所有 messages 和 actions 都可在共享 run ID 下记录；
- max-turn limits 防止无限循环。

---

### Workflow

`workflow` 模块将 Agent 执行组织为 graph。

实现方式：

- nodes 转换 `RuntimeState`；
- edges 定义控制流；
- conditional edges 根据 state 进行分支；
- checkpoints 支持中断和恢复；
- human interrupt nodes 可以暂停执行以等待审批。

---

### Code Agent

`code` 模块为软件工程 Agent 提供基础能力。

实现方式：

- `RepoMap` 总结仓库结构；
- `CodeSearch` 定位文本和 symbols；
- `PatchManager` 应用并记录文件修改；
- `TestRunner` 运行测试命令；
- `Diagnostics` 解析失败信息；
- `CodeAgent` 协调 patch-test-revise loop。

推荐工作流：

```bash
git checkout -b agent-fix
evoagent code "Fix the failing pytest tests" --mock
git diff
pytest
```

提交前务必检查生成的修改。

---

### Skills

`skills` 模块存储可复用指令。

实现方式：

- skills 从 Markdown/YAML 加载；
- triggers 用于检索；
- usage tracker 记录 skill 成功/失败；
- skill evolution 随时间调整 priority。

典型用途：

- Python debugging；
- code review；
- test-driven fixes；
- memory reflection；
- paper-writing workflows。

---

### Evaluation

`eval` 模块支持可复现 Agent evaluation。

JSONL task 示例：

```json
{"task_id":"readme_contains","instruction":"Summarize README.md","expected_check":{"type":"contains","value":"EvoAgent"}}
```

运行 evaluation：

```bash
evoagent eval --suite examples/eval_toy_tasks.jsonl --mock
```

Report 可以包含 success rate、runtime、steps、tool calls、LLM calls 和 task-level errors。

---

## 示例

从项目根目录直接运行 examples。

| Example | 说明 |
|---|---|
| `examples/basic_agent.py` | 使用 mock model 的最小 Agent |
| `examples/tool_agent.py` | 内置工具调用 |
| `examples/memory_agent.py` | 添加和检索 memory |
| `examples/self_evolving_memory.py` | 从 trace 生成 memory |
| `examples/rag_agent.py` | 文档摄取与检索 |
| `examples/code_agent.py` | Code-agent workflow |
| `examples/multi_agent_debugging.py` | Pipeline multi-agent debugging |
| `examples/multi_agent_debate.py` | Debate protocol |
| `examples/skill_agent.py` | Skill 加载与检索 |
| `examples/workflow_agent.py` | Graph workflow execution |
| `examples/eval_toy.py` | Toy evaluation run |

示例命令：

```bash
python examples/basic_agent.py
python examples/tool_agent.py
python examples/memory_agent.py
python examples/eval_toy.py
```

---

## 测试

运行全部测试：

```bash
python -m compileall evoagent
pytest
ruff check .
```

当前报告状态：

```text
360 tests passed
```

测试原则：

- mock-first；
- 不需要真实 API key；
- unit tests 中不进行真实网络调用；
- 通过 `MockLLMProvider` 实现确定性模型输出；
- 对 core、models、tools、sandbox、planning、memory、RAG、workflow、code agent、skills、eval 和 CLI 做模块级测试。

---

## 安全模型

EvoAgent 包含安全控制，但仍应被视为实验性研究框架。

安全机制：

1. **Workspace boundary**
   - 文件操作被限制在 workspace 内；
   - 路径解析后拒绝 path traversal。

2. **Permission policy**
   - 高风险操作经过 deny/ask/allow 规则；
   - deny 规则优先级最高。

3. **Sandbox abstraction**
   - local execution 适用于开发；
   - 对不可信任务建议使用 Docker execution。

4. **Secret handling**
   - API keys 从环境变量读取；
   - `.env` 应被 Git 忽略；
   - tests 使用 mock providers。

5. **Evaluation caution**
   - 不可信 evaluation tasks 可能包含恶意 test commands；
   - test commands 应通过 sandbox 和 permission policy 运行。

不要在不可信仓库上以无限制权限运行 EvoAgent。

---

## 当前状态

| Component | Status | Notes |
|---|---|---|
| Core Schema | Stable | 共享 Pydantic schemas |
| Model Router | Stable | DeepSeek/OpenAI-compatible/Mock 设计 |
| Tool System | Stable | 内置 tools 和 registry |
| Permission Policy | Stable | deny/ask/allow 模型 |
| Local Sandbox | Experimental | 适合开发环境 |
| Docker Sandbox | Experimental | 推荐用于不可信命令 |
| Event Logging | Stable | JSONL event traces |
| Checkpointing | Experimental | Runtime state persistence |
| Planner Loop | Experimental | 依赖结构化模型输出 |
| Memory System | Feature-complete experimental | 5 类 memory |
| RAG | Experimental | 根据配置支持 keyword/hybrid retrieval |
| Multi-Agent | Experimental | Pipeline/Debate/Supervisor protocols |
| Workflow Graph | Experimental | Node/edge/checkpoint/human interrupt |
| Code Agent | Prototype/Experimental | 适合 toy 和 research tasks |
| Skill System | Experimental | Markdown/YAML skills |
| Eval Harness | Stable experimental | JSONL tasks 和 reports |
| CLI | Experimental | 支持主要 workflow |

---

## Roadmap

### v0.1.1 — Safety and Reliability Hotfix

- 统一 BashTool 与 sandbox permission logic；
- 对所有 evaluation test commands 进行 sandbox 化；
- 增加 event log pagination；
- 修复非项目根目录下的配置加载；
- 用纯 Python grep 替代系统 `grep` 依赖；
- 增强 fallback reflection。

### v0.2.0 — Core Capability Upgrade

- memory 和 RAG 的 hybrid retrieval；
- 真实 embedding model integration；
- DockerSandbox 加固；
- LLM-powered code patch loop；
- toy code benchmark。

### v0.3.0 — Benchmark and Release Readiness

- tool use、memory、RAG 和 code tasks 的 benchmark suites；
- Markdown/CSV/JSON reports；
- MkDocs 或 Sphinx 文档网站；
- CI workflow；
- release readiness report。

### v0.4.0 — Advanced Agent Research

- SWE-bench Lite 集成；
- structured multi-agent messages；
- trace viewer；
- 更强的 workflow resume；
- FAISS 或 Qdrant 等真实 vector database backends；
- memory ablation studies。

### v1.0.0 — Stable Research Framework

- 稳定 public API；
- 完整文档；
- benchmark results；
- plugin examples；
- community contribution guidelines。

---

## 与现有 Agent 框架的比较

EvoAgent 并不旨在替代成熟框架。它关注 research-friendly design、traceability、modular memory、mock-first testing 和 reproducible experiments。

| Framework | Primary Focus |
|---|---|
| LangGraph | Durable graph-based agent workflows |
| AutoGen | Multi-agent conversation and collaboration |
| OpenHands | Software engineering agents |
| SWE-agent | Repository-level bug fixing benchmarks |
| Dify | LLM application platform and workflow UI |
| EvoAgent | Research-friendly modular agents, trace-driven execution, self-evolving memory, mock-first evaluation |

EvoAgent 的价值不在于拥有最多功能，而在于通过 typed states、event traces、memory items、tool results 和 evaluation records 显式表示 Agent 的内部行为。

---

## EvoAgent 的优势

### 1. Research-Friendly by Design

EvoAgent 为实验而生：

- 模块化组件；
- mock-first tests；
- trace logging；
- evaluation harness；
- 显式 memory objects；
- 可替换 planners、critics、retrievers、tools 和 model providers。

### 2. Trace-Driven Execution

每次 run 都可以生成：

- `events.jsonl`；
- `state.json`；
- `final_result.json`；
- patches 和 diffs；
- tools、memory、LLM calls 和 errors 的 event-level records。

这更便于调试 Agent 失败并分析 benchmark 行为。

### 3. Memory Evolution Focus

EvoAgent 将 memory 视为演化系统：

- experience extraction；
- reflection memory；
- procedural memory；
- consolidation；
- importance 和 confidence updates；
- future retrieval。

因此，它非常适合作为 self-improving agents 研究的基础。

### 4. Safe-by-Default Direction

EvoAgent 包含：

- permission policies；
- workspace boundary checks；
- deny rules；
- sandbox abstraction；
- mock-first testing；
- 基于环境变量的 secret loading。

### 5. Model-Agnostic Design

框架支持：

- DeepSeek；
- OpenAI-compatible APIs；
- mock providers；
- 后续 LiteLLM 或本地模型集成。

### 6. Extensible Interfaces

用户可以添加：

- custom model providers；
- custom tools；
- custom memory stores；
- custom workflow nodes；
- custom skills；
- custom evaluation checkers；
- custom retrievers。

### 7. Testing Quality

项目围绕确定性测试设计：

- unit tests 中不进行真实网络调用；
- 不需要真实 API key；
- 模块级隔离；
- CLI mock mode；
- 可复现 toy evaluations。

---

## 已知限制

EvoAgent 仍处于实验阶段，重要限制包括：

1. **Retrieval quality**
   - keyword retrieval 能力有限；
   - hybrid retrieval 如果没有配置真实 embedding backend，可能使用 mock embeddings。

2. **Sandboxing**
   - local sandbox 不是强隔离；
   - 不可信任务应使用 Docker sandbox；
   - production-grade sandboxing 仍需要进一步加固。

3. **Code Agent maturity**
   - LLM patch generation 仍为实验性能力；
   - rule-based fallback 只覆盖有限 bug patterns；
   - 真实仓库修复仍需要人工检查。

4. **Planning reliability**
   - planner 依赖结构化模型输出；
   - JSON repair 和 fallback plan 有用但并不完美。

5. **Multi-agent reliability**
   - 当前 protocols 适合实验；
   - structured multi-agent messages 是未来改进方向。

6. **Production readiness**
   - EvoAgent 是 research MVP；
   - 不要在不可信输入上以无限制权限运行。

---

## 贡献指南

欢迎贡献。

推荐工作流：

```bash
git checkout -b feature/your-feature
python -m compileall evoagent
pytest
ruff check .
```

贡献规范：

- 每个新模块或工具都要添加测试；
- 不要提交真实 API keys；
- 面向用户的修改需要更新文档；
- 保持 API typed and serializable；
- 优先使用 mock-first tests；
- 确保风险操作经过 `PermissionPolicy`。

如果仓库包含 `CONTRIBUTING.md`，请在提交 PR 前阅读。

---

## 许可证

MIT License。详见 [LICENSE](LICENSE)。

---

## 引用

如果你在研究或实验中使用 EvoAgent，可以按如下方式引用：

```bibtex
@software{evoagent2026,
  title = {EvoAgent: A Research-Friendly Modular LLM Agent Framework},
  year = {2026},
  url = {https://github.com/mingbo-yang/EvoAgent}
}
```
