"""SQLite connections are lazy: importing the ASGI app writes no user data."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import threading


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, source_identity TEXT NOT NULL,
 external_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, imported_at TEXT NOT NULL, project_id TEXT,
 current_node TEXT, current_node_external TEXT, revision INTEGER NOT NULL,
 raw TEXT NOT NULL, metadata TEXT NOT NULL,
 UNIQUE(source, source_identity, external_id)
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 external_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
 timestamp TEXT, parent_id TEXT REFERENCES messages(id), parent_external_id TEXT,
 position INTEGER NOT NULL, version INTEGER NOT NULL, raw TEXT NOT NULL, metadata TEXT NOT NULL,
 UNIQUE(conversation_id, external_id)
);
CREATE TABLE IF NOT EXISTS raw_versions (
 id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(id),
 version INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
 timestamp TEXT, parent_external_id TEXT, raw TEXT NOT NULL, metadata TEXT NOT NULL,
 recorded_at TEXT NOT NULL, UNIQUE(message_id, version)
);
CREATE TABLE IF NOT EXISTS conversation_versions (
 conversation_id TEXT NOT NULL REFERENCES conversations(id), revision INTEGER NOT NULL,
 raw TEXT NOT NULL, metadata TEXT NOT NULL, recorded_at TEXT NOT NULL,
 PRIMARY KEY(conversation_id, revision)
);
CREATE TABLE IF NOT EXISTS knowledge (id TEXT PRIMARY KEY, payload TEXT NOT NULL, search_text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, payload TEXT NOT NULL, search_text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, payload TEXT NOT NULL, search_text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, payload TEXT NOT NULL, search_text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entity_history (
 id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
 payload TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_history (
 id TEXT PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
 grade TEXT NOT NULL, reviewed_at TEXT NOT NULL, previous_due_at TEXT NOT NULL,
 next_due_at TEXT NOT NULL, interval_minutes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, type TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 conversation_revision INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
 attempts INTEGER NOT NULL DEFAULT 0, error TEXT, error_kind TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL,
 UNIQUE(type, conversation_id, conversation_revision)
);
CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, position);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, created_at);
CREATE TABLE IF NOT EXISTS job_runs (
 job_id TEXT PRIMARY KEY REFERENCES jobs(id), token TEXT, lease_until TEXT,
 next_attempt_at TEXT, disposition TEXT, result TEXT
);
CREATE TABLE IF NOT EXISTS derived_sources (
 derivation_key TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS processed_messages (
 message_id TEXT NOT NULL REFERENCES messages(id), version INTEGER NOT NULL,
 PRIMARY KEY(message_id,version)
);
CREATE TABLE IF NOT EXISTS vectors (
 entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, content_hash TEXT NOT NULL,
 provider_id TEXT NOT NULL, model TEXT NOT NULL, vector TEXT NOT NULL,
 PRIMARY KEY(entity_type,entity_id,provider_id,model)
);
CREATE TABLE IF NOT EXISTS chat_turns (
 client_turn_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 user_message_id TEXT NOT NULL REFERENCES messages(id), assistant_message_id TEXT REFERENCES messages(id),
 request_hash TEXT NOT NULL, context TEXT, token TEXT, lease_until TEXT
);
"""


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._local = threading.local()
        self._ready = False

    def connect(self):
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(self.path)) as connection, connection:
                    connection.execute("PRAGMA journal_mode=WAL")
                    connection.executescript(SCHEMA)
                    connection.execute("PRAGMA user_version=1")
                self._ready = True
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self):
        active = getattr(self._local, "write_connection", None)
        if active is not None:
            yield active
            return
        connection = self.connect()
        previous_read = getattr(self._local, "read_connection", None)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._local.write_connection = connection
            self._local.read_connection = connection
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._local.write_connection = None
            self._local.read_connection = previous_read
            connection.close()

    @contextmanager
    def read(self):
        active = getattr(self._local, "read_connection", None)
        if active is not None:
            yield active
            return
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def snapshot(self):
        """Reuse one SQLite read transaction across an entire archive operation."""
        active = getattr(self._local, "read_connection", None)
        if active is not None:
            yield active
            return
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            self._local.read_connection = connection
            yield connection
        finally:
            self._local.read_connection = None
            connection.rollback()
            connection.close()
