import sqlite3

import pytest

from recallnest import db as db_module
from recallnest.db import Database


@pytest.fixture
def observed_connections(monkeypatch):
    connections = []
    real_connect = sqlite3.connect

    def observe_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(db_module.sqlite3, "connect", observe_connect)
    try:
        yield connections
    finally:
        # Keep real connections alive until teardown so GC cannot hide a leak.
        # Close every reference even when an assertion fails, for Windows cleanup.
        for connection in connections:
            connection.close()


def test_database_constructor_does_not_open_or_create_files(tmp_path, observed_connections):
    path = tmp_path / "not-created" / "archive.sqlite3"

    database = Database(path)

    assert database._ready is False
    assert observed_connections == []
    assert not path.parent.exists()


def test_schema_initialization_closes_its_connection(tmp_path, observed_connections):
    database = Database(tmp_path / "archive.sqlite3")

    connection = database.connect()

    assert len(observed_connections) == 2
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        observed_connections[0].execute("SELECT 1")
    assert database._ready is True
    assert connection is observed_connections[1]
    assert connection.execute("SELECT count(*) FROM knowledge").fetchone()[0] == 0
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert connection.row_factory is sqlite3.Row

    connection.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")


def test_failed_schema_initialization_closes_and_can_retry(tmp_path, observed_connections, monkeypatch):
    database = Database(tmp_path / "archive.sqlite3")
    schema = db_module.SCHEMA
    monkeypatch.setattr(db_module, "SCHEMA", schema + """
        BEGIN;
        INSERT INTO knowledge VALUES ('failed-init', '{}', 'synthetic');
        SELECT * FROM missing_schema_init_table;
    """)

    with pytest.raises(sqlite3.OperationalError, match="missing_schema_init_table"):
        database.connect()

    assert database._ready is False
    assert len(observed_connections) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        observed_connections[0].execute("SELECT 1")

    monkeypatch.setattr(db_module, "SCHEMA", schema)
    connection = database.connect()

    assert database._ready is True
    assert len(observed_connections) == 3
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        observed_connections[1].execute("SELECT 1")
    assert connection is observed_connections[2]
    assert connection.execute("SELECT count(*) FROM knowledge").fetchone()[0] == 0
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
