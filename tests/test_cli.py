import json
from pathlib import Path
import subprocess
import sys
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psutil

from fastapi.testclient import TestClient
import pytest

from recallnest.cli import main, build_app


def test_cli_import_export_share_archive_and_exclude_connections(tmp_path, sample_bytes, capsys, monkeypatch):
    source = tmp_path / "synthetic.json"
    source.write_bytes(sample_bytes)
    data = tmp_path / "data"
    monkeypatch.setenv("RECALLNEST_API_KEY", "secret-synthetic-key")
    monkeypatch.setenv("RECALLNEST_BASE_URL", "http://127.0.0.1:9999")
    assert main(["import", str(source), "--data-dir", str(data)]) == 0
    assert json.loads(capsys.readouterr().out)["messages"] == 2
    assert main(["export", "--data-dir", str(data)]) == 0
    export = capsys.readouterr().out
    assert json.loads(export)["schema_version"] == 1
    assert "secret-synthetic-key" not in export and "9999" not in export
    output = tmp_path / "export.md"
    assert main(["export", "--format", "markdown", "--output", str(output), "--data-dir", str(data)]) == 0
    assert "中文学习" in output.read_text(encoding="utf-8")


def test_cli_import_limit_and_safe_error(tmp_path, monkeypatch, capsys):
    source = tmp_path / "s.json"
    source.write_bytes(b"[]" * 10)
    monkeypatch.setenv("RECALLNEST_MAX_UPLOAD_BYTES", "2")
    assert main(["import", str(source), "--data-dir", str(tmp_path / "data")]) == 1
    result = capsys.readouterr()
    assert not result.out and "limit" in result.err
    assert "Traceback" not in result.err


def test_static_spa_safe_assets_missing_api_and_missing_build(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>Synthetic UI</html>")
    (web / "asset.js").write_text("syntheticAsset")
    with TestClient(build_app(tmp_path / "data", web), base_url="http://127.0.0.1") as client:
        assert client.get("/nested/route").text == "<html>Synthetic UI</html>"
        assert client.get("/asset.js").text == "syntheticAsset"
        assert client.get("/api/unknown").status_code == 404
        assert client.get("/asset-missing.js").status_code == 404
        assert client.get("/../pyproject.toml").status_code == 404
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/", headers={"host": "remote.example"}).status_code == 400
    with TestClient(build_app(tmp_path / "data2", tmp_path / "absent"), base_url="http://127.0.0.1") as client:
        assert client.get("/api/health").status_code == 200
        assert "Build the web UI" in client.get("/").text


def test_serve_saved_connections_survive_cli_restart(tmp_path):
    from recallnest.provider_settings import ConnectionSettings
    from recallnest.config import get_settings
    ConnectionSettings(get_settings(tmp_path)).save({"base_url": "http://127.0.0.1:9876", "chat_model": "synthetic", "api_key": "synthetic-secret"})
    app = build_app(tmp_path, tmp_path / "missing")
    assert app.state.connections.current().chat_model == "synthetic"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/status").json()["worker_running"] is True


def test_cli_serve_defaults_and_custom_bind(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **options: calls.append((app, options)))
    assert main(["serve", "--data-dir", str(tmp_path)]) == 0
    assert calls[-1][1] == {"host": "127.0.0.1", "port": 8787}
    assert main(["serve", "--data-dir", str(tmp_path), "--host", "0.0.0.0", "--port", "9898", "--web-dir", str(tmp_path / "web")]) == 0
    assert calls[-1][1] == {"host": "0.0.0.0", "port": 9898}


def test_cli_module_help_and_capture_root_is_required(tmp_path):
    result = subprocess.run([sys.executable, "-m", "recallnest", "--help"], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and "capture" in result.stdout and "mcp" in result.stdout
    result = subprocess.run([sys.executable, "-m", "recallnest", "capture", "start", "--data-dir", str(tmp_path)], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and "root" in result.stderr


def test_importing_integration_modules_never_reads_provider_config(tmp_path):
    import os
    script = """from pathlib import Path
original = Path.is_file
def guarded(path):
    if path.name == 'provider-settings.json':
        raise AssertionError('import read provider configuration')
    return original(path)
Path.is_file = guarded
import recallnest.cli, recallnest.capture, recallnest.mcp_server
"""
    result = subprocess.run([sys.executable, "-c", script], env={**os.environ, "RECALLNEST_DATA_DIR": str(tmp_path)}, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.iterdir())


def test_default_asgi_entrypoint_lazy_lifespan_preserves_worker(tmp_path, monkeypatch):
    import recallnest.app as module
    monkeypatch.setenv("RECALLNEST_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(module, "_default_app", None, raising=False)
    assert not list(tmp_path.iterdir())
    with TestClient(module.app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/status").json()["worker_running"] is True
    assert module._default_app.state.worker_running is False


def test_actual_cli_uvicorn_serve_saved_settings_and_loopback_boundary(tmp_path):
    from recallnest.provider_settings import ConnectionSettings
    from recallnest.config import get_settings
    data, web = tmp_path / "private", tmp_path / "built"
    web.mkdir()
    (web / "index.html").write_text("Synthetic actual service")
    ConnectionSettings(get_settings(data)).save({"base_url": "http://127.0.0.1:9876", "chat_model": "synthetic-model"})
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    command = [sys.executable, "-m", "recallnest", "serve", "--data-dir", str(data), "--web-dir", str(web), "--port", str(port)]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    with (tmp_path / "serve.stderr").open("wb") as log:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, **options)
        try:
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urlopen(url + "/api/status", timeout=1) as response:
                        status = json.load(response)
                    break
                except URLError:
                    if time.monotonic() >= deadline:
                        pytest.fail("CLI service did not start")
                    time.sleep(0.1)
            assert status["worker_running"] and status["model_configured"]
            with urlopen(url + "/nested/route", timeout=2) as response:
                assert response.read() == b"Synthetic actual service"
            with pytest.raises(HTTPError) as denied:
                urlopen(Request(url + "/api/health", headers={"Host": "untrusted.example"}), timeout=2)
            assert denied.value.code == 400
        finally:
            # Windows venv launchers can own a child interpreter. Stop only this test's
            # captured process tree with the exact synthetic data-dir command.
            parent = psutil.Process(process.pid)
            owned = parent.children(recursive=True) + [parent]
            for child in owned:
                try:
                    if str(data) in child.cmdline():
                        child.terminate()
                except psutil.NoSuchProcess:
                    pass
            process.wait(timeout=10)


def test_cli_stdout_is_utf8_even_with_legacy_windows_console_encoding(tmp_path):
    source = tmp_path / "synthetic.json"
    source.write_text(json.dumps({"source": "synthetic", "messages": [{"role": "user", "content": "中文 🐦"}]}, ensure_ascii=False), encoding="utf-8")
    environment = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    imported = subprocess.run([sys.executable, "-m", "recallnest", "import", str(source), "--data-dir", str(tmp_path / "data")], env=environment, capture_output=True, timeout=15)
    assert imported.returncode == 0
    exported = subprocess.run([sys.executable, "-m", "recallnest", "export", "--data-dir", str(tmp_path / "data")], env=environment, capture_output=True, timeout=15)
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout.decode("utf-8"))["conversations"][0]["messages"][0]["content"] == "中文 🐦"
