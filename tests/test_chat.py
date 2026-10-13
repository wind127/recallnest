import json
import httpx
import pytest
from ai_helpers import make_client, source, provider_response


def test_chat_persists_turns_and_reports_confirmed_valid_context(tmp_path):
    requests = []
    with make_client(tmp_path, lambda request: requests.append(json.loads(request.content)) or provider_response("你好")) as client:
        c = source(client)
        evidence = [{"message_id": c["messages"][0]["id"], "quote": "中文"}]
        m = client.post("/api/memories", json={"content": "中文", "category": "preference", "status": "confirmed", "evidence": evidence}).json()
        client.post("/api/memories", json={"content": "do-not-use", "category": "preference"})
        k = client.post("/api/knowledge", json={"title": "中文", "body": "中文学习", "evidence": evidence}).json()
        result = client.post("/api/chat", json={"conversation_id": c["id"], "content": "中文怎么学？", "client_turn_id": "turn-1"})
        assert result.status_code == 200
        data = result.json()
        assert data["assistant_message"]["content"] == "你好"
        assert data["assistant_message"]["parent_id"] == data["user_message"]["id"]
        assert data["used_context"]["memory_ids"] == [m["id"]]
        assert data["used_context"]["knowledge_ids"] == [k["id"]]
        assert "do-not-use" not in json.dumps(requests)
        assert "secret-key" not in json.dumps(requests)
        again = client.post("/api/chat", json={"conversation_id": c["id"], "content": "中文怎么学？", "client_turn_id": "turn-1"})
        assert again.json()["assistant_message"]["id"] == data["assistant_message"]["id"]
        assert len(requests) == 1


def test_chat_failure_keeps_user_and_ids_without_fake_assistant(tmp_path):
    with make_client(tmp_path, lambda request: provider_response(None, 502)) as client:
        c = source(client)
        response = client.post("/api/chat", json={"conversation_id": c["id"], "content": "hello", "client_turn_id": "retry-1"})
        assert response.status_code == 502
        assert response.json()["assistant_message"] is None
        user_id = response.json()["user_message"]["id"]
        assert "secret-key" not in response.text
        client.app.state.provider_transport = httpx.MockTransport(lambda request: provider_response("fixed"))
        retry = client.post("/api/chat", json={"conversation_id": c["id"], "content": "hello", "client_turn_id": "retry-1"})
        assert retry.json()["user_message"]["id"] == user_id
        assert len(client.get("/api/conversations/" + c["id"]).json()["messages"]) == 3


def test_reply_remains_bound_to_original_turn_after_concurrent_append(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        def handler(request):
            client.app.state.repository.append_messages(c["id"], [{"id": "other-user", "role": "user", "content": "unrelated"}])
            return provider_response("first reply")
        client.app.state.provider_transport = httpx.MockTransport(handler)
        response = client.post("/api/chat", json={"conversation_id": c["id"], "content": "first", "client_turn_id": "concurrent"})
        assert response.status_code == 200
        assert response.json()["assistant_message"]["parent_id"] == response.json()["user_message"]["id"]
        current = client.get("/api/conversations/" + c["id"]).json()
        assert next(m for m in current["messages"] if m["id"] == current["current_node"])["external_id"] == "other-user"
        assert len(current["branches"]) == 2


def test_unconfigured_chat_keeps_user_and_explicit_configuration_error(tmp_path):
    with make_client(tmp_path, configured=False) as client:
        response = client.post("/api/chat", json={"content": "hello", "client_turn_id": "new"})
        assert response.status_code == 409
        assert response.json()["error_kind"] == "configuration_required"
        assert response.json()["user_message"]["content"] == "hello"


def test_chat_rejects_stale_active_branch_context_if_ancestor_is_edited(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        def handler(request):
            client.app.state.repository.append_messages(c["id"], [{"id": "u1", "role": "user", "content": "changed ancestor"}])
            return provider_response("stale reply")
        client.app.state.provider_transport = httpx.MockTransport(handler)
        response = client.post("/api/chat", json={"conversation_id": c["id"], "content": "hello", "client_turn_id": "stale"})
        assert response.status_code == 409
        assert response.json()["error_kind"] == "stale_turn"
        assert response.json()["assistant_message"] is None


def test_concurrent_retry_does_not_duplicate_provider_call_or_user(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        calls = []
        body = {"conversation_id": c["id"], "content": "hello", "client_turn_id": "same"}
        def handler(request):
            calls.append(request)
            retry = client.post("/api/chat", json=body)
            assert retry.status_code == 409
            assert retry.json()["error_kind"] == "turn_running"
            return provider_response("reply")
        client.app.state.provider_transport = httpx.MockTransport(handler)
        assert client.post("/api/chat", json=body).status_code == 200
        assert len(calls) == 1
        assert len(client.get("/api/conversations/" + c["id"]).json()["messages"]) == 3


def test_unconfigured_chat_reports_no_sent_context_and_retry_rebuilds_it(tmp_path):
    calls = []
    with make_client(tmp_path, lambda request: calls.append(request) or provider_response("reply"), configured=False) as client:
        memory = client.post("/api/memories", json={"content": "中文", "category": "preference", "status": "confirmed"}).json()
        body = {"content": "hello", "client_turn_id": "unsent-context"}
        response = client.post("/api/chat", json=body)
        assert response.status_code == 409
        assert response.json()["used_context"] == {"memory_ids": [], "knowledge_ids": [], "message_ids": [], "evidence": []}
        assert response.json()["user_message"]["content"] == "hello"
        assert calls == []
        client.post("/api/settings", json={"base_url": "https://provider.test/v1", "chat_model": "test-chat"})
        retry = client.post("/api/chat", json=body)
        assert retry.status_code == 200
        assert retry.json()["user_message"]["id"] == response.json()["user_message"]["id"]
        assert retry.json()["used_context"]["memory_ids"] == [memory["id"]]
        assert len(calls) == 1


@pytest.mark.parametrize("existing,branch", [(False, "not-real"), (False, ""), (True, ""), (True, "not-real")])
def test_chat_invalid_branch_is_rejected_before_writes_or_provider_call(tmp_path, existing, branch):
    calls = []
    with make_client(tmp_path, lambda request: calls.append(request) or provider_response("reply")) as client:
        c = source(client) if existing else None
        before = client.get("/api/stats").json()
        body = {"content": "hello", "client_turn_id": "invalid-branch", "branch": branch}
        if c:
            body["conversation_id"] = c["id"]
        response = client.post("/api/chat", json=body)
        assert response.status_code == 422
        assert client.get("/api/stats").json() == before
        assert calls == []


def test_chat_branch_with_missing_conversation_is_rejected_as_invalid_request(tmp_path):
    calls = []
    with make_client(tmp_path, lambda request: calls.append(request) or provider_response("reply")) as client:
        before = client.get("/api/stats").json()
        response = client.post("/api/chat", json={"conversation_id": "missing", "branch": "not-real",
            "content": "hello", "client_turn_id": "missing-branch-conversation"})
        assert response.status_code == 422
        assert client.get("/api/stats").json() == before
        assert calls == []


@pytest.mark.parametrize("content", ["长" * 16000, "🧠" * 16000, "\x00" * 10000 + "hello"], ids=["cjk", "four-byte", "escaped"])
def test_chat_complete_utf8_budget_preserves_full_user_and_trims_ancestors(tmp_path, content):
    requests = []
    with make_client(tmp_path, lambda request: requests.append(request) or provider_response("reply")) as client:
        c = client.post("/api/conversations", json={"messages": [{"id": "old-user", "role": "user", "content": "旧" * 5000},
            {"id": "old-assistant", "role": "assistant", "content": "旧" * 5000, "parent_id": "old-user"}]}).json()
        body = {"conversation_id": c["id"], "content": content, "client_turn_id": "utf8-budget"}
        response = client.post("/api/chat", json=body)
        assert response.status_code == 200
        assert len(requests[0].content) <= 65536
        messages = json.loads(requests[0].content)["messages"]
        assert messages[-1]["content"] == content
        assert len(messages) - 1 == len(response.json()["used_context"]["message_ids"])
        assert response.json()["user_message"]["content"] == content
        again = client.post("/api/chat", json=body)
        assert again.json()["assistant_message"]["id"] == response.json()["assistant_message"]["id"]
        assert len(requests) == 1


@pytest.mark.parametrize("entity", ["memory", "knowledge"])
def test_chat_large_cjk_proofs_only_report_context_blocks_that_fit(tmp_path, entity):
    requests = []
    with make_client(tmp_path, lambda request: requests.append(request) or provider_response("reply")) as client:
        c = source(client, "中" * 3500)
        evidence = [{"message_id": c["messages"][0]["id"], "quote": "中" * 3500}]
        ids = []
        for index in range(2):
            values = {"content": "中" * 1000, "category": "preference", "status": "confirmed", "evidence": evidence} if entity == "memory" else {
                "title": "中" + str(index), "body": "中" * 1000, "evidence": evidence}
            ids.append(client.post("/api/" + ("memories" if entity == "memory" else "knowledge"), json=values).json()["id"])
        response = client.post("/api/chat", json={"conversation_id": c["id"], "content": "中" * 16000, "client_turn_id": "proof-budget"})
        assert response.status_code == 200
        assert len(requests[0].content) <= 65536
        messages = json.loads(requests[0].content)["messages"]
        blocks = json.loads(messages[0]["content"].split("\n", 1)[1])
        used = response.json()["used_context"]
        reported_ids = used["memory_ids" if entity == "memory" else "knowledge_ids"]
        assert reported_ids == [block["id"] for block in blocks]
        assert len(reported_ids) == 1 and set(reported_ids) < set(ids)
        assert used["evidence"] == [proof for block in blocks for proof in block["evidence"]]
        assert messages[-1]["content"] == "中" * 16000


def test_oversized_user_turn_is_saved_idempotently_without_provider_or_context(tmp_path):
    requests = []
    with make_client(tmp_path, lambda request: requests.append(request) or provider_response("reply")) as client:
        content = "\x00" * 16000
        body = {"content": content, "client_turn_id": "too-large"}
        response = client.post("/api/chat", json=body)
        assert response.status_code == 413
        assert response.json()["error_kind"] == "request_too_large"
        assert response.json()["assistant_message"] is None
        assert response.json()["used_context"] == {"memory_ids": [], "knowledge_ids": [], "message_ids": [], "evidence": []}
        assert response.json()["user_message"]["content"] == content
        again = client.post("/api/chat", json=body)
        assert again.status_code == 413
        assert again.json()["user_message"]["id"] == response.json()["user_message"]["id"]
        assert requests == []
        assert client.get("/api/stats").json()["messages"] == 1
