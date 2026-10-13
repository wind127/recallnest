"""Durable consolidation with leased claims and atomic source-version commits."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import threading
from .ai import AIError, preview_metadata, extraction_fits
from .ai_schema import normalized
from .models import utc_iso
from .repository_entities import encode, new_id


MAX_ATTEMPTS = 3
LEASE_SECONDS = 120


def later(stamp, seconds):
    return utc_iso(datetime.fromisoformat(stamp) + timedelta(seconds=seconds))


def source_chunks(conversation, pending, model=""):
    """Lossless character slices including every branch. No last-N history cutoff."""
    batch = []
    for message in conversation["messages"]:
        if (message["id"], message["version"]) not in pending:
            continue
        leaves = [b["leaf_id"] for b in conversation["branches"] if message["id"] in b["message_ids"]]
        # Avoid unbounded duplicated branch metadata on very wide imported trees.
        branch_key = hashlib.sha256(encode(leaves).encode()).hexdigest()
        base = {key: message[key] for key in ("id", "role", "version", "conversation_id", "parent_id")}
        base.update(preview_metadata("external_id", message["external_id"]))
        base.update(branch_leaf_ids=leaves[:32], branch_count=len(leaves), branch_set_hash=branch_key)
        text = message["content"]
        if not text.strip():
            continue
        offset = 0
        while offset < len(text):
            low, high = 1, min(3500, len(text) - offset)
            if not extraction_fits(conversation, [{**base, "offset": offset, "content": text[offset:offset + 1]}], model):
                raise AIError("input_limit", "Extraction metadata exceeded its serialized input budget")
            while low < high:
                middle = (low + high + 1) // 2
                if extraction_fits(conversation, [{**base, "offset": offset, "content": text[offset:offset + middle]}], model):
                    low = middle
                else:
                    high = middle - 1
            part = {**base, "offset": offset, "content": text[offset:offset + low]}
            if batch and not extraction_fits(conversation, batch + [part], model):
                yield batch
                batch = []
            batch.append(part)
            offset += low
    if batch:
        yield batch


class JobService:
    def __init__(self, repository, ai_factory, *, clock=None):
        self.repo, self.ai_factory = repository, ai_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stop_event, self.wake_event = threading.Event(), threading.Event()
        self.thread = None

    def now(self):
        return utc_iso(self.clock())

    def list(self, status=None):
        if status is not None and status not in ("queued", "running", "completed", "failed"):
            raise ValueError("Unknown job status")
        with self.repo.db.snapshot() as connection:
            items = self.repo.list_jobs(status)
            for item in items:
                row = connection.execute("SELECT * FROM job_runs WHERE job_id=?", (item["id"],)).fetchone()
                item.update(next_attempt_at=row["next_attempt_at"] if row else None,
                            disposition=row["disposition"] if row else None,
                            result=json.loads(row["result"]) if row and row["result"] else None)
            return items

    def get(self, job_id):
        item = next((item for item in self.list() if item["id"] == job_id), None)
        if item is None:
            raise KeyError("Job not found")
        return item

    def recover(self, now=None):
        stamp = utc_iso(now) if now else self.now()
        with self.repo.db.transaction() as connection:
            rows = connection.execute("SELECT j.id,j.attempts FROM jobs j LEFT JOIN job_runs r ON j.id=r.job_id "
                "WHERE j.status='running' AND (r.lease_until IS NULL OR r.lease_until<=?)", (stamp,)).fetchall()
            for row in rows:
                status = "queued" if row["attempts"] < MAX_ATTEMPTS else "failed"
                connection.execute("UPDATE jobs SET status=?,error=?,error_kind='interrupted',updated_at=? WHERE id=?",
                    (status, "Previous execution was interrupted", stamp, row["id"]))
                connection.execute("INSERT INTO job_runs(job_id) VALUES(?) ON CONFLICT(job_id) DO NOTHING", (row["id"],))
                connection.execute("UPDATE job_runs SET token=NULL,lease_until=NULL,next_attempt_at=NULL WHERE job_id=?", (row["id"],))
            return len(rows)

    def claim(self, job_id=None, *, force=False):
        stamp, token = self.now(), new_id()
        with self.repo.db.transaction() as connection:
            condition = " AND j.id=?" if job_id else ""
            rows = connection.execute("SELECT j.*,r.next_attempt_at FROM jobs j LEFT JOIN job_runs r ON r.job_id=j.id "
                "WHERE j.status='queued' AND j.attempts<?" + condition + " ORDER BY j.created_at,j.id", (MAX_ATTEMPTS, job_id) if job_id else (MAX_ATTEMPTS,)).fetchall()
            row = next((row for row in rows if force or not row["next_attempt_at"] or row["next_attempt_at"] <= stamp), None)
            if not row:
                return None
            connection.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='queued'", (stamp, row["id"]))
            connection.execute("INSERT INTO job_runs(job_id,token,lease_until) VALUES(?,?,?) ON CONFLICT(job_id) "
                "DO UPDATE SET token=excluded.token,lease_until=excluded.lease_until,next_attempt_at=NULL", (row["id"], token, later(stamp, LEASE_SECONDS)))
            return {**dict(row), "status": "running", "payload": json.loads(row["payload"]), "token": token}

    def _owned(self, connection, claim):
        return connection.execute("SELECT 1 FROM jobs j JOIN job_runs r ON r.job_id=j.id "
            "WHERE j.id=? AND j.status='running' AND r.token=? AND r.lease_until>?", (claim["id"], claim["token"], self.now())).fetchone() is not None

    def _source_current(self, connection, claim):
        row = connection.execute("SELECT revision FROM conversations WHERE id=?", (claim["conversation_id"],)).fetchone()
        versions = {row["id"]: row["version"] for row in connection.execute("SELECT id,version FROM messages WHERE conversation_id=?", (claim["conversation_id"],))}
        return row and row["revision"] == claim["conversation_revision"] and versions == claim["payload"]["message_versions"]

    def _renew(self, claim):
        with self.repo.db.transaction() as connection:
            if not self._owned(connection, claim):
                return False
            connection.execute("UPDATE job_runs SET lease_until=? WHERE job_id=? AND token=?", (later(self.now(), LEASE_SECONDS), claim["id"], claim["token"]))
            return True

    def _insert(self, connection, table, values, conversation):
        derivation_key = hashlib.sha256(encode([conversation["id"], table, values]).encode()).hexdigest()
        if connection.execute("SELECT 1 FROM derived_sources WHERE derivation_key=?", (derivation_key,)).fetchone():
            return False
        entity = None
        if table == "memories":
            for row in connection.execute("SELECT payload FROM memories"):
                candidate = json.loads(row["payload"])
                if all(normalized(candidate[key]) == normalized(values[key]) for key in ("content", "category", "subject")):
                    entity = candidate
                    merged = list(candidate["evidence"])
                    for evidence in values["evidence"]:
                        if evidence not in merged:
                            merged.append(evidence)
                    if merged != candidate["evidence"]:
                        self.repo._history(connection, table, candidate)
                        candidate["evidence"] = self.repo._validate_evidence(connection, merged)
                        candidate["updated_at"] = self.now()
                        self.repo._save_entity(connection, table, candidate)
                    break
        if entity is None:
            if table in ("knowledge", "reviews"):
                values = {**values, "project_id": conversation["project_id"]}
            entity = self.repo._create_entity(table, values)
            entity.pop("history", None)
            entity.pop("grade_history", None)
            for evidence in entity["evidence"]:
                evidence.pop("stale", None)
            by_id = {m["id"]: m for m in conversation["messages"]}
            entity["source_context"] = {"conversation_id": conversation["id"], "revision": conversation["revision"], "source": conversation["source"],
                "messages": [{"id": evidence["message_id"], "role": by_id[evidence["message_id"]]["role"],
                    "parent_id": by_id[evidence["message_id"]]["parent_id"], "version": evidence["message_version"],
                    "branch_leaf_ids": [branch["leaf_id"] for branch in conversation["branches"] if evidence["message_id"] in branch["message_ids"]]} for evidence in entity["evidence"]]}
            self.repo._save_entity(connection, table, entity)
        connection.execute("INSERT INTO derived_sources VALUES(?,?,?)", (derivation_key, table, entity["id"]))
        return True

    def finish(self, claim, outputs, *, disposition="extracted", conversation=None, processed=()):
        with self.repo.db.transaction() as connection:
            if not self._owned(connection, claim):
                return False
            if not self._source_current(connection, claim):
                outputs, processed, disposition = [], (), "superseded"
            counts = {"knowledge": 0, "memories": 0, "reviews": 0, "processed_messages": len(processed)}
            for table, values in outputs:
                counts[table] += int(self._insert(connection, table, values, conversation))
            connection.executemany("INSERT OR IGNORE INTO processed_messages VALUES(?,?)", list(processed))
            connection.execute("UPDATE jobs SET status='completed',error=NULL,error_kind=NULL,updated_at=? WHERE id=?", (self.now(), claim["id"]))
            connection.execute("UPDATE job_runs SET disposition=?,result=?,token=NULL,lease_until=NULL,next_attempt_at=NULL WHERE job_id=?",
                               (disposition, encode(counts), claim["id"]))
            return True

    def fail(self, claim, error):
        with self.repo.db.transaction() as connection:
            if not self._owned(connection, claim):
                return
            current = connection.execute("SELECT attempts FROM jobs WHERE id=?", (claim["id"],)).fetchone()["attempts"]
            retry = error.retryable and current < MAX_ATTEMPTS
            connection.execute("UPDATE jobs SET status=?,error=?,error_kind=?,updated_at=? WHERE id=?",
                ("queued" if retry else "failed", error.message, error.kind, self.now(), claim["id"]))
            connection.execute("UPDATE job_runs SET token=NULL,lease_until=NULL,next_attempt_at=? WHERE job_id=?",
                (later(self.now(), 2 ** current * 5) if retry else None, claim["id"]))

    def run(self, job_id=None, *, force=False):
        if job_id:
            self.get(job_id)
        claim = self.claim(job_id, force=force)
        if claim is None:
            return self.get(job_id) if job_id else None
        try:
            conversation = self.repo.get_conversation(claim["conversation_id"])
            with self.repo.db.read() as connection:
                current = self._source_current(connection, claim)
                done = {(row["message_id"], row["version"]) for row in connection.execute("SELECT * FROM processed_messages")}
            if not current:
                self.finish(claim, [], disposition="superseded")
            elif conversation["source"].startswith("demo:") or conversation["metadata"].get("synthetic"):
                self.finish(claim, [], disposition="synthetic_skipped")
            else:
                pending = {(m["id"], m["version"]) for m in conversation["messages"] if m["content"].strip()} - done
                if not pending:
                    self.finish(claim, [], disposition="no_new_text")
                    return self.get(claim["id"])
                ai = self.ai_factory()
                if not ai.settings.model_configured:
                    raise AIError("configuration_required", "Configure a provider base URL and chat model first")
                with self.repo.db.transaction() as connection:
                    if not self._owned(connection, claim):
                        return self.get(claim["id"])
                    connection.execute("UPDATE jobs SET attempts=attempts+1 WHERE id=?", (claim["id"],))
                outputs = []
                for parts in source_chunks(conversation, pending, ai.settings.chat_model):
                    if self.stop_event.is_set() or not self._renew(claim):
                        raise AIError("interrupted", "Execution interrupted before completion", retryable=True)
                    outputs.extend(ai.extract(conversation, parts))
                self.finish(claim, outputs, conversation=conversation, processed=pending)
        except AIError as error:
            self.fail(claim, error)
        except Exception:
            # Never persist exception strings containing source/provider credentials.
            self.fail(claim, AIError("internal_error", "Consolidation failed; retry or inspect the local source"))
        return self.get(claim["id"])

    def retry(self, job_id):
        with self.repo.db.transaction() as connection:
            job = self.get(job_id)
            if job["status"] == "running":
                raise ValueError("Cannot retry a running job")
            connection.execute("UPDATE jobs SET status='queued',attempts=0,error=NULL,error_kind=NULL,updated_at=? WHERE id=?", (self.now(), job_id))
            connection.execute("UPDATE job_runs SET token=NULL,lease_until=NULL,next_attempt_at=NULL,disposition=NULL,result=NULL WHERE job_id=?", (job_id,))
        self.wake_event.set()
        return self.get(job_id)

    def wake_configuration(self):
        with self.repo.db.transaction() as connection:
            connection.execute("UPDATE jobs SET status='queued',error=NULL,error_kind=NULL,updated_at=? WHERE status='failed' AND error_kind='configuration_required'", (self.now(),))
        self.wake_event.set()

    def start(self):
        self.stop_event.clear()
        self.recover()
        self.thread = threading.Thread(target=self._loop, name="recallnest-jobs", daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.recover()
                result = self.run()
            except Exception:
                result = None
            if result is None:
                self.wake_event.wait(0.5)
                self.wake_event.clear()

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                raise RuntimeError("Worker did not stop before shutdown deadline")
