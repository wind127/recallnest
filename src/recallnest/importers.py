"""Source adapters archive raw records and normalize only available text."""
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import zipfile
from pydantic import ValidationError
from .models import NormalizedConversation, NormalizedMessage, utc_iso
from .json_utils import validate_json_numbers, validate_source_metadata


class ImportFailure(ValueError):
    """A safe, user-readable parse error."""


class ImportLimitExceeded(ImportFailure):
    """Uploaded or expanded data exceeds the configured resource limits."""


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _parts(content):
    if isinstance(content, str):
        return content, 0
    if isinstance(content, dict):
        content = content.get("parts", content.get("content", []))
    if not isinstance(content, list):
        return "", 1 if content else 0
    texts, non_text = [], 0
    for part in content:
        if isinstance(part, str):
            texts.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
        else:
            non_text += 1
    return "\n".join(texts), non_text


def _chatgpt(record):
    mapping = record.get("mapping")
    if not isinstance(mapping, dict):
        raise ImportFailure("ChatGPT mapping must be an object")
    node_ids = {key: str(node["message"].get("id") or key) for key, node in mapping.items()
                if isinstance(node, dict) and isinstance(node.get("message"), dict)}
    rendered_node_ids = {key: message_id for key, message_id in node_ids.items()
                         if mapping[key]["message"].get("author", {}).get("role") in ("user", "assistant", "system", "developer", "tool")}
    messages, non_text = [], 0
    for node_id, node in mapping.items():
        if not isinstance(node, dict) or not node.get("message"):
            continue
        message = node["message"]
        role = message.get("author", {}).get("role")
        text, count = _parts(message.get("content", {}))
        non_text += count
        if role not in ("user", "assistant", "system", "developer", "tool"):
            continue
        parent, visited = node.get("parent"), {node_id}
        while parent and parent not in rendered_node_ids:
            if parent in visited:
                raise ImportFailure("ChatGPT graph contains a cycle")
            visited.add(parent)
            parent = mapping.get(parent, {}).get("parent")
        messages.append(NormalizedMessage(id=node_ids[node_id], role=role, content=text,
            timestamp=message.get("create_time"), parent_id=rendered_node_ids.get(parent), raw=message,
            metadata={"node_id": node_id, "children": node.get("children", []), "non_text_blocks": count}))
    return NormalizedConversation(source="chatgpt", external_id=str(record.get("id") or record.get("conversation_id") or "") or None,
        title=record.get("title") or "Untitled", created_at=record.get("create_time"), updated_at=record.get("update_time"),
        current_node=record.get("current_node"), messages=messages, raw=record,
        metadata={"node_message_ids": node_ids, "non_text_blocks": non_text})


def _uniform(record):
    if not isinstance(record, dict) or not isinstance(record.get("messages"), list) or not isinstance(record.get("source"), str):
        raise ImportFailure("Expected source, external_id, title and messages JSON format")
    messages = []
    for index, item in enumerate(record["messages"]):
        if not isinstance(item, dict):
            raise ImportFailure(f"message {index + 1} must be an object")
        text, count = _parts(item.get("content", ""))
        metadata = validate_source_metadata(item.get("metadata", {}))
        messages.append(NormalizedMessage(id=item.get("id") or item.get("external_id"), role=item.get("role"),
            content=text, timestamp=item.get("timestamp") if item.get("timestamp") is not None else item.get("created_at"), parent_id=item.get("parent_id"),
            raw=item, metadata={**metadata, "non_text_blocks": count}))
    return NormalizedConversation(source=record["source"], source_identity=record.get("source_identity"),
        external_id=record.get("external_id") or record.get("id"), title=record.get("title") or "Untitled",
        created_at=record.get("created_at"), updated_at=record.get("updated_at"), current_node=record.get("current_node"),
        project_id=record.get("project_id"), messages=messages, raw=record, metadata=record.get("metadata", {}))


def _json(data):
    records = json.loads(data)
    validate_json_numbers(records)
    if isinstance(records, dict) and "conversations" in records:
        records = records["conversations"]
    if isinstance(records, dict):
        records = [records]
    if not isinstance(records, list):
        raise ImportFailure("JSON must contain a conversation or conversation list")
    return [_chatgpt(record) if isinstance(record, dict) and "mapping" in record else _uniform(record) for record in records]


def _codex(data, allow_partial):
    records = []
    lines = data.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            if allow_partial and index == len(lines) - 1 and not line.endswith(("\n", "\r")):
                break
            raise ImportFailure(f"Malformed JSONL at line {index + 1}") from None
        if not isinstance(record, dict):
            raise ImportFailure(f"JSONL line {index + 1} must be an object")
        try:
            validate_json_numbers(record)
        except ValueError:
            raise ImportFailure(f"JSONL line {index + 1} contains a non-finite number") from None
        records.append(record)
    session = next((r.get("payload", {}) for r in records if r.get("type") == "session_meta"), None)
    if not isinstance(session, dict):
        raise ImportFailure("Codex JSONL requires session_meta")
    messages, last_representation, last_explicit_id, paired, non_text = [], None, None, False, 0
    for record in records:
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        representation, role, text, count = record.get("type"), None, "", 0
        if representation == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            text, count = _parts(payload.get("content", []))
        elif representation == "event_msg" and payload.get("type") in ("user_message", "agent_message"):
            role = "user" if payload["type"] == "user_message" else "assistant"
            text, count = _parts(payload.get("message", ""))
        non_text += count
        if role not in ("user", "assistant", "system", "developer", "tool"):
            continue
        explicit_id = str(payload["id"]) if payload.get("id") is not None else None
        timestamp = utc_iso(record["timestamp"]) if record.get("timestamp") is not None else None
        distinct_id = explicit_id is not None and last_explicit_id is not None and explicit_id != last_explicit_id
        distinct_time = bool(messages) and timestamp is not None and messages[-1].timestamp is not None and timestamp != messages[-1].timestamp
        if (messages and not paired and not distinct_id and not distinct_time
                and messages[-1].role == role and messages[-1].content == text
                and representation != last_representation):
            paired = True
            continue
        message_id = explicit_id or fingerprint([session.get("id"), len(messages), role, record.get("timestamp"), text])
        messages.append(NormalizedMessage(id=message_id, role=role, content=text, timestamp=timestamp,
            parent_id=messages[-1].id if messages else None, raw=record, metadata={"non_text_blocks": count}))
        last_representation = representation
        last_explicit_id, paired = explicit_id, False
    return [NormalizedConversation(source="codex", external_id=session.get("id"), title=session.get("title") or "Codex session",
        created_at=session.get("timestamp"), current_node=messages[-1].id if messages else None,
        messages=messages, raw={"records": records}, metadata={"session_meta": session, "non_text_blocks": non_text})]


def _markdown(filename, text):
    pattern = re.compile(r"^#{1,6}\s*(user|assistant|用户|助手)\s*:?\s*$", re.IGNORECASE | re.MULTILINE)
    headings = list(pattern.finditer(text))
    heading_title = next((line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), None)
    title = heading_title if heading_title is not None else PurePosixPath(filename).stem
    messages = []
    for index, heading in enumerate(headings):
        content = text[heading.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)].strip()
        role = "user" if heading.group(1).lower() in ("user", "用户") else "assistant"
        messages.append(NormalizedMessage(id=fingerprint([index, role, content]), role=role, content=content,
            parent_id=messages[-1].id if messages else None, raw={"heading": heading.group(0), "content": content}))
    if not headings:
        messages = [NormalizedMessage(id=fingerprint(text), role="user", content=text, raw={"text": text})]
    return [NormalizedConversation(source="markdown", external_id="fingerprint:" + fingerprint({"markdown": text}), title=title, messages=messages,
        current_node=messages[-1].id, raw={"text": text}, metadata={"kind": "conversation" if headings else "note", "title_from_filename": heading_title is None})]


def parse_upload(filename, data, *, source_identity=None, max_upload_bytes=32 * 1024 * 1024,
                 max_zip_bytes=128 * 1024 * 1024, max_zip_members=1000, allow_partial=False):
    if len(data) > max_upload_bytes:
        raise ImportLimitExceeded("File exceeds upload byte limit")
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    try:
        if suffix == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                members = archive.infolist()
                if len(members) > max_zip_members:
                    raise ImportLimitExceeded("ZIP exceeds members limit")
                if sum(member.file_size for member in members) > max_zip_bytes:
                    raise ImportLimitExceeded("ZIP exceeds expanded byte limit")
                candidates = []
                for member in members:
                    name = member.filename.replace("\\", "/")
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
                        raise ImportFailure("ZIP contains an unsafe path")
                    if path.name.lower() == "conversations.json" and not member.is_dir():
                        candidates.append(member)
                if not candidates:
                    raise ImportFailure("ZIP has no conversations.json")
                conversations = []
                for member in candidates:
                    with archive.open(member) as stream:
                        content = stream.read(max_zip_bytes + 1)
                    if len(content) > max_zip_bytes:
                        raise ImportLimitExceeded("ZIP exceeds expanded byte limit")
                    conversations.extend(_json(content.decode("utf-8-sig")))
        else:
            text = data.decode("utf-8-sig")
            if suffix == ".json":
                conversations = _json(text)
            elif suffix == ".jsonl":
                conversations = _codex(text, allow_partial)
            elif suffix in (".md", ".markdown"):
                conversations = _markdown(filename, text)
            else:
                raise ImportFailure("Unsupported file format; use JSON, JSONL, Markdown or ChatGPT ZIP")
        for conversation in conversations:
            conversation.source_identity = source_identity or conversation.source_identity or conversation.source
        return conversations
    except ImportFailure:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile, RuntimeError, ValidationError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ImportFailure("Invalid source data or timestamp") from None
