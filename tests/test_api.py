import json
import pytest
from fastapi.testclient import TestClient
from recallnest.app import create_app
from recallnest.config import Settings


def test_empty_status_and_stats(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/status").json()["model_configured"] is False
    assert client.get("/api/stats").json()["conversations"] == 0
    assert client.get("/api/knowledge").json() == {"items": []}


def test_preview_has_no_side_effects(client, sample_bytes):
    result = client.post("/api/import/preview", files={"file": ("history.json", sample_bytes, "application/json")})
    assert result.status_code == 200
    assert result.json()["conversations"] == 1 and result.json()["messages"] == 2
    assert client.get("/api/stats").json()["conversations"] == 0
    assert client.get("/api/jobs").json() == {"items": []}


def test_repeat_import_is_idempotent(client, sample_bytes):
    first = client.post("/api/import", files={"file": ("history.json", sample_bytes, "application/json")})
    second = client.post("/api/import", files={"file": ("history.json", sample_bytes, "application/json")})
    assert first.status_code == second.status_code == 200
    assert second.json()["imported"] == 0 and second.json()["duplicates"] == 1
    assert first.json()["errors"] == 0


def test_api_crud_and_export_evidence(client, sample_bytes, monkeypatch):
    monkeypatch.setenv("RECALLNEST_API_KEY", "super-secret-not-for-export")
    client.post("/api/import", files={"file": ("history.json", sample_bytes)})
    conversation = client.get("/api/conversations").json()["items"][0]
    detail = client.get("/api/conversations/" + conversation["id"]).json()
    evidence = [{"message_id": detail["messages"][0]["id"], "quote": "中文学习"}]
    project = client.post("/api/projects", json={"name": "学习", "goals": ["learn"]}).json()
    assert client.patch("/api/projects/" + project["id"], json={"status": "active"}).status_code == 200
    knowledge = client.post("/api/knowledge", json={"title": "知识", "body": "Text", "project_id": project["id"], "evidence": evidence}).json()
    assert knowledge["evidence"][0]["conversation_id"] == conversation["id"]
    assert client.patch("/api/knowledge/" + knowledge["id"], json={"summary": "Summary"}).status_code == 200
    assert client.post("/api/knowledge/" + knowledge["id"] + "/favorite", json={"favorite": True}).json()["favorite"] is True
    memory = client.post("/api/memories", json={"content": "喜欢中文", "category": "preference", "evidence": evidence}).json()
    assert client.patch("/api/memories/" + memory["id"], json={"status": "confirmed"}).status_code == 200
    assert len(client.get("/api/memories/context").json()["items"]) == 1
    card = client.post("/api/reviews", json={"question": "Q", "answer": "A", "knowledge_id": knowledge["id"], "evidence": evidence}).json()
    assert client.post("/api/reviews/" + card["id"] + "/grade", json={"grade": "good"}).status_code == 200
    export = client.get("/api/export?format=json")
    assert "super-secret" not in export.text
    assert export.json()["schema_version"] == 1
    assert export.json()["conversations"][0]["messages"][0]["versions"]
    assert "中文学习" in client.get("/api/export?format=markdown").text
    assert client.delete("/api/memories/" + memory["id"]).status_code == 204
    assert client.get("/api/memories/" + memory["id"]).status_code == 404
    assert client.delete("/api/reviews/" + card["id"]).status_code == 204
    assert client.delete("/api/knowledge/" + knowledge["id"]).status_code == 204
    assert client.delete("/api/projects/" + project["id"]).status_code == 204


def test_conversation_create_append_and_filters(client):
    conversation = client.post("/api/conversations", json={"title": "New"}).json()
    response = client.post("/api/conversations/" + conversation["id"] + "/messages", json={"messages": [{"id": "m1", "role": "user", "content": "中文问题"}]})
    assert response.status_code == 200 and len(response.json()["messages"]) == 1
    assert len(client.get("/api/conversations?q=中文&source=manual").json()["items"]) == 1
    assert client.get("/api/conversations/missing").status_code == 404


def test_bad_upload_and_invalid_inputs(client):
    assert client.post("/api/import", files={"file": ("x.json", b"{")}).status_code == 400
    assert client.post("/api/memories", json={"content": "wrong", "category": "skill"}).status_code == 422
    assert client.post("/api/knowledge", json={"title": "bad", "evidence": [{"message_id": "missing", "quote": "hi"}]}).status_code == 422


def test_demo_is_explicit_and_idempotent(client):
    first = client.post("/api/demo")
    second = client.post("/api/demo")
    assert first.status_code == second.status_code == 200
    assert second.json()["imported"] == 0
    counts = client.get("/api/stats").json()
    assert counts["knowledge"] >= 1 and counts["reviews"] >= 1 and counts["memories"] >= 1
    assert all("demo" in c["source"] for c in client.get("/api/conversations").json()["items"])
    assert client.get("/api/memories/context").json() == {"items": []}
    assert all(k["evidence"] for k in client.get("/api/knowledge").json()["items"])


def test_local_boundary_rejects_untrusted_origin_and_host(client):
    assert client.get("/api/stats", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/stats", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/stats", headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_upload_limit_rejects_preview_without_persisting(tmp_path):
    settings = Settings(data_dir=tmp_path, max_upload_bytes=8)
    with TestClient(create_app(settings=settings), base_url="http://127.0.0.1") as client:
        assert client.post("/api/import/preview", files={"file": ("x.json", b"[]" * 20)}).status_code == 413
        assert client.get("/api/stats").json()["conversations"] == 0


def test_patch_rejects_extra_and_invalid_fields(client):
    project = client.post("/api/projects", json={"name": "P"}).json()
    assert client.patch("/api/projects/" + project["id"], json={"secret": "no"}).status_code == 422
    assert client.patch("/api/projects/" + project["id"], json={"artifact_links": [{"url": "javascript:alert(1)"}]}).status_code == 422
    memory = client.post("/api/memories", json={"content": "C", "category": "state"}).json()
    assert client.patch("/api/memories/" + memory["id"], json={"status": "invented"}).status_code == 422


def test_limit_settings_from_environment(monkeypatch, tmp_path):
    from recallnest.config import get_settings
    monkeypatch.setenv("RECALLNEST_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("RECALLNEST_MAX_ZIP_BYTES", "2048")
    monkeypatch.setenv("RECALLNEST_MAX_ZIP_MEMBERS", "10")
    settings = get_settings(tmp_path)
    assert (settings.max_upload_bytes, settings.max_zip_bytes, settings.max_zip_members) == (1024, 2048, 10)


def test_patch_project_status_has_documented_choices(client):
    project = client.post("/api/projects", json={"name": "P"}).json()
    assert client.patch("/api/projects/" + project["id"], json={"status": "invented"}).status_code == 422


def test_append_api_retry_keeps_existing_parent(client):
    conv = client.post("/api/conversations", json={"title": "P"}).json()
    body = {"messages": [{"id": "u1", "role": "user", "content": "Hi"}]}
    first = client.post("/api/conversations/" + conv["id"] + "/messages", json=body).json()
    second = client.post("/api/conversations/" + conv["id"] + "/messages", json=body).json()
    assert second["revision"] == first["revision"] and len(second["messages"]) == 1


def test_chunked_body_limit_reports_413(tmp_path):
    settings = Settings(data_dir=tmp_path, max_upload_bytes=8)
    with TestClient(create_app(settings=settings), base_url="http://127.0.0.1") as client:
        response = client.post("/api/conversations", content=iter([b"x" * 70000]), headers={"Content-Type": "application/json"})
        assert response.status_code == 413
        assert "limit" in response.json()["detail"]


def test_real_settings_secrets_never_enter_status_or_exports(tmp_path):
    settings = Settings(data_dir=tmp_path, api_key="test-synthetic-secret", base_url="https://provider.example", chat_model="sample")
    with TestClient(create_app(settings=settings), base_url="http://127.0.0.1") as client:
        for path in ("/api/status", "/api/export", "/api/export?format=markdown"):
            response = client.get(path)
            assert response.status_code == 200 and "test-synthetic-secret" not in response.text
            assert "provider.example" not in response.text


def test_app_factory_does_not_create_data_directory(tmp_path):
    directory = tmp_path / "untouched"
    create_app(data_dir=directory)
    assert not directory.exists()


def test_review_explicit_empty_links_are_respected_and_patch_does_not_inherit(client):
    conv = client.post("/api/conversations", json={"messages": [{"id": "u1", "role": "user", "content": "quote"}]}).json()
    evidence = [{"message_id": conv["messages"][0]["id"], "quote": "quote"}]
    project = client.post("/api/projects", json={"name": "P"}).json()
    knowledge = client.post("/api/knowledge", json={"title": "K", "project_id": project["id"], "evidence": evidence}).json()
    inherited = client.post("/api/reviews", json={"question": "Q", "knowledge_id": knowledge["id"]}).json()
    assert inherited["project_id"] == project["id"] and inherited["evidence"]
    explicit = client.post("/api/reviews", json={"question": "Q", "knowledge_id": knowledge["id"], "project_id": None, "evidence": []}).json()
    assert explicit["project_id"] is None and explicit["evidence"] == []
    cleared = client.patch("/api/reviews/" + inherited["id"], json={"project_id": None, "evidence": []}).json()
    assert cleared["project_id"] is None and cleared["evidence"] == []
    edited = client.patch("/api/reviews/" + explicit["id"], json={"question": "Edited"}).json()
    assert edited["project_id"] is None and edited["evidence"] == []


def test_invalid_current_node_create_and_append_roll_back(client):
    result = client.post("/api/conversations", json={"current_node": "missing", "messages": [{"id": "u1", "role": "user", "content": "Hi"}]})
    assert result.status_code == 422
    assert client.get("/api/stats").json()["conversations"] == 0
    conv = client.post("/api/conversations", json={"messages": [{"id": "u1", "role": "user", "content": "Hi"}]}).json()
    result = client.post("/api/conversations/" + conv["id"] + "/messages", json={"current_node": "missing", "messages": [{"id": "a1", "role": "assistant", "content": "Reply"}]})
    assert result.status_code == 422
    after = client.get("/api/conversations/" + conv["id"]).json()
    assert after["revision"] == conv["revision"] and len(after["messages"]) == 1


def test_demo_repeat_preserves_conversation_title_and_message_edits(client):
    client.post("/api/demo")
    conv = next(c for c in client.get("/api/conversations").json()["items"] if c["source"] == "demo:chatgpt")
    client.patch("/api/conversations/" + conv["id"], json={"title": "Edited demo title"})
    client.post("/api/conversations/" + conv["id"] + "/messages", json={"messages": [{"id": "demo-u1", "role": "user", "content": "Edited demo content"}]})
    before = client.get("/api/conversations/" + conv["id"]).json()
    repeat = client.post("/api/demo").json()
    after = client.get("/api/conversations/" + conv["id"]).json()
    assert repeat["updated"] == 0 and repeat["imported"] == 0
    assert after["title"] == before["title"] == "Edited demo title"
    assert after["messages"][0]["content"] == "Edited demo content"
    assert after["revision"] == before["revision"]


@pytest.mark.parametrize("limit,limits", [("expanded", {"max_zip_bytes": 10}), ("members", {"max_zip_members": 1})])
def test_zip_limit_failures_are_413_for_preview_and_import(tmp_path, limit, limits):
    from test_importers import zip_bytes
    payload = zip_bytes({"conversations.json": " " * 30, "extra": ""})
    with TestClient(create_app(settings=Settings(data_dir=tmp_path, **limits)), base_url="http://127.0.0.1") as client:
        for endpoint in ("/api/import/preview", "/api/import"):
            result = client.post(endpoint, files={"file": ("archive.zip", payload)})
            assert result.status_code == 413 and limit in result.json()["detail"]
        assert client.get("/api/stats").json()["conversations"] == 0


@pytest.mark.parametrize("url", ["https://", "http://:", "http:///missing", "https://example.com:invalid", "http://example.com:99999"])
def test_artifact_links_require_host_and_valid_port(client, url):
    assert client.post("/api/projects", json={"name": "P", "artifact_links": [{"url": url}]}).status_code == 422
    assert client.get("/api/projects").json()["items"] == []


@pytest.mark.parametrize("endpoint", ["create", "append"])
def test_rest_nested_messages_reject_unknown_fields(client, endpoint):
    body = {"messages": [{"id": "u1", "role": "user", "content": "Hi", "unknown": "must not be discarded"}]}
    if endpoint == "create":
        result = client.post("/api/conversations", json=body)
    else:
        conv = client.post("/api/conversations", json={}).json()
        result = client.post("/api/conversations/" + conv["id"] + "/messages", json=body)
    assert result.status_code == 422


@pytest.mark.parametrize("constant", ["1e999", "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("container", ["raw", "metadata"])
def test_rest_nonfinite_nested_source_values_are_rejected_before_writes(client, constant, container):
    body = '{"messages":[{"id":"u1","role":"user","content":"text","' + container + '":{"nested":[{"number":' + constant + '}]}}]}'
    response = client.post("/api/conversations", content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    stats = client.get("/api/stats").json()
    assert stats["conversations"] == stats["messages"] == stats["jobs"] == 0
    assert client.get("/api/export").status_code == 200


@pytest.mark.parametrize("constant", ["1e999", "NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("format", ["json", "jsonl", "zip"])
def test_import_nonfinite_source_records_are_rejected_with_no_writes(client, constant, format):
    from test_importers import zip_bytes
    payload = ('{"source":"bad","external_id":"bad","messages":[],"extra":{"nested":[' + constant + ']}}').encode()
    if format == "jsonl":
        payload = ('{"type":"session_meta","payload":{"id":"bad"},"extra":{"nested":[' + constant + ']}}\n').encode()
    elif format == "zip":
        payload = zip_bytes({"conversations.json": payload})
    for endpoint in ("/api/import/preview", "/api/import"):
        response = client.post(endpoint, files={"file": ("bad." + format, payload)})
        assert 400 <= response.status_code < 500
    stats = client.get("/api/stats").json()
    assert stats["conversations"] == stats["messages"] == stats["jobs"] == 0
    assert client.get("/api/export").status_code == 200


@pytest.mark.parametrize("metadata", [{"node_message_ids": []}, {"node_message_ids": {"key": []}}, {"non_text_blocks": "one"}, {"non_text_blocks": -1}, {"non_text_blocks": True}])
@pytest.mark.parametrize("target", ["conversation", "message"])
def test_reserved_import_metadata_shapes_fail_consistently_without_writes(client, metadata, target):
    body = {"source": "bad", "external_id": "bad", "messages": [{"id": "u1", "role": "user", "content": "text"}]}
    (body if target == "conversation" else body["messages"][0])["metadata"] = metadata
    with TestClient(client.app, base_url="http://127.0.0.1", raise_server_exceptions=False) as safe_client:
        for endpoint in ("/api/import/preview", "/api/import"):
            response = safe_client.post(endpoint, files={"file": ("bad.json", json.dumps(body).encode())})
            assert 400 <= response.status_code < 500
    stats = client.get("/api/stats").json()
    assert stats["conversations"] == stats["messages"] == stats["jobs"] == 0


@pytest.mark.parametrize("value", ["1e999", "1e18"])
@pytest.mark.parametrize("endpoint,body", [
    ("/api/memories", '{"content":"C","category":"state","effective_at":VALUE}'),
    ("/api/memories", '{"content":"C","category":"state","expires_at":VALUE}'),
    ("/api/reviews", '{"question":"Q","due_at":VALUE}'),
    ("/api/conversations", '{"messages":[{"role":"user","content":"Q","timestamp":VALUE}]}'),
])
def test_out_of_range_dates_are_validation_errors_without_writes(client, value, endpoint, body):
    with TestClient(client.app, base_url="http://127.0.0.1", raise_server_exceptions=False) as safe_client:
        response = safe_client.post(endpoint, content=body.replace("VALUE", value), headers={"Content-Type": "application/json"})
        assert response.status_code == 422
    stats = client.get("/api/stats").json()
    assert all(stats[key] == 0 for key in ("memories", "reviews", "conversations", "messages", "jobs"))


@pytest.mark.parametrize("version", [0, -1])
def test_evidence_version_must_be_positive(client, version):
    conv = client.post("/api/conversations", json={"messages": [{"id": "u1", "role": "user", "content": "quote"}]}).json()
    evidence = [{"message_id": conv["messages"][0]["id"], "message_version": version, "quote": "quote"}]
    assert client.post("/api/knowledge", json={"title": "K", "evidence": evidence}).status_code == 422
    assert client.get("/api/stats").json()["knowledge"] == 0
