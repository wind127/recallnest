# Codex 整理，RecallNest 沉淀

Codex 使用当前账号和模型整理会话；RecallNest 在本机保存原文、引用、知识、复习卡和记忆候选。无需额外模型 API Key，不读取或复制 Codex 登录 token。订阅登录沿用现有额度和限制；如果 Codex 自身使用 API Key，则仍按其原有方式计费。

## 安装接入

需要 Python 3.10+、uv、已登录的 Codex CLI。网页还需要 Node.js 22.12+ 和 npm。在本地源码目录执行：

```sh
uv sync --locked
uv run --locked python scripts/install_codex.py
```

脚本把配套技能安装到 `~/.agents/skills/recallnest`，通过 `codex mcp add` 注册 `recallnest`。MCP 使用该项目的 Python 环境执行 `python -m recallnest mcp --local-only`，不依赖启动 Codex 时的工作目录。不会导入个人历史、启动采集器、修改模型配置或读取登录 token。

已有同名但不属于本项目的技能或 MCP 不会覆盖；已编辑的技能会被保留并报告冲突。同一脚本可重复运行来更新未编辑的技能。可先预览，不做写入：

```sh
uv run --locked python scripts/install_codex.py --dry-run
```

自定义路径用 `--data-dir "/path/to/private-data"`、`--skills-dir "/path/to/skills"`；默认数据目录为 `~/.recallnest`（或 `RECALLNEST_DATA_DIR`）。搬动源码或 Python 环境后重新运行接入脚本。

重启 Codex，再检查 `codex mcp list`。新会话中应能找到 `$recallnest` 技能以及七个 RecallNest 工具。安装只提供工具和技能，不会自动触发每轮存档。

## 开始使用

在 Codex 中输入：

```text
用 $recallnest 整理待处理会话，提炼带原文引用的知识和复习卡，个人背景只保存为记忆候选。
```

当前会话尚未归档时，可以输入：

```text
用 $recallnest 保存并整理这次对话；之后在本会话的重要进展处持续沉淀，回答前检索相关已确认记忆。
```

技能让 Codex 提交真实可用的会话内容，或处理已经导入/采集的历史。`prepare_consolidation` 提供一个持久化的待整理片段；Codex 自己生成知识、复习卡和记忆候选，再通过 `complete_consolidation` 保存。每次完成后才推进进度，重启可续接，网络重试不重复插入。新增或编辑的消息版本会再次进入待处理范围。所有分支均可处理，不把互斥分支拼成确定事实。

每项结果都需要这个片段内的精确引用与内部消息版本。来源变化会拒绝旧结果；字段/引用错误整批不写入。个人记忆只接受用户明确陈述的原文，提问和助手猜测不能变成用户事实。记忆在网页人工确认后才进入 `context`，后续由 Codex 按任务检索使用；这不会训练模型权重。

没有来源或未获得访问范围的会话不会自动出现。Codex 无法读取完整逐字记录时，保存明确标注的助手摘要，不能伪造用户原话。持续采集适合保留完整本地日志；先预览自己选定的目录，命令见 [integrations.md](integrations.md#explicit-continuous-codex-capture)。采集器只归档，Codex 未运行时不执行整理。

## 查阅、复习和确认记忆

```sh
cd web
npm ci
npm run build
cd ..
uv run --locked recallnest serve --no-ai
```

打开 <http://127.0.0.1:8787>。`--no-ai` 关闭后台模型整理，并在模型测试、对话、嵌入索引等入口阻止直接模型调用，即使以前保存过 API Key。文本检索、导入、编辑、来源查阅、复习和记忆确认正常使用。网页显示 Codex 模式，并提示回到 Codex 整理与对话。

**MCP、网页、导入与采集必须使用同一个 `--data-dir`。** 不加 `--no-ai` 的启动方式保留独立 API 模型能力；不要与 Codex 同时整理同一份资料。MCP 的 `--local-only` 也禁止显式语义搜索，默认文本搜索不会调用模型。

## 手动接入

没有可用 Codex CLI 时，将下面配置加入 Codex 的 `~/.codex/config.toml`（替换路径，保留其他设置），再把仓库内 `skills/recallnest` 复制到 `~/.agents/skills/recallnest`。在 Windows TOML 中使用正斜线可避免转义：

```toml
[mcp_servers.recallnest]
command = "D:/Projects/recallnest/.venv/Scripts/python.exe"
args = ["-m", "recallnest", "mcp", "--local-only", "--data-dir", "D:/RecallNest Private"]
```

macOS/Linux 的 Python 路径通常是 `/path/to/recallnest/.venv/bin/python`。CLI、桌面应用和 IDE 在同一个 Codex host 上共享 MCP 配置；本地工具不能因此自动在云端会话中使用。

官方接入依据：[MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)、[技能位置与发现](https://learn.chatgpt.com/docs/build-skills)。本项目使用已有 Codex 会话执行推理，不实现 token 转发、OAuth 登录或独立的订阅模型网关。
