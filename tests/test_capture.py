from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

from recallnest.capture import Capture, CaptureDaemon, atomic_json, read_json
from recallnest.importers import parse_upload
from recallnest.repository import Repository


def line(record):
    return json.dumps(record, ensure_ascii=False).encode() + b"\n"


def session(path):
    path.write_bytes(line({"type": "session_meta", "payload": {"id": "synthetic-session"}})
                     + message("first", "synthetic first"))


def message(id, text, kind="response_item"):
    payload = {"type": "message", "id": id, "role": "user", "content": [{"type": "input_text", "text": text}]}
    if kind == "event_msg":
        payload = {"type": "user_message", "id": id, "message": text}
    return line({"type": kind, "payload": payload})


@pytest.fixture
def capture_paths(tmp_path):
    root, data = tmp_path / "synthetic logs", tmp_path / "private data"
    root.mkdir()
    return root, data


def test_capture_recreated_instance_imports_only_new_message(capture_paths):
    root, data = capture_paths
    path = root / "session.jsonl"
    session(path)
    capture = Capture(root, data)
    assert capture.preview()["messages"] == 1
    assert not data.exists()
    assert capture.scan()["messages"] == 1
    repo = Repository(data / "recallnest.sqlite3")
    first = repo.get_conversation(repo.list_conversations()[0]["id"])["messages"][0]["id"]
    with path.open("ab") as stream:
        stream.write(message("second", "synthetic second"))
    assert Capture(root, data).scan()["messages"] == 1
    archived = repo.get_conversation(repo.list_conversations()[0]["id"])
    assert [m["content"] for m in archived["messages"]] == ["synthetic first", "synthetic second"]
    assert archived["messages"][0]["id"] == first
    assert Capture(root, data).scan()["processed"] == 0


@pytest.mark.parametrize("identity", [None, "synthetic-account"])
def test_manual_history_then_capture_handoff_reuses_conversation(capture_paths, identity):
    root, data = capture_paths
    path = root / "s.jsonl"
    session(path)
    repo = Repository(data / "recallnest.sqlite3")
    imported = repo.import_conversations(parse_upload(path.name, path.read_bytes(), source_identity=identity))
    capture = Capture(root, data) if identity is None else Capture(root, data, source_identity=identity)
    assert capture.scan()["messages"] == 0
    assert repo.stats()["conversations"] == 1
    with path.open("ab") as stream:
        stream.write(message("next", "after handoff"))
    assert Capture(root, data, source_identity=identity).scan()["messages"] == 1
    assert repo.stats()["conversations"] == 1
    assert len(repo.get_conversation(imported["conversation_ids"][0])["messages"]) == 2


def test_checkpoint_namespace_does_not_skip_explicit_account_change(capture_paths):
    root, data = capture_paths
    session(root / "s.jsonl")
    first = Capture(root, data, source_identity="synthetic-account-one")
    second = Capture(root, data, source_identity="synthetic-account-two")
    assert first.scan()["messages"] == 1
    assert second.scan()["messages"] == 1
    assert first.progress_path != second.progress_path


def test_atomic_state_replace_retries_transient_windows_sharing_denial(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"status":"old"}')
    real_replace = os.replace
    attempts = []
    def sharing_denial_once(source, target):
        attempts.append(target)
        if len(attempts) == 1:
            raise PermissionError("synthetic sharing violation")
        real_replace(source, target)
    monkeypatch.setattr("recallnest.capture.os.replace", sharing_denial_once)
    atomic_json(path, {"status": "new"})
    assert json.loads(path.read_text()) == {"status": "new"}
    assert len(attempts) == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_state_read_retries_transient_windows_sharing_denial(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"status":"running"}')
    real_open = Path.open
    attempts = []
    def sharing_denial_once(target, *args, **kwargs):
        if target == path:
            attempts.append(target)
            if len(attempts) == 1:
                raise PermissionError("synthetic sharing violation")
        return real_open(target, *args, **kwargs)
    monkeypatch.setattr(Path, "open", sharing_denial_once)
    assert read_json(path, {}) == {"status": "running"}
    assert len(attempts) == 2


def test_partial_trailing_line_is_retried_and_dedup_pair_keeps_identity(capture_paths):
    root, data = capture_paths
    path = root / "session.jsonl"
    session(path)
    tail = message("first", "synthetic first", "event_msg")
    with path.open("ab") as stream:
        stream.write(tail[:17])
    assert Capture(root, data).scan()["messages"] == 1
    with path.open("ab") as stream:
        stream.write(tail[17:] + message("next", "synthetic next"))
    assert Capture(root, data).scan()["messages"] == 1
    repo = Repository(data / "recallnest.sqlite3")
    archive = repo.get_conversation(repo.list_conversations()[0]["id"])
    assert len(archive["messages"]) == 2
    assert len(archive["raw"]["records"]) == 4


def test_invalid_complete_line_never_advances_or_discards_raw_records(capture_paths):
    root, data = capture_paths
    path = root / "session.jsonl"
    session(path)
    capture = Capture(root, data)
    capture.scan()
    progress = capture.progress_path.read_bytes()
    with path.open("ab") as stream:
        stream.write(b"invalid complete line\n")
    assert capture.scan()["errors"][0]["detail"] == "Malformed JSONL at line 3"
    assert capture.progress_path.read_bytes() == progress
    session(path)
    unsupported = {"type": "response_item", "payload": {"type": "function_call", "name": "synthetic", "arguments": "{}"}}
    with path.open("ab") as stream:
        stream.write(line(unsupported))
    assert capture.scan()["processed"] == 1
    repo = Repository(data / "recallnest.sqlite3")
    assert repo.get_conversation(repo.list_conversations()[0]["id"])["raw"]["records"][-1] == unsupported


def test_split_utf8_tail_retries_and_valid_final_record_without_newline_imports(capture_paths):
    root, data = capture_paths
    path = root / "s.jsonl"
    session(path)
    tail = message("utf8", "中文 synthetic")
    split = tail.index("中".encode()) + 1
    with path.open("ab") as stream:
        stream.write(tail[:split])
    assert Capture(root, data).scan()["messages"] == 1
    with path.open("ab") as stream:
        stream.write(tail[split:-1])
    assert Capture(root, data).scan()["messages"] == 1
    repo = Repository(data / "recallnest.sqlite3")
    archive = repo.get_conversation(repo.list_conversations()[0]["id"])
    assert archive["messages"][-1]["content"] == "中文 synthetic"


def test_truncate_rewrite_replays_and_keeps_old_archive(capture_paths):
    root, data = capture_paths
    path = root / "s.jsonl"
    session(path)
    capture = Capture(root, data)
    capture.scan()
    path.write_bytes(line({"type": "session_meta", "payload": {"id": "synthetic-session"}}) + message("new", "rewritten"))
    assert capture.scan()["messages"] == 1
    repo = Repository(data / "recallnest.sqlite3")
    assert repo.stats()["messages"] == 2
    assert len(repo.get_conversation(repo.list_conversations()[0]["id"])["raw_versions"]) == 2


@pytest.mark.parametrize("mutation", ["same_size_rewrite", "append"])
def test_changed_read_never_archives_or_advances_checkpoint(capture_paths, monkeypatch, mutation):
    root, data = capture_paths
    path = root / "s.jsonl"
    session(path)
    capture = Capture(root, data)
    capture.scan()
    checkpoint = capture.progress_path.read_bytes()
    baseline = path.stat()
    prefix = line({"type": "session_meta", "payload": {"id": "synthetic-session"}})
    old = prefix + message("first", "synthetic old")
    replacement = prefix + message("first", "synthetic new")
    assert len(old) == len(replacement)
    path.write_bytes(old)
    os.utime(path, ns=(baseline.st_atime_ns, baseline.st_mtime_ns + 1_000_000_000))
    before = path.stat()
    real_fstat, inspections = os.fstat, 0

    def mutate_before_second_fstat(fd):
        nonlocal inspections
        info = real_fstat(fd)
        if (info.st_dev, info.st_ino) == (before.st_dev, before.st_ino):
            inspections += 1
            if inspections == 2:
                if mutation == "same_size_rewrite":
                    path.write_bytes(replacement)
                    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
                else:
                    with path.open("ab") as stream:
                        stream.write(message("added", "synthetic added"))
                    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                return real_fstat(fd)
        return info

    with monkeypatch.context() as patch:
        patch.setattr("recallnest.capture.os.fstat", mutate_before_second_fstat)
        result = capture.scan()
    assert result["processed"] == 0 and result["errors"] == [
        {"path": "s.jsonl", "detail": "Capture file changed while reading; retry"}]
    assert capture.progress_path.read_bytes() == checkpoint
    archived = capture.repo.get_conversation(capture.repo.list_conversations()[0]["id"])
    assert archived["messages"][0]["content"] == "synthetic first"
    assert len(archived["messages"][0]["versions"]) == 1
    assert capture.scan()["processed"] == 1
    archived = capture.repo.get_conversation(archived["id"])
    expected = "synthetic new" if mutation == "same_size_rewrite" else "synthetic old"
    assert [item["content"] for item in archived["messages"][0]["versions"]] == ["synthetic first", expected]
    if mutation == "append":
        assert archived["messages"][-1]["content"] == "synthetic added"
    assert capture.scan()["processed"] == 0


@pytest.mark.parametrize("operation", ["preview", "scan"])
@pytest.mark.parametrize("failure", ["deleted_child", "permission_denied", "entry_stat"])
def test_traversal_errors_report_relative_path_and_continue_other_sources(capture_paths, monkeypatch, operation, failure):
    root, data = capture_paths
    child = root / "affected"
    child.mkdir()
    session(root / "good.jsonl")
    capture = Capture(root, data)
    real_scandir = os.scandir

    class FailedStatEntry:
        def __init__(self, entry):
            self.entry = entry

        def __getattr__(self, name):
            return getattr(self.entry, name)

        def stat(self, **kwargs):
            raise PermissionError(f"synthetic private error: {child}")

    @contextmanager
    def unreliable_scandir(directory):
        if Path(directory) == child:
            if failure == "deleted_child":
                child.rmdir()
            elif failure == "permission_denied":
                raise PermissionError(f"synthetic private error: {child}")
        with real_scandir(directory) as entries:
            yield [FailedStatEntry(entry) if failure == "entry_stat" and Path(entry.path) == child else entry
                   for entry in entries]

    with monkeypatch.context() as patch:
        patch.setattr("recallnest.capture.os.scandir", unreliable_scandir)
        result = getattr(capture, operation)()
    assert result["processed"] == 1 and result["messages"] == 1
    assert len(result["errors"]) == 1 and result["errors"][0]["path"] == "affected"
    assert "retry" in result["errors"][0]["detail"]
    assert str(root) not in result["errors"][0]["detail"] and "synthetic private error" not in result["errors"][0]["detail"]
    if operation == "preview":
        assert not data.exists()
    else:
        assert capture.repo.stats()["messages"] == 1
    child.mkdir(exist_ok=True)
    (child / "recovered.jsonl").write_bytes(line({"type": "session_meta", "payload": {"id": "synthetic-session"}})
        + message("recovered", "synthetic recovered"))
    recovered = getattr(capture, operation)()
    assert recovered["errors"] == []
    if operation == "preview":
        assert recovered["messages"] == 2 and not data.exists()
    else:
        assert recovered["messages"] == 1 and capture.repo.stats()["messages"] == 2


def test_capture_retries_temporarily_missing_root(capture_paths):
    root, data = capture_paths
    path = root / "s.jsonl"
    session(path)
    capture = Capture(root, data)
    capture.scan()
    checkpoint = capture.progress_path.read_bytes()
    path.unlink()
    root.rmdir()
    result = capture.scan()
    assert result["processed"] == 0 and len(result["errors"]) == 1
    assert result["errors"][0]["path"] == "." and "retry" in result["errors"][0]["detail"]
    assert capture.progress_path.read_bytes() == checkpoint
    root.mkdir()
    path.write_bytes(line({"type": "session_meta", "payload": {"id": "synthetic-session"}})
        + message("recovered", "synthetic root recovered"))
    recovered = capture.scan()
    assert recovered["errors"] == [] and recovered["messages"] == 1
    assert capture.repo.stats()["messages"] == 2


def test_partial_directory_enumeration_error_keeps_discovered_files(capture_paths, monkeypatch):
    root, data = capture_paths
    session(root / "good.jsonl")
    capture = Capture(root, data)
    real_scandir = os.scandir

    @contextmanager
    def interrupted_scandir(directory):
        with real_scandir(directory) as entries:
            def interrupted_entries():
                yield from entries
                raise OSError(f"synthetic private enumeration failure: {root}")
            yield interrupted_entries()

    with monkeypatch.context() as patch:
        patch.setattr("recallnest.capture.os.scandir", interrupted_scandir)
        result = capture.scan()
    assert result["processed"] == 1 and capture.repo.stats()["messages"] == 1
    assert len(result["errors"]) == 1 and result["errors"][0]["path"] == "."
    assert str(root) not in result["errors"][0]["detail"] and "retry" in result["errors"][0]["detail"]


def test_capture_requires_explicit_existing_root_and_bounded_files(capture_paths):
    root, data = capture_paths
    with pytest.raises(ValueError, match="directory"):
        Capture(None, data)
    with pytest.raises(ValueError, match="directory"):
        Capture(root / "absent", data)
    session(root / "large.jsonl")
    assert "limit" in Capture(root, data, max_bytes=8).scan()["errors"][0]["detail"]


def test_outside_root_path_and_symlink_are_not_read(capture_paths, tmp_path):
    root, data = capture_paths
    outside = tmp_path / "outside.jsonl"
    session(outside)
    capture = Capture(root, data)
    with pytest.raises(ValueError, match="outside"):
        capture.read_file(outside)
    try:
        (root / "linked.jsonl").symlink_to(outside)
    except OSError:
        pytest.skip("OS does not permit creating symlinks")
    assert capture.preview()["files"] == 0
    assert not data.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_windows_junction_outside_root_is_not_traversed(capture_paths, tmp_path):
    root, data = capture_paths
    outside = tmp_path / "synthetic outside"
    outside.mkdir()
    session(outside / "s.jsonl")
    link = root / "junction"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", "New-Item -ItemType Junction -Path $env:taskcapturelink -Target $env:taskcapturetarget | Out-Null"],
                            env={**os.environ, "taskcapturelink": str(link), "taskcapturetarget": str(outside)}, capture_output=True, text=True, timeout=15)
    if result.returncode:
        pytest.skip("OS does not permit creating junctions")
    try:
        assert link.resolve() == outside.resolve()
        assert Capture(root, data).preview()["files"] == 0
        assert not data.exists()
    finally:
        # Remove only this synthetic junction itself, never its resolved target.
        os.rmdir(link)
    assert (outside / "s.jsonl").exists()


@pytest.mark.parametrize("pid", [os.getpid(), 2147483647])
def test_stale_pid_status_and_stop_do_not_touch_unrelated_process(capture_paths, pid):
    root, data = capture_paths
    daemon = CaptureDaemon(data)
    daemon.state_path.parent.mkdir(parents=True)
    process = psutil.Process()
    daemon.state_path.write_text(json.dumps({"pid": pid, "create_time": process.create_time(), "token": "wrong-token", "root": str(root), "status": "running"}))
    assert daemon.status()["status"] == "stopped"
    assert daemon.stop()["status"] == "stopped"
    assert process.is_running()


def test_corrupt_daemon_state_reports_safe_actionable_error(capture_paths):
    root, data = capture_paths
    daemon = CaptureDaemon(data)
    daemon.state_path.parent.mkdir(parents=True)
    daemon.state_path.write_text('["synthetic-invalid-state"]')
    with pytest.raises(ValueError, match="Capture state is unreadable"):
        daemon.status()


def wait_for(predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    pytest.fail("capture lifecycle did not complete within deadline")


def test_actual_daemon_survives_traversal_race_and_imports_after_recovery(capture_paths, tmp_path, monkeypatch):
    root, data = capture_paths
    child = root / "affected"
    child.mkdir()
    session(root / "good.jsonl")
    recovered = tmp_path / "enumeration-recovered"
    bootstrap = tmp_path / "synthetic-bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text(f'''import os
from pathlib import Path
original_scandir = os.scandir
blocked_child = Path({str(child)!r})
recovered = Path({str(recovered)!r})
def transient_scandir(path):
    if Path(path) == blocked_child and not recovered.exists():
        raise FileNotFoundError("synthetic private traversal race: " + str(blocked_child))
    return original_scandir(path)
os.scandir = transient_scandir
''', encoding="utf-8")
    source_dir = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", str(bootstrap) + os.pathsep + str(source_dir))
    daemon = CaptureDaemon(data)
    repo = Repository(data / "recallnest.sqlite3")
    try:
        assert daemon.start(root, interval=0.1)["status"] == "running"
        wait_for(lambda: bool(daemon.status().get("last_scan", {}).get("errors")))
        status = daemon.status()
        assert status["status"] == "running" and psutil.Process(status["pid"]).is_running()
        assert status["last_scan"]["errors"][0]["path"] == "affected"
        assert "synthetic private traversal race" not in status["last_scan"]["errors"][0]["detail"]
        wait_for(lambda: repo.stats()["messages"] == 1)
        (child / "later.jsonl").write_bytes(line({"type": "session_meta", "payload": {"id": "synthetic-later-session"}})
            + message("later", "synthetic later"))
        recovered.write_text("ready")
        wait_for(lambda: repo.stats()["messages"] == 2)
        wait_for(lambda: daemon.status().get("last_scan", {}).get("errors") == [])
        assert daemon.status()["status"] == "running"
    finally:
        daemon.stop()
    assert daemon.status()["status"] == "stopped"


@pytest.mark.parametrize("identity", [None, "synthetic-daemon-account"])
def test_real_capture_daemon_lifecycle_restart_append(capture_paths, identity):
    root, data = capture_paths
    path = root / "s.jsonl"
    session(path)
    daemon = CaptureDaemon(data)
    repo = Repository(data / "recallnest.sqlite3")
    try:
        started = daemon.start(root, interval=0.1, source_identity=identity)
        assert started["status"] == "running"
        assert daemon.status()["pid"] == started["pid"]
        assert daemon.status()["source_identity"] == (identity or "codex")
        with pytest.raises(ValueError, match="already"):
            daemon.start(root, interval=0.1, source_identity=identity)
        wait_for(lambda: repo.stats()["messages"] == 1)
        assert daemon.stop()["status"] == "stopped"
        with path.open("ab") as stream:
            stream.write(message("appended", "after restart"))
        assert daemon.start(root, interval=0.1, source_identity=identity)["status"] == "running"
        wait_for(lambda: repo.stats()["messages"] == 2)
    finally:
        daemon.stop()
    assert daemon.status()["status"] == "stopped"
    assert repo.stats()["messages"] == 2
    assert repo.list_conversations()[0]["source_identity"] == (identity or "codex")
