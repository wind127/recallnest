"""Local-only handoff: the MCP host supplies intelligence, SQLite keeps progress."""
import hashlib
import json

from .ai_schema import validate_extraction
from .jobs import JobService
from .models import utc_iso
from .repository_entities import encode, new_id


SOURCE_BYTES = 18000  # Escaped JSON, leaving room inside the MCP response envelope.
OUTPUT_BYTES = 512000


def size(value):
    return len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8"))


def version_hash(conversation):
    return hashlib.sha256(encode({m["id"]: m["version"] for m in conversation["messages"]}).encode()).hexdigest()


class CodexConsolidation:
    def __init__(self, repository):
        self.repo = repository
        # Only the shared transactional entity insertion is used, never a model client.
        self.inserter = JobService(repository, None)

    def _provider_running(self, connection, conversation_id):
        if connection.execute("SELECT 1 FROM jobs WHERE conversation_id=? AND status='running'", (conversation_id,)).fetchone():
            raise ValueError("Provider job is running; stop it and use serve --no-ai before Codex consolidation")

    def _pending(self, connection, conversation):
        done = {(r["message_id"], r["version"]) for r in connection.execute(
            "SELECT p.* FROM processed_messages p JOIN messages m ON m.id=p.message_id WHERE m.conversation_id=?", (conversation["id"],))}
        return [m for m in conversation["messages"] if m["content"].strip() and (m["id"], m["version"]) not in done]

    def _settle_jobs(self, connection, conversation, *, disposition="codex"):
        stamp = utc_iso()
        # Earlier queued revisions have been replaced by the current archive snapshot.
        old = connection.execute("SELECT id FROM jobs WHERE conversation_id=? AND conversation_revision<>? AND status IN ('queued','failed')",
                                 (conversation["id"], conversation["revision"])).fetchall()
        for row in old:
            connection.execute("UPDATE jobs SET status='completed',error=NULL,error_kind=NULL,updated_at=? WHERE id=?", (stamp, row["id"]))
            connection.execute("INSERT INTO job_runs(job_id,disposition) VALUES(?,'superseded') ON CONFLICT(job_id) DO UPDATE SET disposition='superseded'", (row["id"],))
        if disposition == "codex" and self._pending(connection, conversation):
            return
        totals = {"knowledge": 0, "memories": 0, "reviews": 0, "processed_messages": 0}
        for row in connection.execute("SELECT result FROM codex_batches WHERE conversation_id=? AND revision=? AND result IS NOT NULL",
                                      (conversation["id"], conversation["revision"])):
            for key, count in json.loads(row["result"])["counts"].items():
                totals[key] += count
        jobs = connection.execute("SELECT id FROM jobs WHERE conversation_id=? AND conversation_revision=? AND status IN ('queued','failed')",
                                  (conversation["id"], conversation["revision"])).fetchall()
        for row in jobs:
            connection.execute("UPDATE jobs SET status='completed',error=NULL,error_kind=NULL,updated_at=? WHERE id=?", (stamp, row["id"]))
            connection.execute("INSERT INTO job_runs(job_id,disposition,result) VALUES(?,?,?) ON CONFLICT(job_id) "
                               "DO UPDATE SET disposition=excluded.disposition,result=excluded.result,token=NULL,lease_until=NULL,next_attempt_at=NULL", (row["id"], disposition, encode(totals)))

    def prepare(self, conversation_id=None):
        if conversation_id is not None and (not isinstance(conversation_id, str) or not 1 <= len(conversation_id) <= 200):
            raise ValueError("Conversation ID must be an internal archive ID")
        with self.repo.db.transaction() as connection:
            if conversation_id:
                ids = [conversation_id]
            else:
                ids = [r["id"] for r in connection.execute("SELECT c.id FROM conversations c WHERE "
                    "EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND NOT EXISTS "
                    "(SELECT 1 FROM processed_messages p WHERE p.message_id=m.id AND p.version=m.version)) OR "
                    "EXISTS (SELECT 1 FROM jobs j WHERE j.conversation_id=c.id AND j.conversation_revision=c.revision "
                    "AND j.status IN ('queued','failed')) ORDER BY c.created_at,c.id")]
            for current_id in ids:
                conversation = self.repo.get_conversation(current_id)
                if conversation["source"].startswith("demo:") or conversation["metadata"].get("synthetic"):
                    self._provider_running(connection, current_id)
                    self._settle_jobs(connection, conversation, disposition="synthetic_skipped")
                    continue
                self._provider_running(connection, current_id)
                pending = self._pending(connection, conversation)
                if not pending:
                    self._settle_jobs(connection, conversation)
                    continue
                message = pending[0]
                progress = connection.execute("SELECT next_offset FROM codex_progress WHERE message_id=? AND version=?", (message["id"], message["version"])).fetchone()
                offset = progress["next_offset"] if progress else 0
                fingerprint = version_hash(conversation)
                batch_key = hashlib.sha256(encode([current_id, conversation["revision"], fingerprint, message["id"], message["version"], offset]).encode()).hexdigest()
                row = connection.execute("SELECT * FROM codex_batches WHERE batch_key=?", (batch_key,)).fetchone()
                if row:
                    return json.loads(row["request"])
                part = {key: message[key] for key in ("id", "role", "version", "conversation_id", "parent_id")}
                leaves = [b["leaf_id"] for b in conversation["branches"] if message["id"] in b["message_ids"]]
                part.update(offset=offset, total=len(message["content"]), branch_leaf_ids=leaves[:32], branch_count=len(leaves), branch_leaf_ids_truncated=len(leaves) > 32)
                result = {"status": "ready", "batch_id": new_id(), "conversation_id": current_id, "revision": conversation["revision"],
                          "title": conversation["title"][:200], "title_truncated": len(conversation["title"]) > 200,
                          "messages": [part], "untrusted_source": True}
                # Bound escaped bytes as well as characters, including emoji and NUL.
                low, high = 1, min(3500, len(message["content"]) - offset)
                while low < high:
                    middle = (low + high + 1) // 2
                    part["content"] = message["content"][offset:offset + middle]
                    if size(result) <= SOURCE_BYTES:
                        low = middle
                    else:
                        high = middle - 1
                part["content"] = message["content"][offset:offset + low]
                if size(result) > SOURCE_BYTES:
                    raise ValueError("Source metadata exceeds Codex batch limit")
                connection.execute("INSERT INTO codex_batches VALUES(?,?,?,?,?,?,?,NULL)",
                    (result["batch_id"], batch_key, current_id, conversation["revision"], fingerprint, encode(result), utc_iso()))
                return result
            return {"status": "idle", "untrusted_source": True}

    def complete(self, batch_id, output):
        if not isinstance(batch_id, str) or not 1 <= len(batch_id) <= 200:
            raise ValueError("Batch ID must come from prepare_consolidation")
        if size(output) > OUTPUT_BYTES:
            raise ValueError("Consolidation output exceeds byte limit")
        with self.repo.db.transaction() as connection:
            row = connection.execute("SELECT * FROM codex_batches WHERE id=?", (batch_id,)).fetchone()
            if not row:
                raise KeyError("Consolidation batch not found")
            if row["result"] is not None:
                return {**json.loads(row["result"]), "replayed": True}
            conversation = self.repo.get_conversation(row["conversation_id"])
            if conversation["revision"] != row["revision"] or version_hash(conversation) != row["versions_hash"]:
                raise ValueError("Source changed; discard this output and call prepare_consolidation again")
            self._provider_running(connection, conversation["id"])
            request = json.loads(row["request"])
            part = request["messages"][0]
            progress = connection.execute("SELECT next_offset FROM codex_progress WHERE message_id=? AND version=?", (part["id"], part["version"])).fetchone()
            if (progress["next_offset"] if progress else 0) != part["offset"]:
                raise ValueError("Batch is no longer current; call prepare_consolidation again")
            if connection.execute("SELECT 1 FROM processed_messages WHERE message_id=? AND version=?", (part["id"], part["version"])).fetchone():
                raise ValueError("Source was already processed; call prepare_consolidation again")
            try:
                outputs = validate_extraction(output, request["messages"], conversation["messages"])
            except (ValueError, TypeError, KeyError):
                raise ValueError("Invalid consolidation: check schema, exact chunk quotes and user-only verbatim memory evidence") from None
            counts = {"knowledge": 0, "memories": 0, "reviews": 0, "processed_messages": 0}
            for table, values in outputs:
                counts[table] += int(self.inserter._insert(connection, table, values, conversation))
            end = part["offset"] + len(part["content"])
            connection.execute("INSERT INTO codex_progress VALUES(?,?,?) ON CONFLICT(message_id,version) DO UPDATE SET next_offset=excluded.next_offset",
                               (part["id"], part["version"], end))
            if end == part["total"]:
                connection.execute("INSERT OR IGNORE INTO processed_messages VALUES(?,?)", (part["id"], part["version"]))
                counts["processed_messages"] = 1
            result = {"status": "completed", "batch_id": batch_id, "conversation_id": conversation["id"], "revision": row["revision"],
                      "counts": counts, "replayed": False}
            connection.execute("UPDATE codex_batches SET result=? WHERE id=?", (encode(result), batch_id))
            self._settle_jobs(connection, conversation)
            return result
