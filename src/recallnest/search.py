"""Stable text/cosine retrieval and explicit, persisted optional indexing."""
import hashlib
import json
import math
import re
from .ai import AIError, finite_vector
from .repository_entities import encode


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def provider_identity(settings):
    return digest(encode([settings.base_url.rstrip("/"), settings.api_key]))


def cosine(left, right):
    if len(left) != len(right):
        return None
    try:
        left, right = finite_vector(left), finite_vector(right)
        left_norm, right_norm = math.hypot(*left), math.hypot(*right)
        value = sum((a / left_norm) * (b / right_norm) for a, b in zip(left, right))
        return max(-1.0, min(1.0, value)) if math.isfinite(value) else None
    except AIError:
        return None


class SearchService:
    def __init__(self, repository, ai_factory):
        self.repo, self.ai_factory = repository, ai_factory

    def documents(self, **filters):
        documents = []
        with self.repo.db.snapshot() as connection:
            conversations = {row["id"]: dict(row) for row in connection.execute("SELECT * FROM conversations")}
            for c in conversations.values():
                documents.append({"id": c["id"], "entity_type": "conversation", "title": c["title"], "text": c["title"],
                    "source": c["source"], "project_id": c["project_id"], "type": "conversation", "tags": [], "content_version": c["revision"], "created_at": c["created_at"], "evidence": []})
            for row in connection.execute("SELECT * FROM messages"):
                c = conversations[row["conversation_id"]]
                documents.append({"id": row["id"], "entity_type": "message", "title": c["title"], "text": row["content"],
                    "source": c["source"], "project_id": c["project_id"], "type": "message", "tags": [], "content_version": row["version"], "created_at": row["timestamp"] or c["created_at"],
                    "evidence": [{"message_id": row["id"], "conversation_id": c["id"], "message_version": row["version"], "quote": row["content"][:500], "stale": False}] if row["content"] else []})
            for table, items in (("knowledge", self.repo.list_knowledge()), ("memory", self.repo.active_memories())):
                for item in items:
                    text = " ".join(item.get(k, "") for k in ("title", "summary", "body", "content", "subject"))
                    evidence = item.get("evidence", [])
                    origins = {conversations[e["conversation_id"]]["source"] for e in evidence if e["conversation_id"] in conversations}
                    documents.append({"id": item["id"], "entity_type": table, "title": item.get("title", item.get("subject") or item.get("category", "Memory")),
                        "text": text, "source": item["source"], "source_origins": origins, "project_id": item.get("project_id"), "type": item.get("type", "memory"),
                        "tags": item.get("tags", []), "content_version": item["updated_at"], "created_at": item["created_at"], "evidence": evidence})
        result = []
        for doc in documents:
            if any(filters.get(key) is not None and doc.get(key) != filters[key] for key in ("project_id", "type", "entity_type")):
                continue
            if filters.get("source") and filters["source"] != doc["source"] and filters["source"] not in doc.get("source_origins", set()):
                continue
            if filters.get("tag") and filters["tag"] not in doc["tags"]:
                continue
            if filters.get("date_from") and doc["created_at"][:10] < str(filters["date_from"]):
                continue
            if filters.get("date_to") and doc["created_at"][:10] > str(filters["date_to"]):
                continue
            doc["content_hash"] = digest(encode([doc["text"], doc["content_version"]]))
            result.append(doc)
        return sorted(result, key=lambda doc: (doc["entity_type"], doc["id"]))

    def search(self, q, *, limit=20, semantic=False, **filters):
        if not q.strip() or len(q) > 2000 or not 1 <= limit <= 50:
            raise ValueError("Search requires a non-empty query up to 2000 characters and limit from 1 to 50")
        docs = self.documents(**filters)
        query = q.casefold()
        vectors, query_vector, mode, warning = {}, None, "text", None
        ai = self.ai_factory()
        if semantic:
            try:
                query_vector = ai.embeddings([q])[0]
                identity = provider_identity(ai.settings)
                with self.repo.db.read() as connection:
                    vectors = {(row["entity_type"], row["entity_id"]): row for row in connection.execute(
                        "SELECT * FROM vectors WHERE provider_id=? AND model=?", (identity, ai.settings.embedding_model))}
                mode = "hybrid"
            except AIError as error:
                warning = {"error_kind": error.kind, "detail": error.message}
        ranked = []
        for doc in docs:
            text = doc["text"].casefold()
            text_score = min(1.0, 0.6 + min(text.count(query), 8) * 0.05) if query in text else 0.0
            if text_score == 0:
                tokens = set(re.findall(r"[a-z0-9_]{2,}", query))
                for run in re.findall(r"[\u3400-\u9fff]+", query):
                    tokens.update(run[i:i + 2] for i in range(len(run) - 1))
                if tokens:
                    text_score = 0.5 * sum(token in text for token in tokens) / len(tokens)
            semantic_score = None
            vector = vectors.get((doc["entity_type"], doc["id"]))
            if query_vector is not None and vector and vector["content_hash"] == doc["content_hash"]:
                try:
                    semantic_score = cosine(query_vector, json.loads(vector["vector"]))
                except (ValueError, TypeError):
                    pass
            if text_score == 0 and (semantic_score is None or semantic_score <= 0):
                continue
            score = min(1.0, text_score * 0.7 + max(0.0, semantic_score or 0) * 0.3) if mode == "hybrid" else text_score
            ranked.append({"id": doc["id"], "entity_type": doc["entity_type"], "title": doc["title"], "excerpt": doc["text"][:1000],
                "source": doc["source"], "project_id": doc["project_id"], "type": doc["type"], "tags": doc["tags"],
                "created_at": doc["created_at"], "evidence": doc["evidence"], "score": round(score, 6),
                "text_score": round(text_score, 6), "semantic_score": round(semantic_score, 6) if semantic_score is not None else None})
        ranked.sort(key=lambda item: (-item["score"], item["entity_type"], item["id"]))
        return {"items": ranked[:limit], "mode": mode, "warning": warning}

    def reindex(self):
        docs, ai = self.documents(), self.ai_factory()
        if not ai.settings.base_url or not ai.settings.embedding_model:
            raise AIError("configuration_required", "Configure a provider base URL and embedding model first")
        identity = provider_identity(ai.settings)
        outputs = []
        # Every character participates, including single texts longer than a provider context.
        for doc in docs:
            text = doc["text"] or " "
            parts = [text[i:i + 3500] for i in range(0, len(text), 3500)]
            vectors = []
            for start in range(0, len(parts), 8):
                vectors.extend(ai.embeddings(parts[start:start + 8]))
            if len({len(v) for v in vectors}) != 1:
                raise AIError("invalid_output", "Provider embedding dimensions changed during indexing")
            total = sum(len(part) for part in parts)
            averaged = [sum(vector[i] * len(part) / total for vector, part in zip(vectors, parts)) for i in range(len(vectors[0]))]
            outputs.append((doc, finite_vector(averaged)))
        if len({len(vector) for _, vector in outputs}) > 1:
            raise AIError("invalid_output", "Provider returned inconsistent embedding dimensions")
        indexed, skipped = 0, 0
        with self.repo.db.transaction() as connection:
            current = {(doc["entity_type"], doc["id"]): doc["content_hash"] for doc in self.documents()}
            for doc, vector in outputs:
                if current.get((doc["entity_type"], doc["id"])) != doc["content_hash"]:
                    skipped += 1
                    continue
                connection.execute("INSERT INTO vectors VALUES(?,?,?,?,?,?) ON CONFLICT(entity_type,entity_id,provider_id,model) "
                    "DO UPDATE SET content_hash=excluded.content_hash,vector=excluded.vector", (doc["entity_type"], doc["id"], doc["content_hash"], identity, ai.settings.embedding_model, encode(vector)))
                indexed += 1
        return {"indexed": indexed, "skipped_changed": skipped, "model": ai.settings.embedding_model, "status": "completed"}
