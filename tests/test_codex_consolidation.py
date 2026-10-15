import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from recallnest.app import create_app
from recallnest.cli import build_app, main
from recallnest.mcp_server import MCPService, MAX_RESULT_BYTES, encoded_size


EMPTY = {"knowledge": [], "memories": [], "reviews": []}


def submitted(service, text="我偏好中文。", **extra):
    return service.submit({"source": "codex-test", "external_id": "session", "messages": [
        {"id": "u1", "role": "user", "content": text}], **extra})["conversation_ids"][0]


def output_for(batch):
    part = batch["messages"][0]
    proof = {"message_id": part["id"], "message_version": part["version"], "quote": part["content"]}
    return {"knowledge": [{"title": "整理流程", "summary": "保留原文引用", "body": "通过来源核对整理结果。", "type": "topic", "tags": ["整理"], "evidence": [proof]}],
            "memories": [{"content": part["content"], "category": "preference", "subject": "语言", "evidence": [proof]}],
            "reviews": [{"question": "如何核对来源？", "answer": "检查原文引用。", "evidence": [proof]}]}


def test_codex_roundtrip_atomic_idempotent_and_shared_with_web(tmp_path, monkeypatch):
    monkeypatch.setattr("recallnest.ai.AIClient._post", lambda *a, **kw: pytest.fail("No provider calls allowed"))
    service = MCPService(tmp_path, local_only=True)
    cid = submitted(service)
    project = service.repo.create_project({"name": "synthetic project"})
    service.repo.update_conversation(cid, {"project_id": project["id"]})
    batch = service.consolidation.prepare(cid)
    assert service.consolidation.prepare(cid) == batch
    result = service.consolidation.complete(batch["batch_id"], output_for(batch))
    assert result["counts"] == {"knowledge": 1, "memories": 1, "reviews": 1, "processed_messages": 1}
    replay = service.consolidation.complete(batch["batch_id"], EMPTY)
    assert replay["replayed"] and replay["counts"] == result["counts"]
    assert MCPService(tmp_path).consolidation.prepare()["status"] == "idle"
    with TestClient(create_app(tmp_path, start_worker=True, allow_ai=False), base_url="http://127.0.0.1") as web:
        assert web.get("/api/status").json()["consolidation_mode"] == "codex"
        assert not web.get("/api/status").json()["worker_running"]
        knowledge = web.get("/api/knowledge").json()["items"]
        reviews = web.get("/api/reviews").json()["items"]
        memories = web.get("/api/memories").json()["items"]
        assert len(knowledge) == len(reviews) == len(memories) == 1
        assert knowledge[0]["project_id"] == reviews[0]["project_id"] == project["id"]
        assert knowledge[0]["source_context"]["conversation_id"] == cid
        assert memories[0]["status"] == "candidate" and service.context()["items"] == []
        web.patch("/api/memories/" + memories[0]["id"], json={"status": "confirmed"})
        assert len(service.context()["items"]) == 1
        assert web.get("/api/jobs").json()["items"][0]["disposition"] == "codex"
        assert web.post("/api/reviews/" + reviews[0]["id"] + "/grade", json={"grade": "good"}).status_code == 200
    assert service.search("整理")["items"]


@pytest.mark.parametrize("bad", ["quote", "version", "role", "question", "personal", "confirmed", "outside"])
def test_invalid_codex_output_writes_nothing_and_can_be_corrected(tmp_path, bad):
    service = MCPService(tmp_path)
    cid = submitted(service, "我偏好中文吗？" if bad == "question" else "我偏好中文。")
    if bad == "role":
        service.repo.append_messages(cid, [{"id": "u1", "role": "assistant", "content": "我偏好中文。"}])
    batch = service.consolidation.prepare(cid)
    output = output_for(batch)
    if bad == "quote": output["reviews"][0]["evidence"][0] = {**output["reviews"][0]["evidence"][0], "quote": "not present"}
    if bad == "version": output["reviews"][0]["evidence"][0] = {**output["reviews"][0]["evidence"][0], "message_version": 999}
    if bad == "personal": output["knowledge"][0]["body"] = "用户喜欢中文"
    if bad == "confirmed": output["memories"][0]["status"] = "confirmed"
    if bad == "outside": output["knowledge"][0]["evidence"][0] = {**output["knowledge"][0]["evidence"][0], "conversation_id": "other"}
    with pytest.raises(ValueError, match="Invalid consolidation"):
        service.consolidation.complete(batch["batch_id"], output)
    for table in ("knowledge", "memories", "reviews"):
        assert service.repo.export_data()[table] == []
    assert service.consolidation.prepare(cid) == batch
    service.consolidation.complete(batch["batch_id"], EMPTY)
    assert service.consolidation.prepare(cid)["status"] == "idle"


def test_restart_long_unicode_branches_incremental_and_source_edit(tmp_path):
    service = MCPService(tmp_path)
    text = "🐦\x00长" * 2200
    cid = submitted(service, text)
    service.repo.append_messages(cid, [{"id": "a", "role": "assistant", "content": "branch A", "parent_id": "u1"},
                                        {"id": "b", "role": "assistant", "content": "branch B", "parent_id": "u1"}])
    pieces = {}
    while True:
        # A new service on every batch exercises durable checkpoints and SDK restarts.
        service = MCPService(tmp_path, local_only=True)
        batch = service.consolidation.prepare()
        assert encoded_size(batch) <= MAX_RESULT_BYTES
        if batch["status"] == "idle": break
        part = batch["messages"][0]
        pieces.setdefault(part["id"], []).append(part["content"])
        assert part["offset"] == len("".join(pieces[part["id"]][:-1]))
        service.consolidation.complete(batch["batch_id"], EMPTY)
    assert sorted("".join(p) for p in pieces.values()) == sorted([text, "branch A", "branch B"])
    service.repo.append_messages(cid, [{"id": "u2", "role": "user", "content": "new message"}])
    batch = service.consolidation.prepare(cid)
    assert batch["messages"][0]["content"] == "new message"
    service.repo.append_messages(cid, [{"id": "a", "role": "assistant", "content": "edited branch"}])
    with pytest.raises(ValueError, match="Source changed"):
        service.consolidation.complete(batch["batch_id"], EMPTY)
    fresh = service.consolidation.prepare(cid)
    assert fresh["batch_id"] != batch["batch_id"]
    assert fresh["messages"][0]["content"] == "edited branch"
    assert fresh["messages"][0]["version"] == 2


def test_concurrent_completion_preserves_one_copy(tmp_path):
    service = MCPService(tmp_path)
    cid = submitted(service)
    batch = service.consolidation.prepare(cid)
    def finish(_):
        return MCPService(tmp_path).consolidation.complete(batch["batch_id"], output_for(batch))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finish, range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert len(service.repo.list_knowledge()) == 1


def test_codex_wont_race_provider_and_local_only_rejects_embeddings(tmp_path):
    service = MCPService(tmp_path, local_only=True)
    cid = submitted(service)
    with pytest.raises(ValueError, match="disabled"):
        service.search("test", semantic=True)
    from recallnest.jobs import JobService
    jobs = JobService(service.repo, None)
    claim = jobs.claim()
    with pytest.raises(ValueError, match="Provider job is running"):
        service.consolidation.prepare(cid)
    jobs.recover(now="2099-01-01T00:00:00+00:00")
    batch = service.consolidation.prepare(cid)
    jobs.claim()
    with pytest.raises(ValueError, match="Provider job is running"):
        service.consolidation.complete(batch["batch_id"], EMPTY)


def test_codex_settles_metadata_only_revisions_empty_sources_and_demo_jobs(tmp_path):
    from recallnest.jobs import JobService
    service = MCPService(tmp_path, local_only=True)
    cid = submitted(service)
    batch = service.consolidation.prepare()
    service.consolidation.complete(batch["batch_id"], EMPTY)
    submitted(service, title="Title change, same message version")
    empty = service.submit({"source": "empty", "messages": []})["conversation_ids"][0]
    demo = service.submit({"source": "demo:sample", "messages": [{"role": "user", "content": "synthetic demo"}]})["conversation_ids"][0]
    assert service.consolidation.prepare()["status"] == "idle"
    jobs = JobService(service.repo, None).list()
    assert all(j["status"] == "completed" for j in jobs)
    assert next(j for j in jobs if j["conversation_id"] == demo)["disposition"] == "synthetic_skipped"
    assert next(j for j in jobs if j["conversation_id"] == empty)["disposition"] == "codex"
    assert service.repo.get_conversation(cid)["messages"][0]["version"] == 1


def test_codex_partial_progress_does_not_hide_an_edited_message_or_rewrite_entities(tmp_path):
    service = MCPService(tmp_path)
    cid = submitted(service, "x" * 6000)
    first = service.consolidation.prepare(cid)
    output = output_for(first)
    output["memories"] = []
    service.consolidation.complete(first["batch_id"], output)
    knowledge = service.repo.list_knowledge()[0]
    service.repo.update_knowledge(knowledge["id"], {"title": "User edit"})
    tail = service.consolidation.prepare(cid)
    assert tail["messages"][0]["offset"] > 0
    service.repo.append_messages(cid, [{"id": "u1", "role": "user", "content": "changed source"}])
    with pytest.raises(ValueError, match="Source changed"):
        service.consolidation.complete(tail["batch_id"], EMPTY)
    revised = service.consolidation.prepare(cid)
    assert revised["messages"][0]["offset"] == 0 and revised["messages"][0]["version"] == 2
    service.consolidation.complete(revised["batch_id"], EMPTY)
    assert service.consolidation.prepare(cid)["status"] == "idle"
    assert service.repo.get_knowledge(knowledge["id"])["title"] == "User edit"
    assert service.repo.get_knowledge(knowledge["id"])["evidence"][0]["stale"]


def test_no_ai_blocks_model_endpoints_even_with_saved_key(tmp_path, monkeypatch):
    from recallnest.provider_settings import ConnectionSettings
    from recallnest.config import get_settings
    ConnectionSettings(get_settings(tmp_path)).save({"base_url": "https://provider.test/v1", "chat_model": "fake", "embedding_model": "fake", "api_key": "synthetic-only"})
    monkeypatch.setattr("recallnest.ai.AIClient._post", lambda *a, **kw: pytest.fail("No provider calls allowed"))
    with TestClient(build_app(tmp_path, allow_ai=False), base_url="http://127.0.0.1") as web:
        assert web.post("/api/settings/test").status_code == 409
        assert web.post("/api/search/reindex").status_code == 409
        assert web.get("/api/search?q=test&semantic=true").status_code == 200  # Local fallback.
        submitted(MCPService(tmp_path))
        assert web.post("/api/jobs/run").json()["job"]["error_kind"] == "configuration_required"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_sdk_codex_host_reasoning_handoff_without_model_api(tmp_path, mode):
    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=["-m", "recallnest", "mcp", "--local-only", "--data-dir", str(tmp_path / "data")],
            env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONUTF8": "1"})
        with (tmp_path / "stderr.txt").open("w", encoding="utf-8") as errlog:
            async with Client(stdio_client(params, errlog=errlog), mode=mode) as client:
                submitted_result = await client.call_tool("submit", {"conversation": {"source": "sdk", "external_id": "sdk-session", "messages": [{"id": "u1", "role": "user", "content": "我偏好中文。"}]}})
                cid = submitted_result.structured_content["conversation_ids"][0]
                prepared = await client.call_tool("prepare_consolidation", {"conversation_id": cid})
                assert not prepared.is_error
                batch = prepared.structured_content
                done = await client.call_tool("complete_consolidation", {"batch_id": batch["batch_id"], "output": output_for(batch)})
                assert not done.is_error and done.structured_content["counts"]["knowledge"] == 1
                replay = await client.call_tool("complete_consolidation", {"batch_id": batch["batch_id"], "output": output_for(batch)})
                assert not replay.is_error and replay.structured_content["replayed"]
                idle = await client.call_tool("prepare_consolidation", {})
                assert idle.structured_content["status"] == "idle"
                invalid = await client.call_tool("complete_consolidation", {"batch_id": "missing", "output": EMPTY})
                assert invalid.is_error
    asyncio.run(exercise())
