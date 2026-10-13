"""Isolated real FastAPI/SQLite server for headless UI tests; never reads user settings.

Only the provider HTTP boundary is synthetic. App routes, importers, jobs,
citations, chat context, settings, search, export, and SQLite remain real.
"""
import atexit
import asyncio
import gc
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory, gettempdir

import httpx
import uvicorn
from fastapi.responses import JSONResponse
from recallnest.app import create_app
from recallnest.config import Settings

directories = []


def provider(request):
    body = json.loads(request.content)
    if body.get("model") == "fail-model":
        return httpx.Response(401, text="synthetic private provider detail")
    if request.url.path.endswith("/embeddings"):
        items = body["input"] if isinstance(body["input"], list) else [body["input"]]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": [1.0, 0.5, 0.25]} for i, _ in enumerate(items)]})
    if body.get("response_format"):
        source = json.loads(body["messages"][1]["content"])
        messages = source["messages"]
        fact = next((m for m in messages if "我偏好中文。" in m["content"]), None)
        evidence = [{"message_id": fact["id"], "message_version": fact["version"], "quote": "我偏好中文。"}] if fact else []
        topic = next((m for m in messages if "事务确保全部成功或全部回滚。" in m["content"]), None)
        topic_evidence = [{"message_id": topic["id"], "message_version": topic["version"], "quote": "事务确保全部成功或全部回滚。"}] if topic else []
        content = {"knowledge": [{"title": "事务与原子性", "summary": "把多个写入组合为一个整体。", "body": "**事务**保证原子性。", "type": "topic", "tags": ["数据库"], "evidence": topic_evidence}] if topic else [],
                   "memories": [{"content": "我偏好中文。", "category": "preference", "subject": "语言", "evidence": evidence}] if fact else [],
                   "reviews": [{"question": "事务为什么需要原子性？", "answer": "确保写入全部成功或全部回滚。", "evidence": topic_evidence}] if topic else []}
        content = json.dumps(content, ensure_ascii=False)
    else:
        if any("延迟分支" in m["content"] for m in body["messages"] if m["role"] == "user"):
            time.sleep(0.6)
        if any("失败请求" in m["content"] for m in body["messages"] if m["role"] == "user"):
            return httpx.Response(401, text="synthetic private provider detail")
        content = "这是本地测试服务的真实 HTTP 边界回复。"
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def fresh_app():
    directory = TemporaryDirectory(prefix="recallnest-browser-")
    directories.append(directory)
    app = create_app(settings=Settings(Path(directory.name)))
    app.state.provider_transport = httpx.MockTransport(provider)
    return app


current = fresh_app()


async def app(scope, receive, send):
    global current
    if scope["type"] == "http" and scope["path"] == "/_test/reset" and scope["method"] == "POST":
        current = fresh_app()
        return await JSONResponse({"isolated": True})(scope, receive, send)
    if scope["type"] == "http" and scope["path"] == "/_test/cleanup" and scope["method"] == "POST":
        # Closed browser contexts can leave a final GET finishing in a thread.
        await asyncio.sleep(0.2)
        cleanup()
        return await JSONResponse({"cleaned": True})(scope, receive, send)
    await current(scope, receive, send)


def cleanup():
    # sqlite's schema initialization context commits but doesn't explicitly
    # close its short-lived connection. Collect those cycles before removing
    # isolated databases, since Windows refuses to unlink open SQLite files.
    gc.collect()
    for directory in directories:
        path = Path(directory.name).resolve()
        if path.parent != Path(gettempdir()).resolve() or not path.name.startswith("recallnest-browser-"):
            raise RuntimeError("Unexpected synthetic test directory")
        directory.cleanup()
    directories.clear()


atexit.register(cleanup)
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18787, log_level="warning")
