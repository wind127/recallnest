"""Explicitly synthetic examples; no model-generated extraction is implied."""
import json
from uuid import NAMESPACE_URL, uuid5
from .importers import parse_upload
from .models import KnowledgeInput, ProjectInput, ReviewInput, MemoryInput, utc_iso


DEMO_JSON = [{"source": "demo:chatgpt", "external_id": "synthetic-learning", "title": "【演示 / Demo】中文学习计划", "messages": [
    {"id": "demo-u1", "role": "user", "content": "【合成示例】我偏好用中文学习，每天复习十分钟。", "timestamp": "2026-10-14T00:00:00Z"},
    {"id": "demo-a1", "role": "assistant", "content": "【合成示例】先保存来源，再制作可编辑的复习卡片。", "parent_id": "demo-u1"}]}]
DEMO_JSONL = [
    {"type": "session_meta", "payload": {"id": "synthetic-codex", "title": "【演示 / Demo】SQLite 练习"}},
    {"type": "event_msg", "payload": {"type": "user_message", "message": "【合成示例】SQLite 事务可以保证一组操作一起完成。"}},
    {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "【合成示例】失败时应回滚。"}]}}
]
DEMO_MARKDOWN = "# 【演示 / Demo】复习笔记\n\n【合成示例】知识条目保留来源，记忆候选需要确认。\n"


def seed_demo(repo):
    conversations = parse_upload("demo.json", json.dumps(DEMO_JSON, ensure_ascii=False).encode())
    codex = parse_upload("demo.jsonl", "\n".join(json.dumps(r, ensure_ascii=False) for r in DEMO_JSONL).encode())
    notes = parse_upload("demo.md", DEMO_MARKDOWN.encode())
    for conversation in codex + notes:
        conversation.source = "demo:" + conversation.source
        conversation.source_identity = "demo"
    conversations += codex + notes
    for conversation in conversations:
        conversation.source_identity = "demo"
        conversation.metadata["synthetic"] = True
    result = repo.import_conversations(conversations, preserve_existing=True)
    first = repo.get_conversation(result["conversation_ids"][0])
    message = first["messages"][0]
    evidence = [{"message_id": message["id"], "message_version": 1, "quote": "我偏好用中文学习，每天复习十分钟。"}]
    ids = {name: str(uuid5(NAMESPACE_URL, "recallnest:demo:" + name)) for name in ("project", "knowledge", "review", "memory")}
    entries = [
        ("projects", ids["project"], ProjectInput, {"name": "【演示 / Demo】学习项目", "description": "明确标记的合成示例项目", "goals": ["每天复习十分钟"]}),
        ("knowledge", ids["knowledge"], KnowledgeInput, {"title": "【演示 / Demo】让知识有来源", "summary": "合成示例知识，供界面试用。", "body": "复习时可查看原文证据。", "type": "note", "tags": ["演示", "学习"], "project_id": ids["project"], "source": "demo", "evidence": evidence}),
        ("reviews", ids["review"], ReviewInput, {"question": "【演示 / Demo】每天计划复习多久？", "answer": "合成示例中的计划是十分钟。", "knowledge_id": ids["knowledge"], "project_id": ids["project"], "source": "demo", "evidence": evidence}),
        ("memories", ids["memory"], MemoryInput, {"content": "【合成演示】偏好用中文学习。", "category": "preference", "subject": "演示学习偏好", "source": "demo", "status": "candidate", "evidence": evidence}),
    ]
    created = {table: 0 for table, *_ in entries}
    with repo.db.transaction() as connection:
        for table, entity_id, model, values in entries:
            if connection.execute(f"SELECT 1 FROM {table} WHERE id=?", (entity_id,)).fetchone():
                continue
            data = model.model_validate(values).model_dump()
            stamp = utc_iso()
            data.update(id=entity_id, created_at=stamp, updated_at=stamp)
            repo._validate_links(connection, data)
            if "evidence" in data:
                data["evidence"] = repo._validate_evidence(connection, data["evidence"])
            if table == "reviews":
                data.update(due_at=stamp, interval_minutes=0, repetitions=0)
            if table == "memories":
                data["effective_at"] = stamp
            repo._save_entity(connection, table, data)
            created[table] += 1
    return {"demo": True, **result, "created": created}
