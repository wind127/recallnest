import asyncio
import json
import os
import sys

from mcp import Client, StdioServerParameters, stdio_client
from fastapi.testclient import TestClient
import pytest

from recallnest.app import create_app
from recallnest.mcp_server import MAX_RESULT_BYTES, MCPService, build_server, encoded_size
from recallnest.repository import Repository


def test_mcp_candidate_only_strict_writes_and_text_search(tmp_path):
    service = MCPService(tmp_path)
    submitted = service.submit({"source": "synthetic-mcp", "external_id": "s", "title": "Synthetic", "messages": [{"id": "u", "role": "user", "content": "synthetic preference"}]})
    repo = Repository(tmp_path / "recallnest.sqlite3")
    message = repo.get_conversation(submitted["conversation_ids"][0])["messages"][0]
    memory = service.remember({"content": "synthetic preference", "category": "preference", "status": "confirmed", "evidence": [{"message_id": message["id"], "message_version": 1, "quote": "synthetic preference"}]})
    assert memory["status"] == "candidate" and service.context()["total"] == 0
    assert service.remember({"content": "other", "category": "goal", "status": "rejected"})["status"] == "candidate"
    assert service.search("synthetic")["mode"] == "text"
    with pytest.raises(ValueError):
        service.submit({"messages": [{"role": "invalid", "content": "x"}]})
    with pytest.raises(ValueError):
        service.submit({"unknown": True})
    with pytest.raises(ValueError):
        service.remember({"content": "x", "category": "goal", "unknown": True})


def test_mcp_fetch_pages_full_text_and_historical_evidence(tmp_path):
    service = MCPService(tmp_path)
    text = "synthetic "+ "学习" * 7000
    result = service.submit({"source": "synthetic", "external_id": "s", "messages": [{"id": "u", "role": "user", "content": text}]})
    repo = service.repo
    conversation = repo.get_conversation(result["conversation_ids"][0])
    message = conversation["messages"][0]
    page = service.fetch("message", message["id"], limit=1000)
    assert page["source_id"] == message["id"] and page["version"] == 1
    assert page["untrusted_source"] is True and page["total"] == len(text)
    reconstructed, offset = "", 0
    while offset is not None:
        page = service.fetch("message", message["id"], version=1, offset=offset, limit=1000)
        reconstructed += page["text"]
        offset = page["next_offset"]
    assert reconstructed == text
    repo.append_messages(conversation["id"], [{"id": "u", "role": "user", "content": "edited"}])
    assert service.fetch("message", message["id"], version=1)["text"].startswith("synthetic")
    assert service.fetch("message", message["id"])["text"] == "edited"
    assert service.fetch("conversation", conversation["id"], version=1, limit=100)["version"] == 1
    knowledge = repo.create_knowledge({"title": "Synthetic", "body": text, "evidence": [{"message_id": message["id"], "message_version": 1, "quote": "synthetic"}]})
    assert service.fetch("knowledge", knowledge["id"], limit=30)["total"] > 30
    with pytest.raises(ValueError):
        service.fetch("message", message["id"], limit=9000)
    with pytest.raises(ValueError):
        service.fetch("message", message["id"], version=0)


@pytest.mark.parametrize("limit", [7, 8000])
def test_mcp_message_pages_preserve_nul_unicode_and_escapes_in_every_version(tmp_path, limit):
    service = MCPService(tmp_path)
    repeats = 1 if limit == 7 else 700
    original = 'synthetic before\0synthetic after 中文 🐦 "quoted" \\ slash\n\t' * repeats
    current = 'updated\0tail 🐦 中文 \\ "quoted"\n\t' * repeats
    submitted = service.submit({"source": "synthetic-nul", "external_id": "nul", "messages": [
        {"id": "u", "role": "user", "content": original}]})
    conversation_id = submitted["conversation_ids"][0]
    message_id = service.repo.get_conversation(conversation_id)["messages"][0]["id"]
    service.repo.append_messages(conversation_id, [{"id": "u", "role": "user", "content": current}])

    for requested_version, expected, actual_version, stale in ((None, current, 2, False), (1, original, 1, True)):
        pieces, offset = [], 0
        while offset is not None:
            page = service.fetch("message", message_id, version=requested_version, offset=offset, limit=limit)
            assert page["version"] == actual_version and page["stale"] is stale
            assert page["offset"] == offset and page["limit"] == limit
            assert page["total"] == len(expected)
            assert page["text"] == expected[offset:offset + len(page["text"])]
            assert encoded_size(page) <= MAX_RESULT_BYTES
            pieces.append(page["text"])
            next_offset = offset + len(page["text"])
            assert page["next_offset"] == (next_offset if next_offset < len(expected) else None)
            assert next_offset > offset
            offset = page["next_offset"]
            requested_version = page["version"]
        assert "".join(pieces) == expected

    with TestClient(create_app(tmp_path, start_worker=False), base_url="http://127.0.0.1") as rest:
        archived = rest.get(f"/api/conversations/{conversation_id}").json()["messages"][0]
        assert archived["content"] == current
        assert [version["content"] for version in archived["versions"]] == [original, current]
        exported = rest.get("/api/export").json()["conversations"][0]["messages"][0]
        assert exported["content"] == current
        assert [version["content"] for version in exported["versions"]] == [original, current]


def large_confirmed_memory(service, *, suffix=""):
    submitted = service.submit({"source": "synthetic-large-memory", "external_id": "proof", "messages": [
        {"id": "u", "role": "user", "content": "🐦" * 250}]})
    message = service.repo.get_conversation(submitted["conversation_ids"][0])["messages"][0]
    return service.repo.create_memory({"content": "🐦" * 1000 + suffix, "subject": "🐦" * 200,
        "category": "background", "status": "confirmed", "evidence": [
            {"message_id": message["id"], "message_version": 1, "quote": "🐦" * 250} for _ in range(5)]})


def fetch_all_memory_text(service, source_id):
    pieces, offset, version = [], 0, None
    while offset is not None:
        page = service.fetch("memory", source_id, version=version, offset=offset)
        assert encoded_size(page) <= MAX_RESULT_BYTES and page["version"] == 1
        assert page["text"] and (page["next_offset"] is None or page["next_offset"] > offset)
        pieces.append(page["text"])
        offset, version = page["next_offset"], page["version"]
    return "".join(pieces)


def test_mcp_context_keeps_large_memory_identity_and_marks_shortened_fields(tmp_path):
    service = MCPService(tmp_path)
    memory = large_confirmed_memory(service)
    page = service.context(offset=0, limit=1)
    assert page["items"] and page["items"][0]["id"] == memory["id"]
    assert page["offset"] == 0 and page["total"] == 1 and page["next_offset"] is None
    assert page["truncated"] is True and encoded_size(page) <= MAX_RESULT_BYTES
    projected = page["items"][0]
    assert projected["projection_truncated"] is True
    for field in ("content", "subject"):
        if projected[field] != memory[field]:
            assert projected[field + "_truncated"] is True
    assert len(projected["evidence"]) == 5
    for proof in projected["evidence"]:
        assert proof["stale"] is False and proof["message_version"] == 1
        assert proof["quote"] and memory["evidence"][0]["quote"].startswith(proof["quote"])
        if proof["quote"] != "🐦" * 250:
            assert proof["quote_truncated"] is True
    assert fetch_all_memory_text(service, projected["id"]) == memory["content"]
    assert service.repo.export_data()["memories"][0]["content"] == memory["content"]


def test_mcp_context_mixed_pages_reach_every_active_memory_once(tmp_path):
    service = MCPService(tmp_path)
    large_confirmed_memory(service)
    for index in range(8):
        service.repo.create_memory({"content": f"synthetic small {index}", "category": "goal", "status": "confirmed"})
    for status in ("candidate", "rejected", "expired", "superseded"):
        service.repo.create_memory({"content": f"synthetic inactive {status}", "category": "goal", "status": status})
    service.repo.create_memory({"content": "synthetic expired confirmation", "category": "goal", "status": "confirmed",
        "expires_at": "2000-01-01T00:00:00Z"})
    expected = [item["id"] for item in service.repo.active_memories()]
    seen, offset = [], 0
    while offset is not None:
        page = service.context(offset=offset, limit=3)
        assert encoded_size(page) <= MAX_RESULT_BYTES and page["total"] == len(expected)
        assert page["items"] and page["offset"] == offset
        seen.extend(item["id"] for item in page["items"])
        next_offset = offset + len(page["items"])
        assert page["next_offset"] == (next_offset if next_offset < len(expected) else None)
        assert next_offset > offset
        offset = page["next_offset"]
    assert seen == expected and len(seen) == 9


def test_mcp_search_keeps_single_large_hit_discoverable(tmp_path):
    service = MCPService(tmp_path)
    memory = large_confirmed_memory(service, suffix=" singularneedle")
    page = service.search("singularneedle", limit=1)
    assert len(page["items"]) == 1 and page["items"][0]["id"] == memory["id"]
    assert page["items"][0]["entity_type"] == "memory"
    assert page["truncated"] is True and page["items"][0]["projection_truncated"] is True
    assert encoded_size(page) <= MAX_RESULT_BYTES
    assert fetch_all_memory_text(service, page["items"][0]["id"]) == memory["content"]


def test_mcp_context_labels_subject_preview(tmp_path):
    service = MCPService(tmp_path)
    service.repo.create_memory({"content": "synthetic subject", "subject": "🐦" * 201,
        "category": "background", "status": "confirmed"})
    item = service.context()["items"][0]
    assert item["subject"] == "🐦" * 200 and item["subject_truncated"] is True


def test_mcp_search_labels_title_and_source_previews(tmp_path):
    service = MCPService(tmp_path)
    service.submit({"source": "🐦" * 121, "title": "🐦" * 201, "messages": [
        {"role": "user", "content": "syntheticpreviewneedle"}]})
    item = service.search("syntheticpreviewneedle")["items"][0]
    assert item["title"] == "🐦" * 200 and item["title_truncated"] is True
    assert item["source"] == "🐦" * 120 and item["source_truncated"] is True


def test_mcp_complete_response_bounds_and_context_paging_make_progress(tmp_path):
    from recallnest.mcp_server import MAX_RESULT_BYTES, encoded_size
    service = MCPService(tmp_path)
    result = service.submit({"source": "源" * 100000, "external_id": "id" * 100000, "title": "标题" * 100000,
                             "messages": [{"id": "external" * 100000, "role": "user", "content": "学习" * 10000}]})
    conversation = service.repo.get_conversation(result["conversation_ids"][0])
    message = conversation["messages"][0]
    proofs = [{"message_id": message["id"], "message_version": 1, "quote": "学习" * 1000}] * 20
    memory = service.repo.create_memory({"content": "学习" * 10000, "subject": "背景" * 100000, "category": "background", "status": "confirmed", "evidence": proofs})
    context = service.context()
    assert context["items"] and context["items"][0]["id"] == memory["id"]
    assert context["next_offset"] is None
    for response in (context, service.search("学习"), service.fetch("conversation", conversation["id"], limit=8000), service.fetch("memory", memory["id"], limit=8000)):
        assert encoded_size(response) <= MAX_RESULT_BYTES


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_mcp_sdk_large_context_is_bounded_and_fetch_recovers_source(tmp_path, mode):
    data_dir = tmp_path / "data"
    service = MCPService(data_dir)
    memory = large_confirmed_memory(service)

    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "recallnest", "mcp", "--data-dir", str(data_dir)],
            env={"PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"), "PYTHONUTF8": "1"})
        with (tmp_path / "stderr.txt").open("w", encoding="utf-8") as errlog:
            async with Client(stdio_client(params, errlog=errlog), mode=mode) as client:
                result = await client.call_tool("context", {"offset": 0, "limit": 1})
                assert not result.is_error
                page = result.structured_content
                assert encoded_size(page) <= MAX_RESULT_BYTES
                assert page["items"] and page["items"][0]["id"] == memory["id"]
                assert page["next_offset"] is None and page["truncated"] is True
                pieces, offset, version = [], 0, None
                while offset is not None:
                    fetched = await client.call_tool("fetch", {"kind": "memory", "source_id": page["items"][0]["id"], "offset": offset, "version": version})
                    assert not fetched.is_error and encoded_size(fetched.structured_content) <= MAX_RESULT_BYTES
                    chunk = fetched.structured_content
                    assert chunk["total"] == len(memory["content"]) and chunk["version"] == 1
                    assert chunk["text"] and (chunk["next_offset"] is None or chunk["next_offset"] > offset)
                    pieces.append(chunk["text"])
                    offset, version = chunk["next_offset"], chunk["version"]
                assert "".join(pieces) == memory["content"]
                proof = page["items"][0]["evidence"][0]
                source = await client.call_tool("fetch", {"kind": "message", "source_id": proof["message_id"], "version": proof["message_version"]})
                assert not source.is_error and source.structured_content["text"] == "🐦" * 250
    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_mcp_sdk_stdio_initialize_tools_read_write_errors_share_rest(tmp_path, mode):
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "recallnest", "mcp", "--data-dir", str(tmp_path / "data")], env={"PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1] / "src"), "PYTHONUTF8": "1"})
        with (tmp_path / "stderr.txt").open("w", encoding="utf-8") as errlog:
            async with Client(stdio_client(params, errlog=errlog), mode=mode) as client:
                tools = await client.list_tools()
                assert {tool.name for tool in tools.tools} == {"search", "fetch", "context", "submit", "remember"}
                result = await client.call_tool("submit", {"conversation": {"source": "synthetic-sdk", "external_id": "sdk", "title": "SDK", "messages": [{"role": "user", "content": "synthetic sdk content"}]}})
                assert not result.is_error
                source_id = result.structured_content["conversation_ids"][0]
                fetched = await client.call_tool("fetch", {"kind": "conversation", "source_id": source_id, "limit": 100})
                assert not fetched.is_error and fetched.structured_content["limit"] == 100
                found = await client.call_tool("search", {"query": "synthetic"})
                assert found.structured_content["items"]
                context = await client.call_tool("context", {})
                assert context.structured_content["items"] == []
                remembered = await client.call_tool("remember", {"memory": {"content": "synthetic goal", "category": "goal", "status": "confirmed"}})
                assert remembered.structured_content["status"] == "candidate"
                error = await client.call_tool("submit", {"conversation": {"unknown": True}})
                assert error.is_error
                missing = await client.call_tool("fetch", {"kind": "message", "source_id": "missing"})
                assert missing.is_error
        with TestClient(create_app(tmp_path / "data"), base_url="http://127.0.0.1") as rest:
            assert rest.get("/api/conversations").json()["items"][0]["id"] == source_id
            assert rest.get("/api/memories").json()["items"][0]["status"] == "candidate"
    asyncio.run(exercise())
