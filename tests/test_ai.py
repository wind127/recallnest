import json
import pytest
from ai_helpers import make_client, source, extraction, run_job, provider_response


def test_provider_success_extracts_validated_evidence_and_candidates(tmp_path):
    requests = []
    with make_client(tmp_path) as client:
        conversation = source(client)
        def handler(request):
            requests.append(request)
            return provider_response(extraction(conversation["messages"][0]))
        client.app.state.provider_transport = __import__("httpx").MockTransport(handler)
        result = run_job(client)
        assert result.status_code == 200
        assert result.json()["status"] == "completed"
        memory = client.get("/api/memories").json()["items"][0]
        assert memory["status"] == "candidate"
        assert memory["evidence"][0]["stale"] is False
        assert requests[0].url.path == "/v1/chat/completions"
        assert requests[0].headers["authorization"] == "Bearer secret-key"
        assert "secret-key" not in requests[0].content.decode()


@pytest.mark.parametrize("body,kind", [("not-json", "invalid_output"), ({"knowledge": []}, "invalid_output"), (None, "provider_http")])
def test_invalid_provider_results_have_no_partial_writes_or_secret_errors(tmp_path, body, kind):
    with make_client(tmp_path, lambda request: provider_response(body, 503) if body is None else provider_response(body)) as client:
        source(client)
        result = run_job(client)
        assert result.status_code == 200
        assert result.json()["error_kind"] == kind
        assert "secret-key" not in json.dumps(result.json())
        assert client.get("/api/knowledge").json()["items"] == []


@pytest.mark.parametrize("role,text,content", [("assistant", "我偏好中文。", "我偏好中文。"),
    ("user", "我是否偏好中文？", "我是否偏好中文？"), ("user", "我偏好中文。", "我是一名医生。"),
    ("user", "我偏好中文吗", "我偏好中文吗"), ("user", "我不是医生。", "医生")])
def test_personal_claims_require_assertive_user_evidence_and_supported_content(tmp_path, role, text, content):
    with make_client(tmp_path) as client:
        c = source(client, text, role)
        output = extraction(c["messages"][0])
        output["memories"][0]["content"] = content
        client.app.state.provider_transport = __import__("httpx").MockTransport(lambda request: provider_response(output))
        result = run_job(client)
        assert result.status_code == 200
        assert result.json()["error_kind"] == "invalid_output"
        assert client.get("/api/memories").json()["items"] == []
        assert client.get("/api/knowledge").json()["items"] == []


def test_nonexistent_citation_rejects_entire_extraction(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client)
        output = extraction(c["messages"][0])
        output["reviews"][0]["evidence"][0]["message_id"] = "missing"
        client.app.state.provider_transport = __import__("httpx").MockTransport(lambda request: provider_response(output))
        result = run_job(client)
        assert result.status_code == 200
        assert result.json()["error_kind"] == "invalid_output"
        assert client.get("/api/stats").json()["knowledge"] == 0


def test_settings_key_omission_clear_restart_and_connection_test(tmp_path):
    with make_client(tmp_path) as client:
        result = client.get("/api/settings")
        assert result.status_code == 200
        assert result.json()["has_api_key"] is True
        assert "secret-key" not in result.text
        assert client.post("/api/settings", json={"chat_model": "other"}).json()["has_api_key"] is True
        assert client.post("/api/settings/test").json()["connection_verified"] is True
        assert client.post("/api/settings", json={"api_key": ""}).json()["has_api_key"] is False
    from fastapi.testclient import TestClient
    from recallnest.app import create_app
    with TestClient(create_app(data_dir=tmp_path), base_url="http://127.0.0.1") as client:
        assert client.get("/api/settings").json()["chat_model"] == "other"
        assert client.get("/api/settings").json()["has_api_key"] is False


@pytest.mark.parametrize("url", ["ftp://host", "https://user:pw@host/v1", "https://host/v1?api_key=secret", "https://host/#secret"])
def test_settings_reject_unsafe_urls_without_echoing_credentials(tmp_path, url):
    with make_client(tmp_path) as client:
        result = client.post("/api/settings", json={"base_url": url})
        assert result.status_code == 422
        assert url not in result.text


def test_connection_test_cannot_verify_configuration_changed_during_request(tmp_path):
    with make_client(tmp_path) as client:
        def handler(request):
            client.app.state.connections.save({"chat_model": "changed"})
            return provider_response("OK")
        client.app.state.provider_transport = __import__("httpx").MockTransport(handler)
        response = client.post("/api/settings/test")
        assert response.status_code == 409
        assert client.get("/api/settings").json()["connection_verified"] is False


def test_invalid_environment_configuration_exception_does_not_echo_credentials(tmp_path):
    from recallnest.config import Settings
    with pytest.raises(ValueError) as error:
        Settings(tmp_path, base_url="https://user:secret-key@host")
    assert "secret-key" not in str(error.value)


def test_provider_has_an_overall_deadline_not_only_per_read_timeout(tmp_path, monkeypatch):
    import asyncio
    import httpx
    from recallnest.ai import AIClient
    monkeypatch.setattr(AIClient, "request_timeout", 0.01, raising=False)
    async def slow_response(request):
        await asyncio.sleep(0.1)
        return provider_response("late")
    with make_client(tmp_path) as client:
        client.app.state.provider_transport = httpx.MockTransport(slow_response)
        source(client)
        response = run_job(client)
        assert response.json()["error_kind"] == "provider_timeout"


def test_assistant_personal_claim_cannot_bypass_screening_as_knowledge(tmp_path):
    with make_client(tmp_path) as client:
        c = source(client, "你是一名医生。", "assistant")
        output = extraction(c["messages"][0], memories=[], reviews=[])
        output["knowledge"][0]["body"] = "用户是一名医生。"
        client.app.state.provider_transport = __import__("httpx").MockTransport(lambda request: provider_response(output))
        response = run_job(client)
        assert response.json()["error_kind"] == "invalid_output"
        assert client.get("/api/knowledge").json()["items"] == []


@pytest.mark.parametrize("text,quote", [("我偏好中文吗", "我偏好中文"), ("假设我是一名医生。", "我是一名医生。")])
def test_shortened_quote_cannot_remove_question_or_hypothetical_context(tmp_path, text, quote):
    with make_client(tmp_path) as client:
        c = source(client, text)
        output = extraction(c["messages"][0], knowledge=[], reviews=[])
        output["memories"][0]["content"] = quote
        output["memories"][0]["evidence"][0]["quote"] = quote
        client.app.state.provider_transport = __import__("httpx").MockTransport(lambda request: provider_response(output))
        response = run_job(client)
        assert response.json()["error_kind"] == "invalid_output"


@pytest.mark.parametrize("content,accepted", [("I prefer  PYTHON.", False), ("I prefer Python.", True)])
def test_personal_candidate_verbatim_gate_does_not_normalize_case_or_spacing(tmp_path, content, accepted):
    with make_client(tmp_path) as client:
        c = source(client, "I prefer Python.")
        output = extraction(c["messages"][0], knowledge=[], reviews=[])
        output["memories"][0]["content"] = content
        client.app.state.provider_transport = __import__("httpx").MockTransport(lambda request: provider_response(output))
        response = run_job(client)
        assert (response.json()["status"] == "completed") is accepted
        assert len(client.get("/api/memories").json()["items"]) == int(accepted)


@pytest.mark.parametrize("control", [chr(i) for i in range(32)] + [chr(127)])
def test_base_url_controls_are_rejected_in_rest_direct_settings_and_environment(tmp_path, monkeypatch, control):
    from recallnest.config import Settings, get_settings
    url = "https://provider.test/v1" + control
    with make_client(tmp_path) as client:
        before = client.get("/api/settings").json()
        response = client.post("/api/settings", json={"base_url": url})
        assert response.status_code == 422
        assert url not in response.text
        assert client.get("/api/settings").json() == before
        assert not (tmp_path / "provider-settings.json").exists()
    with pytest.raises(ValueError):
        Settings(tmp_path, base_url=url)
    with pytest.raises(ValueError):
        # The operating system itself rejects NUL in environment values.
        monkeypatch.setenv("RECALLNEST_BASE_URL", url)
        get_settings(tmp_path)


def test_provider_chat_final_guard_rejects_oversized_utf8_body(tmp_path):
    from recallnest.ai import AIError
    requests = []
    with make_client(tmp_path, lambda request: requests.append(request) or provider_response("reply")) as client:
        with pytest.raises(AIError) as failure:
            client.app.state.ai_factory().chat([{"role": "user", "content": "🧠" * 20000}])
        assert failure.value.kind == "request_too_large"
        assert requests == []
