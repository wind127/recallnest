# RecallNest · 知巢

[![CI](https://github.com/wind127/recallnest/actions/workflows/ci.yml/badge.svg)](https://github.com/wind127/recallnest/actions/workflows/ci.yml)

把 AI 会话留下来，变成能查阅、能复习、有原文依据的知识与个人记忆。

[English](README.en.md) · [导入说明](docs/imports.md) · [记忆与复习](docs/memory-and-review.md) · [模型设置](docs/models.md) · [CLI / MCP](docs/integrations.md) · [部署](docs/deployment.md) · [API](docs/api-contract.md)

RecallNest 是本地运行的单用户应用。原始会话、项目、知识、复习记录和记忆保存在 SQLite 中；可选择连接 OpenAI 兼容模型，用于整理和问答。没有模型也可以导入、搜索、手动整理和复习。

## 四个使用场景

- **整理历史**：导入 ChatGPT 导出 JSON/ZIP、Codex JSONL、统一 JSON 或 Markdown。保留原文、会话分支和消息版本，重复导入按稳定 ID 去重。
- **持续积累**：应用内对话自动归档并排队整理；显式配置的 Codex 目录支持持续采集；其他工具可以通过 REST/MCP 提交资料。
- **查阅与复习**：按来源、项目、标签、类型和日期查找，收藏知识，跳回原文证据，使用到期复习卡片。
- **逐步了解你**：把偏好、背景、目标、状态与约束整理为记忆候选。你确认、纠正或替代后，AI 在后续回答中使用相关有效记忆，并展示上下文来源。

![知识查阅与原文证据](docs/images/knowledge.png)

截图使用合成会话与固定的模型测试响应，展示知识、原文引用和来源版本。另见[复习完成与调度界面](docs/images/review.png)，不代表真实模型的整理质量评测。

## 本地启动

需要 Python 3.10+、[uv](https://docs.astral.sh/uv/)、Node.js 22.12+ 与 npm。

```sh
git clone https://github.com/wind127/recallnest.git
cd recallnest
uv sync --locked
cd web
npm ci
npm run build
cd ..
uv run recallnest serve
```

打开 <http://127.0.0.1:8787>。首次打开可以导入自己的文件，也可以选择载入明确标注的合成示例；不会自动读取你的历史目录。

开发界面使用 `web/` 下的 `npm run dev`，API 使用上述启动命令。Vite 将 `/api` 转发到本地服务。

## 模型与数据

在界面的模型设置中填写兼容接口的 base URL、聊天模型和可选密钥。嵌入模型可选，用于增加语义检索。也可以使用 `.env.example` 中列出的环境变量；复制文件本身不会自动加载它，需要由运行环境传入。

base URL 通常以 `/v1` 结尾，例如适配的本地服务 `http://127.0.0.1:11434/v1`。接口需要支持聊天补全；模型整理需要返回指定的 JSON 结构。远程模型会收到所处理的会话文本与选中的上下文，使用哪家供应商由你配置。

默认数据目录为 `~/.recallnest`，可用 `RECALLNEST_DATA_DIR` 指定。密钥属于服务端连接配置，不出现在公开 API 响应或归档导出中。你写在会话原文中的敏感内容仍属于归档内容，分享导出前应自行核对。

## 先试一次完整流程

导入文件并确认预览，进入会话核对原文。配置模型后查看整理任务与生成的知识、卡片和记忆候选；打开引用确认来源，确认一条准确的记忆，再发起新对话。进入复习，揭示答案并反馈掌握程度。

任务失败保留原文，可在任务列表查看原因并重试。未配置模型时，整理状态会明确说明配置要求，不会生成假的 AI 结果。

## 持续采集与工具接入

在 Windows 上，可以先预览自己明确指定的 Codex 日志目录，再启动持续采集。以下路径为示意，请换成你的日志目录与私有数据目录：

```powershell
uv run --locked recallnest capture preview --root "D:\Codex Logs" --data-dir "D:\RecallNest Private"
uv run --locked recallnest capture start --root "D:\Codex Logs" --data-dir "D:\RecallNest Private"
uv run --locked recallnest capture status --data-dir "D:\RecallNest Private"
uv run --locked recallnest capture stop --data-dir "D:\RecallNest Private"
```

采集器在后台运行，保留原始记录和版本；重复扫描不重复创建消息。临时不可读或正在改写的日志会报告错误，并在后续扫描中重试。模型自动整理需要同时运行使用同一数据目录的 `recallnest serve`。

MCP 提供 `search`、`fetch`、`context`、`submit`、`remember` 五个 stdio 工具。读取个人上下文只返回有效的已确认记忆，工具提交的个人记忆先成为候选。[接入文档](docs/integrations.md) 包含通用配置及可选的 Codex CLI 注册命令。

也可以离线导入和导出：

```sh
uv run --locked recallnest import examples/conversations.json
uv run --locked recallnest export --output recallnest-export.json
uv run --locked recallnest export --format markdown --output recallnest-export.md
```

## 边界

- ChatGPT 首版使用导出文件和主动提交接口。没有实现网页外的自动监听或浏览器扩展。
- “越来越了解”通过记忆检索与上下文实现，不涉及模型权重训练。
- 个人记忆候选不自动成为事实，用户提问和助手推断不应当形成已确认的个人背景。
- 图片、音频和工具记录保存在原始来源元数据中；不下载或识别被引用的媒体文件。
- 完整 JSON 导出包含原文、版本、证据和历史；Markdown 适合阅读。首版没有完整归档恢复接口，需要迁移时备份数据目录。
- 默认监听回环地址，面向本地单用户。没有面向公网的账户与认证系统。

## 开发与参考

```sh
uv run pytest -q
cd web
npm test -- --run
npm run build
```

[贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md) · [验证记录](docs/verification.md) · [设计参考](docs/design-references.md) · [已批准设计](docs/superpowers/specs/2026-10-14-recallnest-design.md)

本项目参考 Mem0、Khoj、Basic Memory 和 Open WebUI 的产品思路，独立实现。采用 [MIT License](LICENSE)。
