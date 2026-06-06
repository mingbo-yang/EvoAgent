# EvoAgent — SOTA Roadmap (v0.5.0 → v1.0.0)

> 本文是面向"对标业界最先进编码 Agent（Claude Code / Cursor / OpenHands / LangGraph / Devin）"的前瞻路线图。
> 历史构建路线见 `docs/roadmap.md`（Phase 0–16，已完成框架搭建）。
> 本路线图经一次独立设计评审修订：P0 的目标不是"堆功能"，而是 **"一条安全、可自洽的自主编码循环：能编辑、能跑测试、能回滚、能保留任务状态"**。

## 执行摘要（中文）

当前 EvoAgent 底座健全（工具调用协议、权限/沙箱、工作流引擎、eval、真实 API 跑通），但要成为"健全且完整可用"的 agent，核心短板是：
1. **两套执行路径**，自主路径 `Agent.run` 用静态"先规划后执行"，不能"先读再决定"（实测 2/3）。
2. **编辑脆弱**（精确字符串匹配，无 diff/模糊/多文件/回滚）。
3. **无上下文管理**（只有 -50 窗口截断）、**无测试在环**、**无任务状态外化（todo）**。
4. **可靠性/安全缺口**：无 429 退避、无密钥脱敏、工具输出无治理。

路线图以 **P0 = 一条安全编码循环** 为先，再扩展广度（工具/检索/MCP/子 agent），最后产品化。

---

## 能力对标矩阵（EvoAgent 现状 vs SOTA 标准）

| 能力维度 | EvoAgent 现状 | SOTA 标准 | 差距 | 目标阶段 |
|---|---|---|---|---|
| 主循环 | 交互式迭代可用；`Agent.run` 静态规划 | 单一健壮 ReAct 循环（读→想→做→观察→修订） | 大 | P0 |
| 代码编辑 | exact-match `edit_file` | apply_patch/unified-diff + 模糊匹配 + 多处/多文件原子编辑 | 大 | P0 |
| 安全回滚 | 无 | 每轮快照/undo + diff 预览 + 事务化 | 大 | P0 |
| 测试在环 | 有 bash/python，但无显式 edit→test→fix 循环 | 内建测试反馈闭环 | 大 | P0 |
| 任务状态 | 无 model-facing todo | TodoWrite 式计划跟踪，跨压缩/恢复持久 | 大 | P0 |
| 上下文管理 | `messages[-50:]` 截断 | token 预算 + 摘要压缩 + 观测裁剪 | 大 | P0 |
| 工具输出治理 | 部分截断 | 统一大小上限 + head/tail + 结构化元数据 | 中 | P0 |
| 限流/重试 | 仅 timeout/network | 429/5xx 指数退避 + 尊重 Retry-After | 中 | P0 |
| 密钥安全 | 无脱敏 | 持久化前对 trace/log/session/工具输出脱敏 | 中 | P0 |
| 工具并行 | 串行 | 按副作用分级：只读并行、写/shell 串行 | 中 | P0(只读) / P1 |
| 工具广度 | 9 个 | 15–25：glob/apply_patch/web_fetch/web_search/符号大纲/todo | 中 | P1 |
| 中断/操控 | 无 mid-run steering | 停在当前工具后/改计划/禁改某文件/取消长任务 | 中 | P1 |
| 检索 | mock embedding + 内存库 | glob→符号→repo map→代码分块→(可选)向量库 | 中 | P1 |
| MCP | 无 | MCP client（在权限/出网控制之后） | 中 | P1 |
| 崩溃恢复 | 仅 workflow | 会话/工具/todo/文件快照 → 从最近稳定轮恢复 | 中 | P0尾/P1 |
| 子 agent | 基础顺序协议 | 并行子任务派发（Task 工具） | 中 | P1 |
| 流式 | 缓冲切片 | 真 token 流 + SSE 工具调用拼装 | 低 | P1 |
| Provider 广度 | DeepSeek + OpenAI 兼容 | + 原生 Anthropic/Gemini | 低 | P2 |
| 可观测性 | trace + cost | OpenTelemetry + 成本面板 | 低 | P2 |
| 评测 | harness（合成任务） | SWE-bench Lite 真实接入 + CI 回归 | 中 | P2 |
| Prompt 缓存 | 无 | provider 缓存控制 | 低 | P2 |

---

## P0 — 一条安全、可自洽的编码循环（最高优先）

目标验收：在真实 API 下，agent 能对一个多文件仓库**读→改→跑测试→读失败→再改→回滚误改**，并在长任务中保留 todo、不超 token 预算、不泄露密钥。每项均配真实 DeepSeek 验证 + 回归测试 + 独立提交。

**P0.1 统一主循环（先做，其他都依赖它）**
- 把 `Agent.run`/`AgentLoop` 重构为与 `ConversationRuntime` 一致的迭代式 ReAct 循环（读→想→做→观察→修订），废弃静态 plan-ahead。
- 触点：`evoagent/core/agent.py`, `evoagent/planning/loop.py`, `evoagent/conversation/runtime.py`。
- 验收：现有 eval harness 在新循环上 ≥ 旧路径；新增"需先读后改"的 eval 任务通过。

**P0.2 健壮编辑栈**
- `apply_patch`（unified diff）工具；`edit_file` 支持单次多处编辑 + 模糊匹配（difflib，置信阈值）；多文件原子应用（全成功或全回滚）；写前 diff 预览。
- 触点：`evoagent/tools/file_tools.py`, 新增 `evoagent/tools/patch_tools.py`, `evoagent/code/patch.py`。
- 验收：对缩进/上下文漂移的编辑成功率显著提升；冲突可检测；回归测试覆盖模糊/多处/多文件/失败回滚。

**P0.3 检查点 / 撤销**
- 每轮（或每次写）做文件快照（git 或影子目录）；`undo_last`（撤销上次工具/上一轮）；与 P0.2 的原子事务联动。
- 触点：复用 `evoagent/logging/checkpoint.py`，新增工作区文件快照层。
- 验收：误改后可一键回滚；崩溃后能从最近快照恢复（与 P0.8 衔接）。

**P0.4 面向模型的 Todo/计划工具**
- `create_todo/update_todo/list_todos`，状态 pending/in_progress/done/blocked；跨上下文压缩与 resume 持久；摘要时纳入。
- 触点：新增 `evoagent/tools/todo_tools.py`，持久化进 session。
- 验收：多步任务不重复/不遗漏子任务；压缩后 todo 仍在上下文。

**P0.5 测试在环（edit→test→fix）**
- 主循环显式支持：定位→编辑→跑定向测试→读失败→打补丁→重跑→产出最终 diff 摘要。
- 触点：`evoagent/planning/loop.py` + `evoagent/code/test_runner.py`。
- 验收：新增需要测试反馈的 eval 任务（如修 bug 直到 pytest 通过）通过率提升。

**P0.6 上下文管理（预算 + 压缩）**
- token 计数；硬预算上限；超限时对老对话/陈旧观测做摘要压缩，保留文件/todo/近期工具结果。
- 触点：`evoagent/conversation/runtime.py`, 新增 `evoagent/conversation/context.py`。
- 验收：长会话不溢出；压缩后关键状态（todo/当前文件/最近失败）保留。

**P0.7 工具输出治理**
- 每工具输出大小上限 + head/tail 截断；结构化元数据（exit_code/duration/cwd/changed_files）；超大输出提示模型收窄查询。
- 触点：`evoagent/tools/schema.py` + 各工具。
- 验收：单工具输出受限；元数据齐全。

**P0.8 可靠性与安全基线**
- 429/5xx 指数退避（尊重 `Retry-After`）：`evoagent/models/openai_compatible.py`。
- 密钥脱敏：持久化前对 trace/log/session/工具输出做模式脱敏（TOKEN/KEY/SECRET/PASSWORD/CREDENTIAL 等）：新增 `evoagent/core/redaction.py`，接入 trace/store/error_view。
- 只读工具并行：为工具加副作用标签（read_only/writes_files/runs_process/network），仅并行只读（read_file/list_directory/grep/git_status），写与 shell 串行，保持观测顺序确定；每工具超时/取消。
- 验收：模拟 429 触发退避；密钥不落盘/不回传；并行只读不破坏状态。

**P0 出口标准（Definition of Done）**：单一循环能在真实仓库稳定完成"读-改-测-回滚"，长任务有 todo 与上下文压缩，密钥安全，限流可恢复。

---

## P1 — 扩展 agent 能力

**P1.1 工具广度**：`glob`、`apply_patch`（若 P0 未含全）、`web_fetch`/`web_search`（带出网策略）、符号大纲/定义-引用、`view`/`outline`。
**P1.2 中断 / 操控（先于子 agent）**：用户中断、"当前工具后停"、"改计划"、"别动文件 X"、"现在跑测试"、取消长 shell。
**P1.3 检索（确定性优先）**：顺序为 glob → 符号大纲/定义 → repo map → 代码感知分块 →（仅当 eval 证明检索是瓶颈时）真实 embedding → 向量库。复用 `evoagent/code/repo_map`。
**P1.4 MCP client**：在权限/出网/脱敏（P0.8）之后接入 Model Context Protocol，外部工具/资源走统一权限。
**P1.5 子 agent 编排**：并行子任务派发（Task 工具），基于已稳的单 agent 循环。
**P1.6 真流式**：token 级流 + SSE 工具调用拼装（修复 `stream_chat` 丢 tool_calls）。
**P1.7 崩溃恢复/resume**（若 P0 未完成）：会话/工具/todo/文件快照统一恢复。

---

## P2 — 生产化与规模

- 原生 Anthropic（`/v1/messages`，`x-api-key`）与 Gemini（`:generateContent`）适配器，替换当前的安全降级报错。
- 可观测性：OpenTelemetry trace、成本/延迟面板、结构化 run 日志。
- 高级出网控制与审计日志。
- 真实 SWE-bench Lite 接入 + CI 回归评测（measured，非 estimated）。
- 向量库后端（FAISS/Qdrant/sqlite-vec）——仅当 repo-map/确定性检索不足时。
- Prompt 缓存（provider 专属 cache control）。

---

## 横切关注点（每阶段都遵守）

- **测试**：每个能力配真实 API 验证 + 回归测试；保持 `ruff`/`compileall`/`pytest` 全绿；不删失败测试求绿。
- **安全**：密钥永不入源码/日志/session；ASK 默认 fail-closed；写操作经权限边界。
- **评测驱动**：新能力先定义 eval 任务再实现；用 measured 指标，不把 estimated 当 measured。
- **提交规范**：每能力独立提交，含 `Co-authored-by: Copilot`。

## 依赖与排序要点（评审结论）

1. **先统一主循环**（P0.1），否则功能会在错误路径重复建设。
2. **编辑必须配回滚/预览**（P0.2+P0.3 同期），否则更强的编辑只会扩大破坏半径。
3. **并行只做只读**，写/shell 串行，直到工具有副作用分级。
4. **MCP 在安全控制之后**；**子 agent 在单 agent 能力达标之后**。
5. **明确丢弃/推迟**：P0 不做 prompt 缓存、不做全量向量库、不做无限制并行、不做 provider 广度——这些不能弥补弱循环。

## 里程碑版本

- **v0.6.0** = P0 出口（安全自洽的编码循环）。
- **v0.7.0** = P1 广度（工具/检索/MCP/中断/子 agent/流式）。
- **v1.0.0** = P2 生产化（provider 广度、可观测性、SWE-bench、稳定）。