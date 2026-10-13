import json
import httpx
import pytest
from ai_helpers import make_client, source


def test_text_search_without_model_is_stable_bounded_and_cited(tmp_path):
    with make_client(tmp_path, configured=False) as client:
        c = source(client, "SQLite 中文事务")
        evidence = [{"message_id": c["messages"][0]["id"], "quote": "SQLite"}]
        k = client.post("/api/knowledge", json={"title": "SQLite", "body": "SQLite 中文事务", "tags": ["db"], "type": "topic", "evidence": evidence}).json()
        result = client.get("/api/search", params={"q": "SQLite", "limit": 2})
        assert result.status_code == 200
        assert len(result.json()["items"]) == 2
        assert result.json()["mode"] == "text"
        assert result.json() == client.get("/api/search", params={"q": "SQLite", "limit": 2}).json()
        filtered = client.get("/api/search", params={"q": "SQLite", "tag": "db", "type": "topic"})
        assert [i["id"] for i in filtered.json()["items"]] == [k["id"]]
        assert filtered.json()["items"][0]["evidence"][0]["message_id"] == c["messages"][0]["id"]


def test_embeddings_are_persisted_and_changed_content_or_model_invalidates_them(tmp_path):
    def handler(request):
        assert request.url.path == "/v1/embeddings"
        inputs = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(inputs)]})
    with make_client(tmp_path, handler) as client:
        source(client, "SQLite")
        k = client.post("/api/knowledge", json={"title": "different", "body": "transaction"}).json()
        response = client.post("/api/search/reindex")
        assert response.status_code == 200
        assert response.json()["indexed"] >= 3
        result = client.get("/api/search", params={"q": "semantic", "semantic": True})
        assert result.json()["mode"] == "hybrid"
        assert k["id"] in [i["id"] for i in result.json()["items"]]
        client.patch("/api/knowledge/" + k["id"], json={"body": "changed"})
        assert k["id"] not in [i["id"] for i in client.get("/api/search", params={"q": "semantic", "semantic": True}).json()["items"]]
        client.post("/api/settings", json={"embedding_model": "other-model"})
        assert client.get("/api/search", params={"q": "semantic", "semantic": True}).json()["items"] == []


@pytest.mark.parametrize("vector", [[], [float("nan")], [0, 0], ["bad"], [10 ** 400]])
def test_invalid_embeddings_fail_explicitly_without_persisting(tmp_path, vector):
    # Raw JSON permits exercising provider nonfinite output independently of request validation.
    def handler(request):
        return httpx.Response(200, content=json.dumps({"data": [{"index": 0, "embedding": vector}]}).encode())
    with make_client(tmp_path, handler) as client:
        source(client)
        result = client.post("/api/search/reindex")
        assert result.status_code == 502
        assert result.json()["error_kind"] == "invalid_output"


def test_empty_reindex_still_requires_configured_embedding_model(tmp_path):
    with make_client(tmp_path, configured=False) as client:
        response = client.post("/api/search/reindex")
        assert response.status_code == 409
        assert response.json()["error_kind"] == "configuration_required"


def test_source_version_changes_invalidate_semantic_message_vector(tmp_path):
    def handler(request):
        texts = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 0.0]} for i in range(len(texts))]})
    with make_client(tmp_path, handler) as client:
        c = source(client, "original")
        mid = c["messages"][0]["id"]
        assert client.post("/api/search/reindex").status_code == 200
        assert mid in [item["id"] for item in client.get("/api/search", params={"q": "semantic", "semantic": True}).json()["items"]]
        client.post("/api/conversations/" + c["id"] + "/messages", json={"messages": [{"id": "u1", "role": "assistant", "content": "original"}]})
        assert mid not in [item["id"] for item in client.get("/api/search", params={"q": "semantic", "semantic": True}).json()["items"]]


def test_cosine_remains_stable_for_large_finite_components():
    from recallnest.search import cosine
    assert cosine([1e150, 0.0], [1e150, 0.0]) == 1.0
