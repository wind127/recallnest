import json
import pytest
from fastapi.testclient import TestClient
from recallnest.app import create_app
from recallnest.repository import Repository


@pytest.fixture(autouse=True)
def isolated_provider_environment(monkeypatch):
    for field in ("API_KEY", "BASE_URL", "CHAT_MODEL", "EMBEDDING_MODEL"):
        monkeypatch.delenv("RECALLNEST_" + field, raising=False)


@pytest.fixture
def repo(tmp_path):
    return Repository(tmp_path / "test.sqlite3")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, start_worker=False), base_url="http://127.0.0.1") as client:
        yield client


@pytest.fixture
def sample_bytes():
    return json.dumps({"source": "fixture", "external_id": "conversation-1", "title": "中文学习", "messages": [
        {"id": "u1", "role": "user", "content": "我喜欢用中文学习，完成 100% 的练习", "timestamp": "2026-10-14T08:00:00Z"},
        {"id": "a1", "role": "assistant", "content": "可以制作复习卡片", "parent_id": "u1"}
    ]}, ensure_ascii=False).encode()
