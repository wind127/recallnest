"""Opt-in Codex capture with replay-safe archival and cooperative process ownership."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid

import psutil

from .config import get_settings
from .importers import ImportFailure, ImportLimitExceeded, parse_upload
from .repository import Repository


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 5
        while True:
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows readers/antivirus can briefly deny atomic replacement.
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, default):
    deadline = time.monotonic() + 5
    while True:
        try:
            with path.open(encoding="utf-8") as stream:
                value = json.load(stream)
            if not isinstance(value, dict):
                raise ValueError("Expected capture state object")
            return value
        except FileNotFoundError:
            return default
        except PermissionError:
            if time.monotonic() >= deadline:
                raise ValueError("Capture state is unreadable; check the private data directory") from None
            time.sleep(0.02)
        except (ValueError, OSError):
            raise ValueError("Capture state is unreadable; check the private data directory") from None


@contextmanager
def file_lock(path):
    """OS advisory lock released by the kernel even when a process crashes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        deadline = time.monotonic() + 5
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError("Capture is busy; retry after the current operation") from None
                time.sleep(0.02)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def resolve_root(root):
    if root is None or not str(root).strip():
        raise ValueError("Capture requires an explicit existing directory")
    path = Path(root).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Capture requires an explicit existing directory")
    return path


class Capture:
    def __init__(self, root, data_dir=None, *, max_bytes=None, source_identity=None):
        self.root = resolve_root(root)
        settings = get_settings(data_dir)
        self.data_dir = settings.data_dir.resolve()
        self.max_bytes = settings.max_upload_bytes if max_bytes is None else max_bytes
        if type(self.max_bytes) is not int or self.max_bytes <= 0:
            raise ValueError("Capture byte limit must be a positive integer")
        self.identity = source_identity or "codex"
        # Source identity matches ordinary historical imports; root is checkpoint scope.
        root_key = json.dumps([os.path.normcase(str(self.root)), self.identity], ensure_ascii=True)
        progress_key = hashlib.sha256(root_key.encode()).hexdigest()
        self.progress_path = self.data_dir / "capture" / (progress_key + ".json")
        self.repo = Repository(self.data_dir / "recallnest.sqlite3")

    def _inside(self, path):
        resolved = path.resolve()
        try:
            inside = os.path.normcase(os.path.commonpath([self.root, resolved])) == os.path.normcase(str(self.root))
        except ValueError:
            inside = False
        if not inside:
            raise ValueError("Capture path is outside the configured directory")
        return resolved

    def files(self, errors=None):
        errors = [] if errors is None else errors
        pending = [self.root]
        while pending:
            directory = pending.pop()
            discovered = []
            try:
                self._inside(directory)
                with os.scandir(directory) as entries:
                    discovered.extend(entries)
            except OSError:
                errors.append({"path": directory.relative_to(self.root).as_posix(),
                               "detail": "Unable to inspect capture directory; check permissions and retry"})
            for entry in sorted(discovered, key=lambda item: item.name):
                path = Path(entry.path)
                try:
                    attributes = entry.stat(follow_symlinks=False)
                    # Junctions are reparse points on Windows; never traverse them.
                    if entry.is_symlink() or getattr(attributes, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                        continue
                    self._inside(path)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
                    elif entry.is_file(follow_symlinks=False) and path.suffix.lower() == ".jsonl":
                        yield path
                except OSError:
                    errors.append({"path": path.relative_to(self.root).as_posix(),
                                   "detail": "Unable to inspect capture entry; check permissions and retry"})

    def read_file(self, path):
        path = Path(path)
        resolved = self._inside(path)
        if path.is_symlink():
            raise ValueError("Capture does not read symbolic links")
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if before.st_size > self.max_bytes:
                raise ImportLimitExceeded("Capture file exceeds upload byte limit")
            content = stream.read(self.max_bytes + 1)
            after = os.fstat(stream.fileno())
        if len(content) > self.max_bytes:
            raise ImportLimitExceeded("Capture file exceeds upload byte limit")
        current = path.stat()
        stable = all(getattr(before, field) == getattr(after, field) == getattr(current, field)
                     for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns"))
        if self._inside(path) != resolved or not stable or len(content) != after.st_size:
            raise ValueError("Capture file changed while reading; retry")
        # Hold incomplete JSON/UTF-8 back; a complete closed log needs no final newline.
        end = max(content.rfind(b"\n"), content.rfind(b"\r")) + 1
        tail = content[end:]
        if tail.strip():
            try:
                json.loads(tail.decode("utf-8"))
                end = len(content)
            except (ValueError, UnicodeDecodeError):
                pass
        complete = content[:end]
        parsed = parse_upload(path.name, complete, source_identity=self.identity,
                              max_upload_bytes=self.max_bytes) if complete.strip() else []
        return parsed, {"size": len(content), "offset": end, "sha256": hashlib.sha256(content).hexdigest(),
                        "mtime_ns": after.st_mtime_ns, "inode": after.st_ino}

    def _scan(self, commit):
        progress = read_json(self.progress_path, {"files": {}}) if commit else {"files": {}}
        if not isinstance(progress, dict) or not isinstance(progress.get("files"), dict):
            raise ValueError("Capture progress is invalid; check the private data directory")
        result = {"files": 0, "processed": 0, "conversations": 0, "messages": 0, "errors": [], "items": []}
        for path in self.files(result["errors"]):
            result["files"] += 1
            key = path.relative_to(self.root).as_posix()
            try:
                info = path.stat()
                previous = progress["files"].get(key)
                if commit and previous and all(previous.get(name) == value for name, value in (
                        ("size", info.st_size), ("mtime_ns", info.st_mtime_ns), ("inode", info.st_ino))):
                    continue
                conversations, checkpoint = self.read_file(path)
                if commit:
                    # Repository commit precedes checkpoint. A crash replays through stable dedup.
                    imported = self.repo.import_conversations(conversations)
                    progress["files"][key] = checkpoint
                    atomic_json(self.progress_path, progress)
                    messages = imported["messages"]
                else:
                    messages = sum(len(conversation.messages) for conversation in conversations)
                result["processed"] += 1
                result["conversations"] += len(conversations)
                result["messages"] += messages
                result["items"].append({"path": key, "messages": messages, "pending_bytes": checkpoint["size"] - checkpoint["offset"]})
            except (ImportFailure, ValueError) as error:
                result["errors"].append({"path": key, "detail": str(error)})
            except OSError:
                result["errors"].append({"path": key, "detail": "Unable to read capture file; check permissions and retry"})
        return result

    def preview(self):
        return self._scan(False)

    def scan(self):
        with file_lock(self.data_dir / "capture" / "scan.lock"):
            return self._scan(True)


class CaptureDaemon:
    def __init__(self, data_dir=None):
        self.data_dir = get_settings(data_dir).data_dir.resolve()
        self.state_path = self.data_dir / "capture" / "daemon.json"
        self.lock_path = self.data_dir / "capture" / "daemon.lock"
        self.stop_path = self.data_dir / "capture" / "stop.json"

    def _owned(self, state):
        try:
            if not isinstance(state, dict) or type(state.get("pid")) is not int or not isinstance(state.get("token"), str):
                return False
            process = psutil.Process(state["pid"])
            command = process.cmdline()
            return (process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                    and process.create_time() == state.get("create_time")
                    and command[1:4] == ["-m", "recallnest", "_capture-worker"]
                    and "--token" in command and command[command.index("--token") + 1] == state["token"])
        except (psutil.Error, IndexError):
            return False

    def status(self):
        state = read_json(self.state_path, {})
        if not self._owned(state):
            return {"status": "stopped", "stale": bool(state and state.get("status") != "stopped")}
        return {key: state[key] for key in ("status", "pid", "root", "source_identity", "heartbeat", "last_scan") if key in state}

    def start(self, root, *, interval=1.0, source_identity=None):
        root = resolve_root(root)
        if not 0.05 <= interval <= 3600:
            raise ValueError("Capture interval must be between 0.05 and 3600 seconds")
        with file_lock(self.lock_path):
            if self._owned(read_json(self.state_path, {})):
                raise ValueError("Capture is already running")
            token = uuid.uuid4().hex
            self.stop_path.unlink(missing_ok=True)
            command = [sys.executable, "-m", "recallnest", "_capture-worker", "--root", str(root),
                       "--data-dir", str(self.data_dir), "--token", token, "--interval", str(interval)]
            if source_identity:
                command.extend(["--source-identity", source_identity])
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            with (self.state_path.parent / "daemon.log").open("ab") as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log, **options)
            try:
                created = psutil.Process(process.pid).create_time()
            except psutil.Error:
                raise ValueError("Capture worker did not start; check capture/daemon.log") from None
            atomic_json(self.state_path, {"pid": process.pid, "create_time": created, "token": token,
                                         "root": str(root), "source_identity": source_identity or "codex", "status": "starting", "heartbeat": time.time()})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = self.status()
            if state["status"] == "running":
                return state
            if process.poll() is not None:
                raise ValueError("Capture worker exited; check capture/daemon.log")
            time.sleep(0.05)
        raise ValueError("Capture worker is still starting; check capture status and daemon.log")

    def stop(self, *, timeout=15):
        with file_lock(self.lock_path):
            state = read_json(self.state_path, {})
            if not self._owned(state):
                return {"status": "stopped", "stale": bool(state)}
            atomic_json(self.stop_path, {"token": state["token"]})
            state["status"] = "stopping"
            atomic_json(self.state_path, state)
        deadline = time.monotonic() + timeout
        while self._owned(state):
            if time.monotonic() >= deadline:
                raise ValueError("Capture is still stopping; wait and check status")
            time.sleep(0.05)
        return {"status": "stopped", "stale": False}

    def run(self, root, token, interval, source_identity=None):
        capture = Capture(root, self.data_dir, source_identity=source_identity)
        # Parent publishes identity after Popen; do not scan before registration.
        deadline = time.monotonic() + 10
        while True:
            state = read_json(self.state_path, {})
            if state.get("token") == token:
                break
            if time.monotonic() >= deadline:
                return
            time.sleep(0.05)
        # Windows venv launchers may start a child interpreter with a different PID.
        # Register the actual worker, never assume Popen.pid is the Python process.
        with file_lock(self.lock_path):
            state = read_json(self.state_path, {})
            if state.get("token") != token:
                return
            state.update(pid=os.getpid(), create_time=psutil.Process().create_time())
            atomic_json(self.state_path, state)
        try:
            while read_json(self.stop_path, {}).get("token") != token:
                scanned = capture.scan()
                with file_lock(self.lock_path):
                    state = read_json(self.state_path, {})
                    if state.get("token") != token:
                        return
                    stopping = read_json(self.stop_path, {}).get("token") == token
                    state.update(status="stopping" if stopping else "running", heartbeat=time.time(), last_scan=scanned)
                    atomic_json(self.state_path, state)
                deadline = time.monotonic() + interval
                while time.monotonic() < deadline and read_json(self.stop_path, {}).get("token") != token:
                    time.sleep(min(0.1, interval))
        finally:
            with file_lock(self.lock_path):
                state = read_json(self.state_path, {})
                if state.get("token") == token:
                    # All scans and checkpoint writes have finished before stopped.
                    state.update(status="stopped", heartbeat=time.time())
                    atomic_json(self.state_path, state)
