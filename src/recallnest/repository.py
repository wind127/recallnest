"""Transactional source archive and stable import identity."""
import json
from .db import Database
from .models import NormalizedConversation, NormalizedMessage, utc_iso
from .importers import fingerprint
from .repository_entities import EntityRepository, encode, new_id, escaped_like


class Repository(EntityRepository):
    def __init__(self, path):
        self.db = Database(path)

    def import_conversations(self, conversations, *, preserve_existing=False):
        """Import revisions; demo seeding alone opts to preserve already-present sources."""
        result = {"imported": 0, "updated": 0, "duplicates": 0, "messages": 0, "edited_messages": 0,
                  "duplicate_messages": 0, "errors": 0, "error_details": [], "conversation_ids": []}
        with self.db.transaction() as connection:
            for item in conversations:
                counts, conversation_id = self._import_one(connection, NormalizedConversation.model_validate(item), preserve_existing=preserve_existing)
                for key, count in counts.items():
                    result[key] += count
                result["conversation_ids"].append(conversation_id)
        return result

    def _import_one(self, connection, conversation, *, preserve_existing=False):
        stamp = utc_iso()
        identity = conversation.source_identity or conversation.source
        external_id = conversation.external_id or "fingerprint:" + fingerprint({"title": conversation.title, "raw": conversation.raw,
            "messages": [{"role": m.role, "content": m.content, "timestamp": m.timestamp, "parent_id": m.parent_id} for m in conversation.messages]})
        existing = connection.execute("SELECT * FROM conversations WHERE source=? AND source_identity=? AND external_id=?",
                                      (conversation.source, identity, external_id)).fetchone()
        conversation_id = existing["id"] if existing else new_id()
        if conversation.project_id:
            self._entity(connection, "projects", conversation.project_id)
        raw, metadata = encode(conversation.raw), encode(conversation.metadata)
        title = conversation.title
        if (existing and conversation.source == "markdown"
                and conversation.metadata.get("title_from_filename") is True):
            title = existing["title"]
        counts = {"imported": 0 if existing else 1, "updated": 0, "duplicates": 0, "messages": 0, "edited_messages": 0, "duplicate_messages": 0}
        if existing and preserve_existing:
            counts.update(duplicates=1, duplicate_messages=len(conversation.messages))
            return counts, conversation_id
        changed = not existing or any(existing[key] != value for key, value in (
            ("title", title), ("raw", raw), ("metadata", metadata), ("current_node_external", conversation.current_node)))
        if not existing:
            connection.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                conversation_id, conversation.source, identity, external_id, conversation.title,
                conversation.created_at or stamp, conversation.updated_at or stamp, stamp, conversation.project_id,
                None, conversation.current_node, 0, raw, metadata))
        rows = connection.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY position", (conversation_id,)).fetchall()
        known = {row["external_id"]: row for row in rows}
        ids = {row["external_id"]: row["id"] for row in rows}
        incoming, seen = [], set()
        for index, message in enumerate(conversation.messages):
            message_id = message.id or "fingerprint:" + fingerprint([index, message.role, message.content, message.timestamp, message.parent_id])
            if message_id in seen:
                raise ValueError("Duplicate external message IDs in source")
            seen.add(message_id)
            ids.setdefault(message_id, new_id())
            incoming.append((message_id, message))
        node_external = conversation.metadata.get("node_message_ids", {}).get(conversation.current_node, conversation.current_node)
        if conversation.current_node is not None and node_external not in ids:
            graph = conversation.raw.get("mapping", {}) if conversation.source == "chatgpt" else {}
            if conversation.current_node not in graph:
                raise ValueError("Selected current_node does not exist in conversation")
        for message_id, message in incoming:
            if message.parent_id and message.parent_id not in ids:
                raise ValueError("Message parent does not exist")
            before = known.get(message_id)
            message_raw, message_metadata = encode(message.raw), encode(message.metadata)
            message_changed = not before or any(before[key] != value for key, value in (
                ("role", message.role), ("content", message.content), ("timestamp", message.timestamp),
                ("parent_external_id", message.parent_id), ("raw", message_raw), ("metadata", message_metadata)))
            if not message_changed:
                counts["duplicate_messages"] += 1
                continue
            changed = True
            version = before["version"] + 1 if before else 1
            if before:
                counts["edited_messages"] += 1
                connection.execute("UPDATE messages SET role=?,content=?,timestamp=?,parent_external_id=?,version=?,raw=?,metadata=? WHERE id=?", (
                    message.role, message.content, message.timestamp, message.parent_id, version, message_raw, message_metadata, ids[message_id]))
            else:
                counts["messages"] += 1
                connection.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                    ids[message_id], conversation_id, message_id, message.role, message.content, message.timestamp, None,
                    message.parent_id, len(rows) + counts["messages"] - 1, version, message_raw, message_metadata))
            connection.execute("INSERT INTO raw_versions VALUES(?,?,?,?,?,?,?,?,?,?)", (
                new_id(), ids[message_id], version, message.role, message.content, message.timestamp,
                message.parent_id, message_raw, message_metadata, stamp))
        for message_id, message in incoming:
            connection.execute("UPDATE messages SET parent_id=? WHERE id=?", (ids.get(message.parent_id), ids[message_id]))
        parents = {row["id"]: row["parent_id"] for row in connection.execute("SELECT id,parent_id FROM messages WHERE conversation_id=?", (conversation_id,))}
        for message_id in parents:
            visited, current = set(), message_id
            while current:
                if current in visited:
                    raise ValueError("Message graph contains a cycle")
                visited.add(current)
                current = parents.get(current)
        if changed:
            revision = existing["revision"] + 1 if existing else 1
            node_internal = ids.get(node_external)
            if not conversation.current_node and incoming:
                node_internal = ids[incoming[-1][0]]
            connection.execute("UPDATE conversations SET title=?,updated_at=?,current_node=?,current_node_external=?,revision=?,raw=?,metadata=? WHERE id=?", (
                title, conversation.updated_at or stamp, node_internal, conversation.current_node, revision, raw, metadata, conversation_id))
            if conversation.project_id is not None:
                connection.execute("UPDATE conversations SET project_id=? WHERE id=?", (conversation.project_id, conversation_id))
            connection.execute("INSERT INTO conversation_versions VALUES(?,?,?,?,?)", (conversation_id, revision, raw, metadata, stamp))
            versions = {row["id"]: row["version"] for row in connection.execute("SELECT id,version FROM messages WHERE conversation_id=?", (conversation_id,))}
            connection.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                new_id(), "consolidate", conversation_id, revision, "queued", 0, None, None, stamp, stamp,
                encode({"message_versions": versions})))
            counts["updated"] = 1 if existing else 0
        else:
            counts["duplicates"] = 1
        return counts, conversation_id

    def _conversation(self, row):
        data = dict(row)
        data["raw"] = json.loads(data["raw"])
        data["metadata"] = json.loads(data["metadata"])
        return data

    def list_conversations(self, *, q=None, source=None, project_id=None, date_from=None, date_to=None, **ignored):
        clauses, parameters = [], []
        if q:
            clauses.append("(c.title LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND m.content LIKE ? ESCAPE '\\'))")
            parameters.extend([escaped_like(q)] * 2)
        for key, value in (("source", source), ("project_id", project_id)):
            if value is not None:
                clauses.append(f"c.{key}=?")
                parameters.append(value)
        for value, operator in ((date_from, ">="), (date_to, "<=")):
            if value:
                clauses.append(f"substr(c.created_at,1,10){operator}?")
                parameters.append(value[:10])
        sql = "SELECT c.*, (SELECT count(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count FROM conversations c"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        with self.db.read() as connection:
            result = [self._conversation(row) for row in connection.execute(sql + " ORDER BY c.updated_at DESC,c.id", parameters)]
        for item in result:
            item.pop("raw")
        return result

    def get_conversation(self, conversation_id, branch=None):
        with self.db.snapshot() as connection:
            row = connection.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if not row:
                raise KeyError("Conversation not found")
            data = self._conversation(row)
            messages = []
            for row in connection.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY position", (conversation_id,)):
                message = dict(row)
                message["raw"] = json.loads(message["raw"])
                message["metadata"] = json.loads(message["metadata"])
                message["versions"] = []
                for version in connection.execute("SELECT * FROM raw_versions WHERE message_id=? ORDER BY version", (message["id"],)):
                    archived = dict(version)
                    archived["raw"] = json.loads(archived["raw"])
                    archived["metadata"] = json.loads(archived["metadata"])
                    message["versions"].append(archived)
                messages.append(message)
            by_id = {m["id"]: m for m in messages}
            parent_ids = {m["parent_id"] for m in messages}
            leaves = [m for m in messages if m["id"] not in parent_ids]
            def path(leaf):
                result = []
                while leaf:
                    result.append(leaf)
                    leaf = by_id[leaf]["parent_id"]
                return list(reversed(result))
            selected = branch or data["current_node"] or (leaves[-1]["id"] if leaves else None)
            if selected and selected not in by_id:
                raise ValueError("Selected branch message does not exist in conversation")
            data.update(messages=messages, message_count=len(messages), active_message_ids=path(selected) if selected else [],
                branches=[{"leaf_id": m["id"], "external_id": m["external_id"], "message_ids": path(m["id"])} for m in leaves])
            data["raw_versions"] = [{**dict(row), "raw": json.loads(row["raw"]), "metadata": json.loads(row["metadata"])} for row in connection.execute(
                "SELECT * FROM conversation_versions WHERE conversation_id=? ORDER BY revision", (conversation_id,))]
            return data

    def create_conversation(self, data):
        values = dict(data)
        values["external_id"] = values.get("external_id") or new_id()
        normalized = NormalizedConversation.model_validate({**values, "raw": values})
        result = self.import_conversations([normalized])
        return self.get_conversation(result["conversation_ids"][0])

    def source_page(self, kind, source_id, *, version=None, offset=0, limit=4000):
        """Bounded MCP text projection; the lossless raw archive remains in export/detail."""
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 8000:
            raise ValueError("Invalid source page bounds")
        if version is not None and (type(version) is not int or version <= 0):
            raise ValueError("Version must be a positive integer")
        result = {"kind": kind, "source_id": source_id, "offset": offset, "limit": limit, "text": "", "total": 0, "evidence": []}
        with self.db.snapshot() as connection:
            if kind == "message":
                message = connection.execute("SELECT conversation_id,version FROM messages WHERE id=?", (source_id,)).fetchone()
                if not message:
                    raise KeyError("Source message not found")
                selected = message["version"] if version is None else version
                row = connection.execute("SELECT content FROM raw_versions WHERE message_id=? AND version=?",
                                         (source_id, selected)).fetchone()
                if not row:
                    raise KeyError("Source message version not found")
                # SQLite text length/substr stop at NUL; Python preserves all stored characters.
                text = row["content"]
                result.update(text=text[offset:offset + limit], total=len(text), version=selected,
                              conversation_id=message["conversation_id"], stale=selected != message["version"])
            elif kind == "conversation":
                row = connection.execute("SELECT revision,substr(title,1,200) AS title FROM conversations WHERE id=?", (source_id,)).fetchone()
                if not row:
                    raise KeyError("Source conversation not found")
                selected = row["revision"] if version is None else version
                if not connection.execute("SELECT 1 FROM conversation_versions WHERE conversation_id=? AND revision=?", (source_id, selected)).fetchone():
                    raise KeyError("Source conversation version not found")
                result.update(version=selected, title=row["title"], stale=selected != row["revision"])
                # Durable consolidation snapshots preserve exact internal message versions per revision.
                rows = connection.execute("SELECT m.id,rv.role,rv.content,rv.version FROM jobs j,json_each(j.payload,'$.message_versions') p "
                    "JOIN messages m ON m.id=p.key JOIN raw_versions rv ON rv.message_id=p.key AND rv.version=p.value "
                    "WHERE j.type='consolidate' AND j.conversation_id=? AND j.conversation_revision=? ORDER BY m.position", (source_id, selected))
                position, pieces = 0, []
                for message in rows:
                    text = message["role"] + ": " + message["content"] + "\n"
                    end = position + len(text)
                    if position < offset + limit and end > offset:
                        pieces.append(text[max(0, offset - position):offset + limit - position])
                        if len(result["evidence"]) < 10:
                            result["evidence"].append({"message_id": message["id"], "conversation_id": source_id, "message_version": message["version"]})
                    position = end
                result.update(text="".join(pieces), total=position)
            elif kind in ("knowledge", "memory"):
                table = "knowledge" if kind == "knowledge" else "memories"
                current = self._entity(connection, table, source_id)
                histories = connection.execute("SELECT payload FROM entity_history WHERE entity_type=? AND entity_id=? ORDER BY recorded_at,rowid", (table, source_id)).fetchall()
                selected = len(histories) + 1 if version is None else version
                if selected > len(histories) + 1:
                    raise KeyError("Source entity version not found")
                data = current if selected == len(histories) + 1 else json.loads(histories[selected - 1]["payload"])
                text = data["content"] if kind == "memory" else "\n\n".join([data["title"], data["summary"], data["body"]])
                enriched = self._enrich_entity(connection, table, data, history=False)
                result.update(version=selected, text=text[offset:offset + limit], total=len(text), stale=selected != len(histories) + 1,
                    evidence_total=len(enriched["evidence"]),
                    evidence=[{"message_id": proof["message_id"], "conversation_id": proof["conversation_id"], "message_version": proof["message_version"],
                               "quote": proof["quote"][:250], "quote_truncated": len(proof["quote"]) > 250, "stale": proof["stale"]} for proof in enriched["evidence"][:5]])
            else:
                raise ValueError("Source kind must be conversation, message, knowledge or memory")
        next_offset = offset + len(result["text"])
        result["next_offset"] = next_offset if next_offset < result["total"] else None
        return result

    def append_messages(self, conversation_id, messages, current_node=None):
        with self.db.transaction():
            return self._append_messages_locked(conversation_id, messages, current_node)

    def _append_messages_locked(self, conversation_id, messages, current_node):
        existing = self.get_conversation(conversation_id)
        normalized = [NormalizedMessage.model_validate(item) for item in messages]
        by_external = {m["external_id"]: m for m in existing["messages"]}
        selected = next((m["external_id"] for m in existing["messages"] if m["id"] == existing["current_node"]), None)
        seen = set()
        for index, message in enumerate(normalized):
            supplied = set(message.model_fields_set)
            message.id = message.id or new_id()
            if message.id in seen:
                raise ValueError("Duplicate external message IDs in append")
            seen.add(message.id)
            before = by_external.get(message.id)
            if before:
                if "parent_id" not in message.model_fields_set:
                    message.parent_id = before["parent_external_id"]
                if "timestamp" not in message.model_fields_set:
                    message.timestamp = before["timestamp"]
                if "metadata" not in supplied:
                    message.metadata = before["metadata"]
            elif "parent_id" not in message.model_fields_set:
                message.parent_id = normalized[index - 1].id if index else selected
            same_text_fields = before and all(before[key] == value for key, value in (
                ("role", message.role), ("content", message.content), ("timestamp", message.timestamp), ("parent_external_id", message.parent_id)))
            if "raw" not in supplied:
                message.raw = before["raw"] if same_text_fields else message.model_dump(exclude={"raw"})
        unchanged = all(message.id in by_external and all(by_external[message.id][key] == value for key, value in (
            ("role", message.role), ("content", message.content), ("timestamp", message.timestamp),
            ("parent_external_id", message.parent_id), ("raw", message.raw), ("metadata", message.metadata))) for message in normalized)
        if unchanged and current_node is None:
            return existing
        node = current_node if current_node is not None else normalized[-1].id if normalized else existing["current_node_external"]
        self.import_conversations([NormalizedConversation(source=existing["source"], source_identity=existing["source_identity"],
            external_id=existing["external_id"], title=existing["title"], created_at=existing["created_at"], project_id=existing["project_id"],
            current_node=node, messages=normalized, raw={"source_record": existing["raw"].get("source_record", existing["raw"]), "messages": [m.model_dump() for m in normalized]}, metadata=existing["metadata"])])
        return self.get_conversation(conversation_id)

    def update_conversation(self, conversation_id, changes):
        if set(changes) - {"title", "project_id", "current_node"}:
            raise ValueError("Only title, project_id and current_node may be edited")
        with self.db.transaction() as connection:
            row = connection.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if not row:
                raise KeyError("Conversation not found")
            if changes.get("project_id"):
                self._entity(connection, "projects", changes["project_id"])
            if changes.get("current_node") and not connection.execute("SELECT 1 FROM messages WHERE id=? AND conversation_id=?", (changes["current_node"], conversation_id)).fetchone():
                raise ValueError("Selected branch does not exist")
            for key, value in changes.items():
                if key == "title" and (not isinstance(value, str) or not value.strip()):
                    raise ValueError("Title must not be empty")
                connection.execute(f"UPDATE conversations SET {key}=?,updated_at=? WHERE id=?", (value, utc_iso(), conversation_id))
        return self.get_conversation(conversation_id)

    def list_jobs(self, status=None):
        with self.db.read() as connection:
            rows = connection.execute("SELECT * FROM jobs" + (" WHERE status=?" if status else "") + " ORDER BY created_at,id", (status,) if status else ())
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def stats(self):
        with self.db.read() as connection:
            result = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("conversations", "messages", "knowledge", "projects", "memories", "reviews", "jobs")}
        result["confirmed_memories"] = len(self.active_memories())
        result["due_reviews"] = len(self.list_reviews(due=True))
        return result

    def export_data(self):
        with self.db.snapshot():
            return self._export_snapshot()

    def _export_snapshot(self):
        with self.db.read() as connection:
            history = [{**dict(row), "payload": json.loads(row["payload"])} for row in connection.execute("SELECT * FROM entity_history ORDER BY recorded_at,rowid")]
        return {"schema_version": 1, "exported_at": utc_iso(),
                "conversations": [self.get_conversation(item["id"]) for item in self.list_conversations()],
                "knowledge": self.list_knowledge(), "projects": self.list_projects(), "memories": self.list_memories(),
                "reviews": self.list_reviews(), "jobs": self.list_jobs(), "entity_history": history}

    def export_markdown(self):
        archive = self.export_data()
        parts = ["# RecallNest archive", "", "Text archive; JSON export contains complete raw records and revision history."]
        for conversation in archive["conversations"]:
            parts.extend(["", "## " + conversation["title"], f"Source: {conversation['source']} · ID: {conversation['id']}"])
            for message in conversation["messages"]:
                parts.extend(["", f"### {message['role']} ({message['id']}, version {message['version']})", message["content"]])
        for table in ("knowledge", "projects", "memories", "reviews"):
            parts.extend(["", "## " + table.title()])
            for item in archive[table]:
                heading = item.get("title", item.get("name", item.get("question", item.get("subject") or item.get("category", "Entry"))))
                body = item.get("body", item.get("description", item.get("content", item.get("answer", ""))))
                parts.extend(["", "### " + heading, body])
                for evidence in item.get("evidence", []):
                    parts.append(f"Evidence: message {evidence['message_id']} v{evidence['message_version']} — {evidence['quote']}")
        return "\n".join(parts) + "\n"
