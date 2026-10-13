import json
import httpx
import pytest
from ai_helpers import make_client, source, extraction, run_job, latest_job, provider_response


def test_unconfigured_job_is_visible_and_configuration_wakes_it(tmp_path):
    with make_client(tmp_path, configured=False) as client:
        c = source(client)
        result = run_job(client)
        assert result.status_code == 200
        assert result.json()["status"] == "failed"
        assert result.json()["error_kind"] == "configuration_required"
        assert result.json()["attempts"] == 0
        client.post("/api/settings", json={"base_url": "https://provider.test/v1", "chat_model": "test-chat"})
        assert latest_job(client)["status"] == "queued"


def test_duplicate_processing_preserves_edited_derived_items(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        client.app.state.provider_transport = httpx.MockTransport(lambda request: provider_response(extraction(c["messages"][0])))
        job = latest_job(client)
        assert run_job(client, job).status_code == 200
        items = client.get("/api/knowledge").json()["items"]
        assert len(items) == 1
        client.patch("/api/knowledge/" + items[0]["id"], json={"title": "用户编辑"})
        assert run_job(client, job).json()["status"] == "completed"
        assert client.get("/api/knowledge").json()["items"][0]["title"] == "用户编辑"
        assert len(client.get("/api/memories").json()["items"]) == 1


def test_message_edit_during_provider_call_discards_stale_result(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        job = latest_job(client)
        def handler(request):
            client.app.state.repository.append_messages(c["id"], [{"id": "u1", "role": "user", "content": "我偏好英文。"}])
            return provider_response(extraction(c["messages"][0]))
        client.app.state.provider_transport = httpx.MockTransport(handler)
        result = run_job(client, job)
        assert result.status_code == 200
        assert result.json()["disposition"] == "superseded"
        assert client.get("/api/memories").json()["items"] == []


def test_long_history_chunks_cover_every_character_and_all_branches(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return provider_response({"knowledge": [], "memories": [], "reviews": []})
    with make_client(tmp_path, handler) as client:
        text = "start-" + "长" * 22000 + "-end"
        c = source(client, text)
        client.post("/api/conversations/" + c["id"] + "/messages", json={"messages": [
            {"id": "branch-a", "role": "assistant", "content": "branch-A", "parent_id": "u1"},
            {"id": "branch-b", "role": "assistant", "content": "branch-B", "parent_id": "u1"}]})
        assert run_job(client).status_code == 200
        chunks = [part for request in requests for part in json.loads(request["messages"][1]["content"])["messages"]]
        reconstructed = "".join(part["content"] for part in chunks if part["external_id"] == "u1")
        assert reconstructed == text
        assert {part["content"] for part in chunks if part["external_id"].startswith("branch-")} == {"branch-A", "branch-B"}
        assert all("branch_leaf_ids" in part and "version" in part for part in chunks)
        assert all(len(request["messages"][1]["content"]) <= 14000 for request in requests)


def test_demo_job_skips_provider_explicitly(tmp_path):
    def forbidden(request):
        raise AssertionError("demo must not call provider")
    with make_client(tmp_path, forbidden) as client:
        client.post("/api/demo")
        result = run_job(client)
        assert result.status_code == 200
        assert result.json()["disposition"] == "synthetic_skipped"


def test_interrupted_running_job_recovers_and_old_lease_cannot_commit(tmp_path):
    with make_client(tmp_path) as client:
        source(client)
        job = latest_job(client)
        service = getattr(client.app.state, "jobs", None)
        assert service is not None
        claim = service.claim(job["id"])
        assert claim["status"] == "running"
        assert service.claim(job["id"]) is None
        service.recover(now="2099-01-01T00:00:00+00:00")
        assert latest_job(client)["status"] == "queued"
        assert service.finish(claim, [], disposition="extracted") is False
        assert client.post("/api/jobs/" + job["id"] + "/retry").status_code == 200


def test_retries_are_bounded_and_have_backoff(tmp_path):
    with make_client(tmp_path, lambda request: provider_response(None, 503)) as client:
        source(client)
        service = getattr(client.app.state, "jobs", None)
        assert service is not None
        for _ in range(3):
            result = run_job(client)
            assert result.status_code == 200
            if result.json()["status"] == "queued":
                assert result.json()["next_attempt_at"] is not None
                assert service.claim(latest_job(client)["id"]) is None
        assert result.json()["status"] == "failed"
        assert result.json()["attempts"] == 3
        assert service.claim(latest_job(client)["id"]) is None
        retried = client.post("/api/jobs/" + latest_job(client)["id"] + "/retry")
        assert retried.json()["attempts"] == 0


def test_stale_confirmed_memory_is_excluded_from_future_context(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        m = client.post("/api/memories", json={"category": "preference", "content": "中文", "status": "confirmed",
            "evidence": [{"message_id": c["messages"][0]["id"], "quote": "中文"}]}).json()
        client.post("/api/conversations/" + c["id"] + "/messages", json={"messages": [{"id": "u1", "role": "user", "content": "英文"}]})
        assert client.get("/api/memories/context").json()["items"] == []
        assert client.get("/api/memories/" + m["id"]).json()["evidence"][0]["stale"] is True


def test_incremental_jobs_only_send_new_or_edited_message_versions(tmp_path):
    sent = []
    def handler(request):
        sent.extend(json.loads(json.loads(request.content)["messages"][1]["content"])["messages"])
        return provider_response({"knowledge": [], "memories": [], "reviews": []})
    with make_client(tmp_path, handler) as client:
        c = source(client)
        assert run_job(client).status_code == 200
        sent.clear()
        client.post("/api/conversations/" + c["id"] + "/messages", json={"messages": [{"id": "u2", "role": "user", "content": "我喜欢Python。"}]})
        assert run_job(client).status_code == 200
        assert [m["external_id"] for m in sent] == ["u2"]
        sent.clear()
        client.post("/api/conversations/" + c["id"] + "/messages", json={"messages": [{"id": "u1", "role": "user", "content": "我偏好英文。"}]})
        assert run_job(client).status_code == 200
        assert [(m["external_id"], m["version"]) for m in sent] == [("u1", 2)]


def test_exact_memory_merge_preserves_rejected_state_edits_expiry_and_history(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        m = client.post("/api/memories", json={"content": "我偏好中文。", "category": "preference", "subject": "语言",
            "status": "rejected", "expires_at": "2030-01-01T00:00:00Z"}).json()
        client.patch("/api/memories/" + m["id"], json={"status": "expired"})
        before = client.get("/api/memories/" + m["id"]).json()
        client.app.state.provider_transport = httpx.MockTransport(lambda request: provider_response(extraction(c["messages"][0])))
        assert run_job(client).json()["status"] == "completed"
        after = client.get("/api/memories/" + m["id"]).json()
        assert after["content"] == before["content"] and after["status"] == "expired"
        assert after["expires_at"] == before["expires_at"]
        assert after["history"][:len(before["history"])] == before["history"]
        assert len(after["evidence"]) == 1
        assert len(client.get("/api/memories").json()["items"]) == 1


def test_lifespan_worker_processes_and_stops_cleanly(tmp_path):
    import time
    with make_client(tmp_path, lambda request: provider_response({"knowledge": [], "memories": [], "reviews": []}), start_worker=True) as client:
        source(client)
        assert client.get("/api/status").json()["worker_running"] is True
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and latest_job(client)["status"] != "completed":
            time.sleep(0.01)
        assert latest_job(client)["status"] == "completed"
        worker = client.app.state.jobs.thread
    assert not worker.is_alive()
    assert client.app.state.worker_running is False


def test_provider_request_bounds_include_large_metadata_and_escaped_text(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        return provider_response({"knowledge": [], "memories": [], "reviews": []})
    with make_client(tmp_path, handler) as client:
        huge_source, huge_id = "source-" + "S" * 100000, "external-" + "E" * 100000
        text = "start" + "\x00\\\"长" * 5000 + "end"
        c = client.post("/api/conversations", json={"source": huge_source, "title": "T" * 100000,
            "messages": [{"id": huge_id, "role": "user", "content": text}]}).json()
        result = run_job(client)
        assert result.status_code == 200 and result.json()["status"] == "completed"
        parts = []
        for request in requests:
            assert len(request.content) <= 65536
            body = json.loads(request.content)
            raw_source = body["messages"][1]["content"]
            assert len(raw_source.encode("utf-8")) <= 14000
            supplied = json.loads(raw_source)
            assert supplied["conversation_id"] == c["id"]
            assert len(supplied["source"]) <= 200
            parts.extend(supplied["messages"])
        assert requests and "".join(part["content"] for part in parts) == text
        assert all(part["id"] == c["messages"][0]["id"] for part in parts)
        assert all(len(part["external_id"]) <= 200 for part in parts)
        saved = client.get("/api/conversations/" + c["id"]).json()
        assert saved["source"] == huge_source and saved["title"] == "T" * 100000
        assert saved["messages"][0]["external_id"] == huge_id and saved["messages"][0]["content"] == text


@pytest.mark.parametrize("text", ["", " \t\n "])
def test_empty_text_job_skips_provider_and_later_edit_is_processed(tmp_path, text):
    calls = []
    with make_client(tmp_path, lambda request: calls.append(request) or provider_response({"knowledge": [], "memories": [], "reviews": []})) as client:
        c = source(client, text)
        response = run_job(client)
        assert response.json()["disposition"] == "no_new_text"
        assert response.json()["attempts"] == 0
        assert response.json()["result"] == {"knowledge": 0, "memories": 0, "reviews": 0, "processed_messages": 0}
        assert calls == []
        client.post("/api/conversations/" + c["id"] + "/messages", json={"messages": [{"id": "u1", "role": "user", "content": "我偏好中文。"}]})
        assert run_job(client).json()["disposition"] == "extracted"
        assert len(calls) == 1


@pytest.mark.parametrize("status", ["confirmed", "candidate", "rejected", "expired", "superseded"])
def test_memory_current_proof_renews_without_losing_history_or_reactivating_status(tmp_path, status):
    requests = []
    with make_client(tmp_path) as client:
        c = source(client, "I prefer Python.")
        def handler(request):
            body = json.loads(request.content)
            if "response_format" in body:
                current = client.app.state.repository.get_conversation(c["id"])
                message = next(message for message in current["messages"] if message["external_id"] == "u1")
                return provider_response(extraction(message, knowledge=[], reviews=[]))
            requests.append(body)
            return provider_response("reply")
        client.app.state.provider_transport = httpx.MockTransport(handler)
        assert run_job(client).json()["status"] == "completed"
        memory = client.get("/api/memories").json()["items"][0]
        client.patch("/api/memories/" + memory["id"], json={"status": status, "expires_at": "2035-01-01T00:00:00Z"})
        before = client.get("/api/memories/" + memory["id"]).json()
        client.post("/api/conversations/" + c["id"] + "/messages", json={"messages": [{"id": "u1", "role": "user", "content": "I prefer Python.", "raw": {"edited": True}}]})
        assert client.get("/api/memories/context").json()["items"] == []
        assert run_job(client).json()["status"] == "completed"
        after = client.get("/api/memories/" + memory["id"]).json()
        assert after["status"] == status and after["content"] == before["content"]
        assert after["expires_at"] == before["expires_at"]
        assert after["history"][:len(before["history"])] == before["history"]
        assert [(proof["message_version"], proof["stale"]) for proof in after["evidence"]] == [(1, True), (2, False)]
        active = client.get("/api/memories/context").json()["items"]
        hits = client.get("/api/search", params={"q": "Python", "entity_type": "memory"}).json()["items"]
        if status == "confirmed":
            assert [item["id"] for item in active] == [memory["id"]]
            assert active[0]["evidence"] == [after["evidence"][1]]
            assert hits[0]["evidence"] == active[0]["evidence"]
            reply = client.post("/api/chat", json={"content": "hello", "client_turn_id": "renewed-proof"}).json()
            assert reply["used_context"]["memory_ids"] == [memory["id"]]
            assert reply["used_context"]["evidence"] == active[0]["evidence"]
            blocks = json.loads(requests[0]["messages"][0]["content"].split("\n", 1)[1])
            assert blocks[0]["evidence"] == active[0]["evidence"]
        else:
            assert active == [] and hits == []
        archive = client.get("/api/export").json()["memories"][0]
        assert len(archive["evidence"]) == 2
