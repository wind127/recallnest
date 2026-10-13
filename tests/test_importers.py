import io
import json
import zipfile
import pytest
from recallnest.importers import ImportFailure, parse_upload


def zip_bytes(members):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return out.getvalue()


def chatgpt():
    return [{"id": "g1", "title": "Branches", "current_node": "b", "mapping": {
        "root": {"parent": None, "children": ["u"], "message": None},
        "u": {"parent": "root", "children": ["a", "b"], "message": {"id": "u", "author": {"role": "user"}, "content": {"parts": ["你好"]}, "create_time": 1700000000}},
        "a": {"parent": "u", "children": [], "message": {"id": "a", "author": {"role": "assistant"}, "content": {"parts": ["branch A"]}}},
        "b": {"parent": "u", "children": [], "message": {"id": "b", "author": {"role": "assistant"}, "content": {"parts": ["branch B"]}}}
    }}]


def test_chatgpt_preserves_graph_and_current_node():
    conversation = parse_upload("conversations.json", json.dumps(chatgpt()).encode())[0]
    assert conversation.source == "chatgpt"
    assert conversation.current_node == "b"
    assert {m.id: m.parent_id for m in conversation.messages} == {"u": None, "a": "u", "b": "u"}
    assert conversation.raw["mapping"]["root"]["children"] == ["u"]


def test_zip_reads_nested_conversations_without_extraction():
    payload = zip_bytes({"export/conversations.json": json.dumps(chatgpt()), "readme.txt": "ignore"})
    assert len(parse_upload("export.zip", payload)) == 1


@pytest.mark.parametrize("name", ["../conversations.json", "/conversations.json", "C:/conversations.json", "folder\\..\\conversations.json"])
def test_zip_rejects_traversal(name):
    with pytest.raises(ImportFailure, match="path"):
        parse_upload("export.zip", zip_bytes({name: "[]"}))


def test_zip_and_upload_are_bounded():
    with pytest.raises(ImportFailure, match="upload"):
        parse_upload("x.json", b"[]" * 10, max_upload_bytes=2)
    with pytest.raises(ImportFailure, match="expanded"):
        parse_upload("x.zip", zip_bytes({"conversations.json": " " * 30}), max_zip_bytes=10)
    with pytest.raises(ImportFailure, match="members"):
        parse_upload("x.zip", zip_bytes({"a": "", "b": ""}), max_zip_members=1)


def test_codex_response_and_event_representations_are_deduplicated():
    lines = [
        {"type": "session_meta", "payload": {"id": "s1", "timestamp": "2026-10-14T00:00:00Z"}},
        {"type": "event_msg", "timestamp": "2026-10-14T00:00:01Z", "payload": {"type": "user_message", "message": "学 SQLite"}},
        {"type": "response_item", "timestamp": "2026-10-14T00:00:01Z", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "学 SQLite"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "先建表"}]}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "先建表"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "学 SQLite"}},
    ]
    conv = parse_upload("session.jsonl", "\n".join(json.dumps(line) for line in lines).encode())[0]
    assert conv.external_id == "s1"
    assert [m.content for m in conv.messages] == ["学 SQLite", "先建表", "学 SQLite"]


def test_malformed_complete_jsonl_line_reports_line_number():
    with pytest.raises(ImportFailure, match="line 2"):
        parse_upload("s.jsonl", b'{"type":"session_meta","payload":{"id":"s"}}\nnot json\n')


def test_partial_trailing_jsonl_can_be_explicitly_ignored():
    data = b'{"type":"session_meta","payload":{"id":"s"}}\n{"type":'
    with pytest.raises(ImportFailure):
        parse_upload("s.jsonl", data)
    assert parse_upload("s.jsonl", data, allow_partial=True)[0].external_id == "s"


def test_uniform_json_and_markdown_note(sample_bytes):
    assert parse_upload("generic.json", sample_bytes)[0].messages[1].parent_id == "u1"
    conv = parse_upload("notes.md", "# 我的笔记\n中文学习 100%".encode())[0]
    assert conv.messages[0].role == "user"
    assert "中文学习" in conv.messages[0].content


def test_markdown_roles():
    conv = parse_upload("chat.md", b"# User\nQuestion\n## Assistant\nAnswer\n## User\nAgain")[0]
    assert [m.role for m in conv.messages] == ["user", "assistant", "user"]
    assert conv.messages[1].parent_id == conv.messages[0].id


@pytest.mark.parametrize("filename,data", [("x.bin", b"x"), ("x.json", b'{"unexpected": true}'), ("x.json", b"{"), ("x.jsonl", b'{"type":"unknown"}\n')])
def test_unknown_formats_are_errors(filename, data):
    with pytest.raises(ImportFailure):
        parse_upload(filename, data)


def test_non_text_chatgpt_content_stays_in_raw_archive():
    records = chatgpt()
    image = {"content_type": "image_asset_pointer", "asset_pointer": "file-service://synthetic-image"}
    records[0]["mapping"]["u"]["message"]["content"]["parts"].append(image)
    conv = parse_upload("conversations.json", json.dumps(records).encode())[0]
    assert conv.messages[0].content == "你好"
    assert conv.metadata["non_text_blocks"] == 1
    assert conv.raw["mapping"]["u"]["message"]["content"]["parts"][-1] == image


def test_codex_raw_tool_calls_are_archived():
    records = [{"type": "session_meta", "payload": {"id": "s"}}, {"type": "response_item", "payload": {"type": "function_call", "name": "synthetic_tool", "arguments": "{}"}}]
    conv = parse_upload("s.jsonl", "\n".join(json.dumps(r) for r in records).encode())[0]
    assert conv.raw["records"] == records and conv.messages == []


def codex_same_text_record(kind, *, message_id=None, timestamp=None):
    payload = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "repeat"}]} if kind == "response_item" else {"type": "user_message", "message": "repeat"}
    if message_id is not None:
        payload["id"] = message_id
    record = {"type": kind, "payload": payload}
    if timestamp is not None:
        record["timestamp"] = timestamp
    return record


def parse_codex_records(records):
    return parse_upload("session.jsonl", "\n".join(json.dumps(r) for r in [{"type": "session_meta", "payload": {"id": "s"}}, *records]).encode())[0]


def test_codex_dedup_finishes_one_pair_then_retains_later_same_text_turn():
    conv = parse_codex_records([
        codex_same_text_record("response_item", message_id="first", timestamp="2026-10-14T00:00:01Z"),
        codex_same_text_record("event_msg", message_id="first", timestamp="2026-10-14T00:00:01Z"),
        codex_same_text_record("response_item", message_id="second", timestamp="2026-10-14T00:00:02Z"),
        codex_same_text_record("event_msg", message_id="second", timestamp="2026-10-14T00:00:02Z"),
    ])
    assert [m.id for m in conv.messages] == ["first", "second"]
    assert len(conv.raw["records"]) == 5


def test_codex_dedup_without_identifiers_still_consumes_only_one_pair():
    conv = parse_codex_records([codex_same_text_record(kind) for kind in ("event_msg", "response_item", "event_msg", "response_item")])
    assert len(conv.messages) == 2


@pytest.mark.parametrize("field,first,second", [("message_id", "first", "second"), ("timestamp", "2026-10-14T00:00:01Z", "2026-10-14T00:00:02Z")])
def test_codex_distinct_explicit_turn_identity_prevents_dedup(field, first, second):
    conv = parse_codex_records([codex_same_text_record("response_item", **{field: first}), codex_same_text_record("event_msg", **{field: second})])
    assert len(conv.messages) == 2


def test_uniform_zero_epoch_timestamp_survives_fallback_and_export_fields():
    data = {"source": "uniform", "created_at": 0, "updated_at": 0,
            "messages": [{"role": "user", "content": "epoch", "timestamp": 0, "created_at": 1700000000}]}
    conv = parse_upload("zero.json", json.dumps(data).encode())[0]
    assert conv.created_at == conv.updated_at == conv.messages[0].timestamp == "1970-01-01T00:00:00+00:00"


def test_chatgpt_and_codex_zero_epoch_dates_are_preserved():
    data = chatgpt()
    data[0]["create_time"] = data[0]["update_time"] = data[0]["mapping"]["u"]["message"]["create_time"] = 0
    conv = parse_upload("conversations.json", json.dumps(data).encode())[0]
    assert conv.created_at == conv.updated_at == conv.messages[0].timestamp == "1970-01-01T00:00:00+00:00"
    codex = parse_upload("s.jsonl", b'{"type":"session_meta","payload":{"id":"s","timestamp":0}}\n{"type":"event_msg","timestamp":0,"payload":{"type":"user_message","message":"epoch"}}')[0]
    assert codex.created_at == codex.messages[0].timestamp == "1970-01-01T00:00:00+00:00"
