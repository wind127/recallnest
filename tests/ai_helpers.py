import json
import httpx
from fastapi.testclient import TestClient
from recallnest.app import create_app
from recallnest.config import Settings


def provider_response(content="reply", status=200):
    if status != 200:
        return httpx.Response(status, text="secret-key https://user:password@provider.test/?key=secret-key")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def make_client(tmp_path, handler=None, configured=True, start_worker=False):
    settings = Settings(tmp_path, base_url="https://provider.test/v1" if configured else "",
                        api_key="secret-key", chat_model="test-chat" if configured else "", embedding_model="test-vector")
    app = create_app(settings=settings, start_worker=start_worker)
    app.state.provider_transport = httpx.MockTransport(handler or (lambda request: provider_response()))
    return TestClient(app, base_url="http://127.0.0.1")


def source(client, text="我偏好中文。", role="user", **kwargs):
    response = client.post("/api/conversations", json={"title": "Source", "messages": [
        {"id": "u1", "role": role, "content": text}], **kwargs})
    assert response.status_code == 201
    return response.json()


def extraction(message, **extra):
    evidence = [{"message_id": message["id"], "message_version": message["version"], "quote": message["content"]}]
    return {"knowledge": [{"title": "中文", "summary": "语言", "body": "中文学习", "type": "summary", "tags": [], "evidence": evidence}],
            "memories": [{"content": message["content"], "category": "preference", "subject": "语言", "evidence": evidence}],
            "reviews": [{"question": "偏好什么语言？", "answer": "中文", "evidence": evidence}], **extra}


def latest_job(client):
    return client.get("/api/jobs").json()["items"][-1]


def run_job(client, job=None):
    return client.post("/api/jobs/" + (job or latest_job(client))["id"] + "/run")
