"""Derived entities, evidence validation and simple review scheduling."""
from datetime import datetime, timedelta
import json
import uuid
from .models import KnowledgeInput, ProjectInput, MemoryInput, ReviewInput, utc_iso


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def new_id():
    return str(uuid.uuid4())


def escaped_like(value):
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


MODELS = {"knowledge": KnowledgeInput, "projects": ProjectInput, "memories": MemoryInput, "reviews": ReviewInput}


class EntityRepository:
    def _entity(self, connection, table, entity_id):
        row = connection.execute(f"SELECT payload FROM {table} WHERE id=?", (entity_id,)).fetchone()
        if not row:
            raise KeyError(f"{table} entry not found")
        return json.loads(row["payload"])

    def _save_entity(self, connection, table, data):
        searchable = " ".join(str(data.get(key, "")) for key in ("title", "summary", "body", "content", "subject", "name", "description", "question", "answer"))
        searchable += " " + " ".join(data.get("tags", []))
        connection.execute(f"INSERT INTO {table}(id,payload,search_text) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,search_text=excluded.search_text",
                           (data["id"], encode(data), searchable))

    def _history(self, connection, table, data):
        connection.execute("INSERT INTO entity_history VALUES(?,?,?,?,?)", (new_id(), table, data["id"], encode(data), utc_iso()))

    def _validate_evidence(self, connection, evidence):
        result = []
        for item in evidence:
            message = connection.execute("SELECT * FROM messages WHERE id=?", (item["message_id"],)).fetchone()
            if not message:
                raise ValueError("Evidence message does not exist")
            if item.get("conversation_id") and item["conversation_id"] != message["conversation_id"]:
                raise ValueError("Evidence conversation does not match message")
            version = item.get("message_version")
            if version is None:
                version = message["version"]
            if type(version) is not int or version <= 0:
                raise ValueError("Evidence message_version must be a positive integer")
            raw = connection.execute("SELECT content FROM raw_versions WHERE message_id=? AND version=?", (message["id"], version)).fetchone()
            if not raw or item["quote"] not in raw["content"]:
                raise ValueError("Evidence quote must occur in the referenced message version")
            result.append({"message_id": message["id"], "conversation_id": message["conversation_id"], "message_version": version, "quote": item["quote"]})
        return result

    def _enrich_entity(self, connection, table, data, history=True):
        for evidence in data.get("evidence", []):
            message = connection.execute("SELECT version FROM messages WHERE id=?", (evidence["message_id"],)).fetchone()
            evidence["stale"] = not message or message["version"] != evidence["message_version"]
        if history:
            data["history"] = [json.loads(row["payload"]) for row in connection.execute(
                "SELECT payload FROM entity_history WHERE entity_type=? AND entity_id=? ORDER BY recorded_at,rowid", (table, data["id"]))]
        if table == "reviews":
            data["grade_history"] = [dict(row) for row in connection.execute("SELECT * FROM review_history WHERE review_id=? ORDER BY reviewed_at,rowid", (data["id"],))]
        return data

    def _validate_links(self, connection, data, inherit_fields=()):
        if data.get("project_id"):
            self._entity(connection, "projects", data["project_id"])
        if data.get("knowledge_id"):
            knowledge = self._entity(connection, "knowledge", data["knowledge_id"])
            if "project_id" in inherit_fields:
                data["project_id"] = knowledge["project_id"]
            if "evidence" in inherit_fields:
                data["evidence"] = knowledge["evidence"]

    def _supersede(self, connection, data):
        if not data.get("supersedes"):
            return
        if data["supersedes"] == data["id"]:
            raise ValueError("Memory cannot supersede itself")
        if data["status"] == "confirmed" and data["effective_at"] and data["effective_at"] > utc_iso():
            raise ValueError("A confirmed supersession cannot have a future effective_at; save a candidate and confirm when effective")
        old = self._entity(connection, "memories", data["supersedes"])
        if old["subject"] != data["subject"] or old["category"] != data["category"]:
            raise ValueError("Supersession requires the same category and subject")
        ancestor, seen = old, {data["id"]}
        while ancestor.get("supersedes"):
            if ancestor["id"] in seen or ancestor["supersedes"] in seen:
                raise ValueError("Supersession cannot form a cycle")
            seen.add(ancestor["id"])
            ancestor = self._entity(connection, "memories", ancestor["supersedes"])
        if data["status"] == "confirmed" and old["status"] != "superseded":
            self._history(connection, "memories", old)
            old["status"] = "superseded"
            old["updated_at"] = utc_iso()
            self._save_entity(connection, "memories", old)

    def _create_entity(self, table, values, now=None):
        validated = MODELS[table].model_validate(values)
        data = validated.model_dump()
        inherit_fields = {"project_id", "evidence"} - validated.model_fields_set if table == "reviews" else set()
        stamp = utc_iso(now)
        data.update(id=new_id(), created_at=stamp, updated_at=stamp)
        if table == "memories":
            data["effective_at"] = data["effective_at"] or stamp
        if table == "reviews":
            data.update(due_at=data["due_at"] or stamp, interval_minutes=0, repetitions=0)
        with self.db.transaction() as connection:
            self._validate_links(connection, data, inherit_fields=inherit_fields)
            if "evidence" in data:
                data["evidence"] = self._validate_evidence(connection, data["evidence"])
            if table == "memories":
                self._supersede(connection, data)
            self._save_entity(connection, table, data)
            return self._enrich_entity(connection, table, data)

    def _update_entity(self, table, entity_id, changes):
        allowed = set(MODELS[table].model_fields)
        if set(changes) - allowed:
            raise ValueError("Unknown or read-only fields: " + ", ".join(sorted(set(changes) - allowed)))
        with self.db.transaction() as connection:
            old = self._entity(connection, table, entity_id)
            values = {key: old[key] for key in allowed}
            values.update(changes)
            data = MODELS[table].model_validate(values).model_dump()
            data.update(id=entity_id, created_at=old["created_at"], updated_at=utc_iso())
            if "source_context" in old:
                data["source_context"] = old["source_context"]
            if table == "reviews":
                data.update(interval_minutes=old["interval_minutes"], repetitions=old["repetitions"])
                data["due_at"] = data["due_at"] or old["due_at"]
            self._validate_links(connection, data)
            if "evidence" in data:
                data["evidence"] = self._validate_evidence(connection, data["evidence"])
            if table == "memories":
                self._supersede(connection, data)
            self._history(connection, table, old)
            self._save_entity(connection, table, data)
            return self._enrich_entity(connection, table, data)

    def _get_entity(self, table, entity_id):
        with self.db.read() as connection:
            return self._enrich_entity(connection, table, self._entity(connection, table, entity_id))

    def _list_entities(self, table, *, q=None, source=None, project_id=None, type=None, tag=None, date_from=None,
                       date_to=None, favorite=None, unresolved=None, status=None, category=None, paused=None, due=False, now=None):
        with self.db.read() as connection:
            sql = f"SELECT payload FROM {table}"
            arguments = []
            if q:
                sql += " WHERE search_text LIKE ? ESCAPE '\\'"
                arguments.append(escaped_like(q))
            items = [json.loads(row["payload"]) for row in connection.execute(sql, arguments)]
            result = []
            stamp = utc_iso(now)
            for data in items:
                if any(expected is not None and data.get(key) != expected for key, expected in (
                    ("project_id", project_id), ("type", type), ("favorite", favorite), ("unresolved", unresolved),
                    ("status", status), ("category", category), ("paused", paused))):
                    continue
                if tag and tag not in data.get("tags", []):
                    continue
                date = data.get("due_at", data["created_at"])[:10]
                if (date_from and date < date_from[:10]) or (date_to and date > date_to[:10]):
                    continue
                if due and (data.get("paused") or data.get("due_at", stamp) > stamp):
                    continue
                if source and data.get("source") != source:
                    origins = {row["source"] for item in data.get("evidence", []) for row in connection.execute(
                        "SELECT source FROM conversations WHERE id=?", (item["conversation_id"],))}
                    if source not in origins:
                        continue
                result.append(self._enrich_entity(connection, table, data, history=False))
            return sorted(result, key=lambda data: (data.get("due_at", data["created_at"]), data["id"]), reverse=table != "reviews")

    def _delete_entity(self, table, entity_id):
        with self.db.transaction() as connection:
            self._entity(connection, table, entity_id)
            if table == "memories" and any(json.loads(row["payload"]).get("supersedes") == entity_id for row in connection.execute("SELECT payload FROM memories")):
                raise ValueError("Memory is referenced by supersession history; expire it instead")
            if table == "projects":
                connection.execute("UPDATE conversations SET project_id=NULL WHERE project_id=?", (entity_id,))
                for related in ("knowledge", "reviews"):
                    for row in connection.execute(f"SELECT payload FROM {related}").fetchall():
                        data = json.loads(row["payload"])
                        if data.get("project_id") == entity_id:
                            self._history(connection, related, data)
                            data["project_id"] = None
                            data["updated_at"] = utc_iso()
                            self._save_entity(connection, related, data)
            if table == "knowledge":
                for row in connection.execute("SELECT payload FROM reviews").fetchall():
                    data = json.loads(row["payload"])
                    if data.get("knowledge_id") == entity_id:
                        self._history(connection, "reviews", data)
                        data["knowledge_id"] = None
                        self._save_entity(connection, "reviews", data)
            self._history(connection, table, self._entity(connection, table, entity_id))
            connection.execute(f"DELETE FROM {table} WHERE id=?", (entity_id,))

    def create_knowledge(self, data): return self._create_entity("knowledge", data)
    def update_knowledge(self, entity_id, changes): return self._update_entity("knowledge", entity_id, changes)
    def get_knowledge(self, entity_id): return self._get_entity("knowledge", entity_id)
    def list_knowledge(self, **filters): return self._list_entities("knowledge", **filters)
    def delete_knowledge(self, entity_id): return self._delete_entity("knowledge", entity_id)
    def create_project(self, data): return self._create_entity("projects", data)
    def update_project(self, entity_id, changes): return self._update_entity("projects", entity_id, changes)
    def get_project(self, entity_id): return self._get_entity("projects", entity_id)
    def list_projects(self, **filters): return self._list_entities("projects", **filters)
    def delete_project(self, entity_id): return self._delete_entity("projects", entity_id)
    def create_memory(self, data): return self._create_entity("memories", data)
    def update_memory(self, entity_id, changes): return self._update_entity("memories", entity_id, changes)
    def get_memory(self, entity_id): return self._get_entity("memories", entity_id)
    def list_memories(self, **filters): return self._list_entities("memories", **filters)
    def delete_memory(self, entity_id): return self._delete_entity("memories", entity_id)
    def create_review(self, data, now=None): return self._create_entity("reviews", data, now=now)
    def update_review(self, entity_id, changes): return self._update_entity("reviews", entity_id, changes)
    def get_review(self, entity_id): return self._get_entity("reviews", entity_id)
    def list_reviews(self, **filters): return self._list_entities("reviews", **filters)
    def delete_review(self, entity_id): return self._delete_entity("reviews", entity_id)

    def active_memories(self, now=None):
        stamp = utc_iso(now)
        active = []
        for memory in self.list_memories(status="confirmed"):
            if (memory["expires_at"] and memory["expires_at"] <= stamp) or (memory["effective_at"] and memory["effective_at"] > stamp):
                continue
            evidence = memory.get("evidence", [])
            current = [proof for proof in evidence if not proof.get("stale")]
            if not current and (evidence or memory["source"] != "manual"):
                continue
            memory["evidence"] = current
            # Original derivation metadata can cite old versions; keep it in archive/detail.
            memory.pop("source_context", None)
            active.append(memory)
        return active

    def grade_review(self, review_id, grade, now=None):
        if grade not in ("again", "hard", "good", "easy"):
            raise ValueError("Unknown review grade")
        stamp = utc_iso(now)
        with self.db.transaction() as connection:
            data = self._entity(connection, "reviews", review_id)
            if data["paused"]:
                raise ValueError("Cannot grade a paused card")
            previous, interval = data["due_at"], data["interval_minutes"]
            minutes = {"again": 10, "hard": max(1440, int(interval * 1.2)),
                       "good": max(4320, interval * 2), "easy": max(10080, interval * 3)}[grade]
            self._history(connection, "reviews", data)
            data.update(due_at=utc_iso(datetime.fromisoformat(stamp) + timedelta(minutes=minutes)),
                        interval_minutes=minutes, repetitions=data["repetitions"] + 1, updated_at=stamp)
            self._save_entity(connection, "reviews", data)
            connection.execute("INSERT INTO review_history VALUES(?,?,?,?,?,?,?)", (new_id(), review_id, grade, stamp, previous, data["due_at"], minutes))
            return self._enrich_entity(connection, "reviews", data)

    def project_links(self, project_id):
        project = self.get_project(project_id)
        return {"project_id": project_id, "artifact_links": project["artifact_links"],
                "conversations": self.list_conversations(project_id=project_id), "knowledge": self.list_knowledge(project_id=project_id),
                "reviews": self.list_reviews(project_id=project_id)}
