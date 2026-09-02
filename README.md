# mini-nanobot

用 LangChain/LangGraph 复现 nanobot 核心运行时的中文学习项目。

标准 ReAct 循环交给 `create_agent`；会话并发、异步注入、Sustained Goal、
后台 Subagent、Dream 长期记忆等产品语义由外层 LangGraph 和 Python 运行时负责。

## 安装与运行

要求 Python 3.11+ 和 `uv`：

```powershell
uv sync --dev --python 3.11
copy .env.example .env
# 编辑 .env，至少填写 OPENAI_API_KEY
uv run mini-nanobot
```

支持 OpenAI 官方接口和兼容接口，通过 `OPENAI_API_BASE`、`MODEL_NAME` 配置。

## 控制台命令

- `/new`：创建并持久化一个新会话
- `/goal <目标>`：显式授权并创建 Sustained Goal
- `/stop`：取消当前会话运行及其活动目标
- `/status`：查看运行状态、pending 数量和目标状态
- `/compact`：后台手动压缩上下文
- `/dream`：后台巩固长期记忆
- `/help`、`/exit`

## 已实现的核心能力

- `create_agent` ReAct 循环与动态 system prompt
- OpenAI 兼容 Provider、模型/工具重试、调用预算、总超时、空响应兜底
- SQLite 对话检查点和原子 JSON 会话元数据
- 同会话串行、跨会话并发、取消与 pending queue
- `SummarizationMiddleware` 自动压缩并归档摘要
- 可替换的异步 `MemoryBackend`，默认使用原子本地文件
- 受限 Dream agent、快照回滚、变化检测和自动触发阈值
- 显式授权、续跑预算、完成/阻塞/取消状态的 Sustained Goal
- 后台 `SubagentManager`，并发/超时/取消和结果异步注入
- 工作区范围内的文件工具和可选 MCP 工具
- MessageBus、Channel 抽象与流式控制台

## 关键结构

```text
src/mini_nanobot/
  graph.py          外层业务图、create_agent 和运行时组装
  middleware.py     动态提示词、注入、压缩归档、重试与预算
  service.py        消息调度、会话并发、流式输出和命令
  session/          稳定会话元数据、锁、取消、pending queue
  subagents.py      后台 SubagentManager
  memory/
    store.py        MemoryBackend、原子文件后端和同步兼容层
    dream.py        受限 Dream agent
    consolidator.py 手动压缩兼容路径
  tools/            基础工具、Goal、spawn、MCP
  prompts.py        Python PromptTemplate
```

## 验证

```powershell
uv run pytest -v
uv run ruff check src tests
```

详细设计和学习说明见 [`docs/功能实现文档.md`](docs/功能实现文档.md)。

当前范围刻意不包含真实平台 Channel 和 OS 级沙箱；文件工具只提供应用层工作区
边界，不应视为不可信代码的系统隔离。
