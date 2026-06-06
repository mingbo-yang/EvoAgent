<div align="center">

# EvoAgent

**一个异步、模块化的大语言模型 Agent 框架，面向工具调用、确定性检索、多智能体编排与可复现评测。**

[![English](https://img.shields.io/badge/docs-English-blue)](README.md)
[![中文](https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87-red)](README_zh.md)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-649%20passing-brightgreen)](#测试)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Style](https://img.shields.io/badge/lint-ruff-000000)](https://github.com/astral-sh/ruff)

</div>

---

EvoAgent 是一个 Python 框架，围绕单一、可观测的 **ReAct 循环** 构建自主大模型 Agent。它内置了丰富的工具集、确定性优先的代码检索栈、MCP 客户端、并行子代理、真实的 token 级流式输出、崩溃可恢复的断点续跑，以及与 OpenTelemetry 兼容的链路追踪层——所有能力均已通过真实模型 API 端到端验证。

每个组件（模型、工具、记忆、检索、工作流节点、评测器）皆可替换，每一次运行皆可追踪，使 EvoAgent 同时适用于生产自动化与 Agent 研究。

## 目录

- [核心特性](#核心特性)
- [架构](#架构)
- [安装](#安装)
- [快速开始](#快速开始)
- [配置](#配置)
- [命令行](#命令行)
- [内置工具](#内置工具)
- [进阶能力](#进阶能力)
- [测试](#测试)
- [安全模型](#安全模型)
- [项目结构](#项目结构)
- [路线图](#路线图)
- [贡献](#贡献)
- [许可证](#许可证)

## 核心特性

- **规范化 ReAct 引擎** —— 单一的「读取–决策–行动」循环，内置权限校验、上下文压缩、成本统计，并保证消息历史对 provider 合法（每个 `tool_calls` 轮次都有对应回复）。
- **丰富的工具集** —— 文件编辑、可撤销补丁、Shell/Python 执行、测试运行、glob、AST 符号大纲、确定性代码搜索，以及带 SSRF 防护的网页抓取/搜索。
- **确定性优先检索** —— 基于符号的代码分块 + 关键词排序，并可叠加可选的持久化向量库与哈希嵌入。
- **MCP 客户端** —— 通过 stdio JSON-RPC 连接任意 [Model Context Protocol](https://modelcontextprotocol.io) 服务器，并将其工具暴露给 Agent。
- **并行子代理** —— `task` 工具可将多个独立子任务分发给全新、隔离的 Agent 并发执行。
- **真实流式输出** —— token 级 SSE，并从流中拼装工具调用（不丢失 tool_call）。
- **中断与转向** —— 运行中即可注入指令、在当前工具后停止、取消长时间运行的命令，或禁止编辑特定文件。
- **崩溃恢复** —— 每次运行的原子断点，配合 `agent.resume(run_id)` 续跑。
- **可靠性与安全** —— 带 `Retry-After` 退避的 HTTP 重试、任何持久化前的递归密钥脱敏，以及 deny/ask/allow 三级权限策略。
- **可观测性** —— 依赖可选的 OpenTelemetry 链路追踪，覆盖 run、LLM、tool 三类 span。
- **评测** —— 免 Docker 的 SWE-bench 风格评测器：生成补丁并在干净检出上对实例测试进行验证。

## 架构

```
                          ┌──────────────────────────┐
        用户任务 ────────▶│         Agent            │
                          │  (记忆、断点、追踪、转向) │
                          └────────────┬─────────────┘
                                       │
                          ┌────────────▼─────────────┐
                          │       ReAct 引擎         │
                          │  循环 · 压缩 · 成本统计  │
                          └──┬───────────┬───────────┘
                             │           │
              ┌──────────────▼──┐   ┌────▼─────────────┐
              │   模型路由器     │   │   工具注册表     │
              │ (OpenAI 兼容 /   │   │ 文件 · Shell ·   │
              │   DeepSeek)      │   │ 网页 · 代码搜索  │
              └────────┬─────────┘   │ · MCP · 子代理   │
                       │             └────┬─────────────┘
                       │                  │
              ┌────────▼─────────┐  ┌─────▼──────────┐
              │     权限策略      │  │   检索 +       │
              │  deny>ask>allow  │  │   向量库       │
              └──────────────────┘  └────────────────┘
```

## 安装

需要 **Python 3.11+**。

```bash
git clone https://github.com/mingbo-yang/EvoAgent.git
cd EvoAgent
pip install -e .

# 可选附加项
pip install -e ".[dev]"            # 测试、代码检查
pip install -e ".[observability]"  # OpenTelemetry 追踪
```

## 快速开始

设置 API Key（DeepSeek 或任意 OpenAI 兼容端点）：

```bash
export DEEPSEEK_API_KEY="sk-..."
```

在 Python 中运行一次性任务：

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
    result = await agent.run("找出本项目中失败的测试并修复它。")
    print(result.final_answer)


asyncio.run(main())
```

或在终端中运行：

```bash
evoagent run "总结这个仓库的结构"
evoagent chat        # 交互式会话
```

## 配置

EvoAgent 从 `evoagent.yaml` 与环境变量读取配置。初始化项目：

```bash
evoagent init
```

API Key 通过环境变量名（`api_key_env`）引用，**绝不会**写入源码、日志、追踪或会话文件。

| 变量 | 用途 |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API Key |
| `EVOAGENT_EGRESS_ALLOWLIST` | 网页工具的可选主机白名单（逗号分隔） |

## 命令行

| 命令 | 说明 |
| --- | --- |
| `evoagent run <task>` | 运行一次性 Agent 任务 |
| `evoagent chat` | 启动交互式会话 |
| `evoagent code <task>` | 在软件任务上运行代码 Agent |
| `evoagent eval <suite>` | 运行评测基准套件 |
| `evoagent init` | 在当前目录初始化 EvoAgent |
| `evoagent config` | 管理配置 |
| `evoagent memory` | 管理 Agent 记忆 |
| `evoagent trace` | 查看执行追踪 |

## 内置工具

| 类别 | 工具 |
| --- | --- |
| **文件** | `read_file`、`write_file`、`edit_file`、`multi_edit`、`apply_patch`、`undo_last` |
| **导航** | `list_directory`、`grep`、`glob`、`outline`、`code_search` |
| **执行** | `bash`、`python`、`run_tests` |
| **版本控制** | `git_status`、`git_diff` |
| **规划** | `write_todos`、`list_todos` |
| **网页** | `web_fetch`、`web_search`（带 SSRF 防护） |
| **编排** | `task`（并行子代理），以及任意 MCP 服务器工具 |

## 进阶能力

<details>
<summary><b>中断与转向</b></summary>

```python
from evoagent.core.steering import SteeringController

steering = SteeringController()
agent = Agent(..., steering=steering)

steering.inject("顺便更新一下 changelog")  # 注入指令
steering.forbid_file("config.py")           # 保护文件
steering.request_stop()                     # 当前工具后停止
steering.cancel()                           # 取消执行中的工具
```
</details>

<details>
<summary><b>崩溃恢复与续跑</b></summary>

```python
agent = Agent(..., checkpoint_dir=".runs")
result = await agent.run("一个多步骤的长任务")
# 崩溃/重启后：
result = await agent.resume(result.run_id, follow_up="从上次中断处继续")
```
</details>

<details>
<summary><b>MCP 客户端</b></summary>

```python
from evoagent.mcp import MCPClient, register_mcp_tools

client = MCPClient(["python", "my_mcp_server.py"])
await register_mcp_tools(registry, client)   # 工具以 mcp__* 前缀注册
```
</details>

<details>
<summary><b>可观测性</b></summary>

```python
from evoagent.observability import Tracer, configure_otel

configure_otel("evoagent")           # 若已安装 opentelemetry SDK
tracer = Tracer(use_otel=True)
agent = Agent(..., tracer=tracer)
# tracer.spans_named("tool.execute") -> 已记录的 span
```
</details>

## 测试

```bash
pip install -e ".[dev]"
ruff check evoagent tests
pytest -q
```

测试套件包含 **649 个测试**。除单元测试外，每项主要能力都额外通过真实模型 API 进行了端到端验证，而非仅依赖 mock。

## 安全模型

- **权限策略** —— deny > ask > allow，默认安全规则会阻止破坏性 Shell 命令以及对系统路径的写入。
- **工作区沙箱** —— 文件工具拒绝逃逸出工作区的路径；`glob` 拒绝 `..` 穿越。
- **出网防护** —— 网页工具阻止对私有、回环、链路本地及保留地址的请求（每次重定向都会重新校验），并支持可选的主机白名单。
- **密钥脱敏** —— API Key、Token 与凭据在任何日志、追踪或会话持久化之前都会被递归脱敏。

> EvoAgent 属于研究级软件。在面向不可信输入或生产环境运行前，请先阅读[安全策略](SECURITY.md)。

## 项目结构

```
evoagent/
├── core/            # ReAct 引擎、agent、转向、断点、成本、脱敏
├── models/          # provider 抽象、OpenAI 兼容 + DeepSeek、流式
├── tools/           # 内置工具注册表与实现
├── sandbox/         # 权限策略 + 出网（SSRF）防护
├── retrieval/       # 代码检索器、向量库、嵌入、关键词索引
├── rag/             # 文档加载、分块、查询引擎
├── mcp/             # Model Context Protocol stdio 客户端
├── observability/   # OpenTelemetry 兼容追踪
├── conversation/    # 会话、运行时、上下文压缩
├── memory/          # 经验/反思记忆存储
├── planning/        # 规划器、执行器、评判器、反思器
├── workflow/        # 工作流图 + 运行时
├── multi_agent/     # 多智能体角色与协议
├── eval/            # 评测框架 + SWE-bench 风格运行器
├── skills/          # 可复用的 Agent 技能
├── code/            # 代码 Agent 辅助（仓库地图、补丁、诊断）
├── logging/         # JSONL 事件、追踪、diff
├── config/          # 配置模型与加载
└── cli/             # Typer 命令行与终端 UI
```

## 路线图

参见 [ROADMAP.md](ROADMAP.md)。原生 Anthropic 与 Gemini 适配器已在规划中；当前可通过任意 OpenAI 兼容网关访问这些模型。

## 贡献

欢迎贡献。请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，在提交 Pull Request 前运行 `ruff` 与 `pytest`，并确保改动有测试覆盖。

## 许可证

基于 [MIT 许可证](LICENSE) 发布。
