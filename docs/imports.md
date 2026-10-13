# 会话导入与归档

首版支持 ChatGPT 导出 JSON/ZIP、Codex 会话 JSONL、统一 JSON 和 Markdown。导入先保留原文，再将可展示的消息转换成统一格式。知识整理属于后续独立任务，模型失败不会删除已导入的会话。

## ChatGPT

上传 `conversations.json`，或包含这个文件的 ZIP。解析器保留完整消息树、所有分支、原始节点和当前分支。没有可展示文字的节点仍保留在原始归档中。

图片、音频等内容块的元数据及引用会留在 JSON 归档中。首版不会下载这些引用指向的媒体，也不会把媒体引用当成已经保存的图片或音频。导入预览会提示非文本内容。

## Codex

上传包含 `session_meta` 的 `.jsonl` 文件。支持 `response_item` 中的消息，以及 `event_msg` 中的用户或助手消息；相邻的同一条消息在两种记录中的表示会合并。

原始记录中仍保留工具调用、重复表示和不参与文字展示的内容。直接上传会严格校验每一行；持续采集时才允许等待尚未写完的最后一行。

## 统一 JSON

其他应用可以提交单个会话、会话数组，或 `{ "conversations": [...] }`。建议提供稳定的会话和消息 ID，方便识别新增消息和修改。

```json
{
  "source": "my-assistant",
  "source_identity": "my-workspace",
  "external_id": "session-001",
  "title": "数据库学习",
  "messages": [
    { "id": "u1", "role": "user", "content": "我想复习 SQLite。" },
    { "id": "a1", "role": "assistant", "content": "先比较事务和锁。", "parent_id": "u1" }
  ]
}
```

输入中的消息 ID 和父消息 ID 是来源系统的 ID；入库后生成的内部 ID 用于界面和证据引用。详情响应会同时保留两者。

同一来源下，同一个 `source_identity + external_id` 表示同一会话。不同账户或工作区可以设置不同的 `source_identity`。

没有 ID 的记录使用内容指纹。同内容文件改名后仍能去重；修改内容可能产生新的指纹。因此持续接入时应提供稳定 ID。

## Markdown

用“用户 / 助手”或“User / Assistant”作为标题分隔消息。一般笔记也可以直接导入，会作为一个来源记录保存。

```markdown
# 用户
为什么要给数据库建立索引？

# 助手
索引用额外存储换取特定查询的速度。
```

## 预览、确认与更新

预览只解析文件，不写入数据库。确认导入后会显示新增、更新、重复和消息计数。一个文件中的记录以事务方式导入；格式错误不会留下半份记录。

再次导入同一份文件不会重复创建消息。稳定 ID 对应的内容改变后，归档保留旧版本；证据会标记其引用是否已经过时。

默认限制为上传 32 MiB、ZIP 总解压大小 128 MiB、ZIP 成员 1000 个。较大的可信导出可以通过以下环境变量调整，值必须为正整数：

- `RECALLNEST_MAX_UPLOAD_BYTES`
- `RECALLNEST_MAX_ZIP_BYTES`
- `RECALLNEST_MAX_ZIP_MEMBERS`

## 数据导出

JSON 导出包含会话原始记录、消息版本、知识、项目、记忆、复习状态、任务和修订历史。Markdown 导出适合阅读，包含文字和证据 ID。

当前提供的是可移植归档，没有一键全库恢复接口。需要保存完整运行状态时，也可以使用可靠的 SQLite 备份流程保留本地数据库。不要在数据库仍写入时只复制主文件而漏掉 WAL。

精确请求和返回字段见 [API contract](api-contract.md)。
