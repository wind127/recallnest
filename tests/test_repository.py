import json
import pytest
from recallnest.importers import parse_upload
from recallnest.repository import Repository


def imported(repo, sample_bytes):
    result = repo.import_conversations(parse_upload("history.json", sample_bytes))
    return result, repo.list_conversations()[0]


def test_repeat_import_and_restart_are_idempotent(repo, sample_bytes):
    first, conversation = imported(repo, sample_bytes)
    assert first["imported"] == 1 and first["messages"] == 2
    assert repo.import_conversations(parse_upload("history.json", sample_bytes))["duplicates"] == 1
    other = Repository(repo.db.path)
    assert len(other.get_conversation(conversation["id"])["messages"]) == 2
    assert len(other.list_jobs()) == 1


def test_append_and_edit_preserve_raw_versions(repo, sample_bytes):
    _, conversation = imported(repo, sample_bytes)
    data = json.loads(sample_bytes)
    data["messages"][0]["content"] = "我喜欢用中文，编辑后的内容"
    data["messages"].append({"id": "u2", "role": "user", "content": "新增", "parent_id": "a1"})
    result = repo.import_conversations(parse_upload("history.json", json.dumps(data).encode()))
    detail = repo.get_conversation(conversation["id"])
    assert result["updated"] == 1 and result["messages"] == 1 and result["edited_messages"] == 1
    assert detail["revision"] == 2
    assert len(detail["messages"][0]["versions"]) == 2
    assert "100%" in detail["messages"][0]["versions"][0]["content"]
    assert len(repo.list_jobs()) == 2


def test_source_identity_separates_same_external_id(repo, sample_bytes):
    a = parse_upload("x.json", sample_bytes, source_identity="account-a")
    b = parse_upload("x.json", sample_bytes, source_identity="account-b")
    assert repo.import_conversations(a)["imported"] == 1
    assert repo.import_conversations(b)["imported"] == 1


def test_no_id_fingerprint_does_not_depend_on_filename(repo):
    data = b'{"source":"notes","title":"Title","messages":[{"role":"user","content":"Text"}]}'
    repo.import_conversations(parse_upload("a.json", data))
    assert repo.import_conversations(parse_upload("b.json", data))["duplicates"] == 1


def test_branch_path_resolves_internal_ids(repo):
    from test_importers import chatgpt
    repo.import_conversations(parse_upload("conversations.json", json.dumps(chatgpt()).encode()))
    detail = repo.get_conversation(repo.list_conversations()[0]["id"])
    active = {m["external_id"] for m in detail["messages"] if m["id"] in detail["active_message_ids"]}
    assert active == {"u", "b"}
    assert len(detail["branches"]) == 2
    branch_a = next(m["id"] for m in detail["messages"] if m["external_id"] == "a")
    assert len(repo.get_conversation(detail["id"], branch=branch_a)["active_message_ids"]) == 2


def test_chinese_and_literal_percent_search(repo, sample_bytes):
    _, conv = imported(repo, sample_bytes)
    message = repo.get_conversation(conv["id"])["messages"][0]
    evidence = [{"message_id": message["id"], "quote": "中文学习"}]
    repo.create_knowledge({"title": "中文学习 100%", "body": "复习", "tags": ["学习"], "evidence": evidence})
    repo.create_knowledge({"title": "英文", "body": "other"})
    assert len(repo.list_knowledge(q="中文")) == 1
    assert len(repo.list_knowledge(q="%")) == 1
    assert len(repo.list_knowledge(source="fixture", tag="学习")) == 1
    assert len(repo.list_knowledge(q="_")) == 0


def test_evidence_must_reference_existing_message_and_real_quote(repo, sample_bytes):
    with pytest.raises(ValueError, match="message"):
        repo.create_knowledge({"title": "bad", "evidence": [{"message_id": "missing", "quote": "text"}]})
    _, conv = imported(repo, sample_bytes)
    message = repo.get_conversation(conv["id"])["messages"][0]
    with pytest.raises(ValueError, match="quote"):
        repo.create_knowledge({"title": "bad", "evidence": [{"message_id": message["id"], "quote": "fabricated"}]})


def test_project_links_and_delete_preserve_source_records(repo, sample_bytes):
    project = repo.create_project({"name": "Project", "goals": ["learn"], "artifact_links": [{"title": "repo", "url": "https://example.com"}]})
    _, conv = imported(repo, sample_bytes)
    repo.update_conversation(conv["id"], {"project_id": project["id"]})
    knowledge = repo.create_knowledge({"title": "Linked", "project_id": project["id"]})
    links = repo.project_links(project["id"])
    assert links["conversations"][0]["id"] == conv["id"]
    assert links["knowledge"][0]["id"] == knowledge["id"]
    repo.delete_project(project["id"])
    assert repo.get_knowledge(knowledge["id"])["project_id"] is None


def test_append_uses_selected_branch_and_does_not_nest_raw_archive(repo):
    from test_importers import chatgpt
    repo.import_conversations(parse_upload("conversations.json", json.dumps(chatgpt()).encode()))
    conv = repo.get_conversation(repo.list_conversations()[0]["id"])
    branch_a = next(m["id"] for m in conv["messages"] if m["external_id"] == "a")
    repo.update_conversation(conv["id"], {"current_node": branch_a})
    first = repo.append_messages(conv["id"], [{"id": "u2", "role": "user", "content": "Next"}])
    assert first["messages"][-1]["parent_id"] == branch_a
    second = repo.append_messages(conv["id"], [{"id": "a2", "role": "assistant", "content": "Reply"}])
    assert "source_record" not in second["raw"].get("source_record", {})


def test_append_with_same_external_id_is_idempotent(repo):
    conv = repo.create_conversation({"title": "Manual"})
    repo.append_messages(conv["id"], [{"id": "u1", "role": "user", "content": "Hi"}])
    again = repo.append_messages(conv["id"], [{"id": "u1", "role": "user", "content": "Hi"}])
    assert len(again["messages"]) == 1 and again["revision"] == 2


def test_transaction_rolls_back_invalid_graph(repo):
    conv = {"source": "test", "external_id": "cycle", "messages": [{"id": "a", "role": "user", "content": "A", "parent_id": "b"}, {"id": "b", "role": "assistant", "content": "B", "parent_id": "a"}]}
    with pytest.raises(ValueError, match="cycle"):
        repo.import_conversations(parse_upload("x.json", json.dumps(conv).encode()))
    assert repo.list_conversations() == [] and repo.list_jobs() == []


def test_source_times_and_raw_non_text_survive_export(repo):
    conv = {"source": "test", "external_id": "raw", "created_at": 1700000000, "messages": [{"id": "m", "role": "user", "timestamp": "2026-10-14T08:00:00+08:00", "content": ["text", {"type": "image", "pointer": "synthetic://image"}]}]}
    repo.import_conversations(parse_upload("raw.json", json.dumps(conv).encode()))
    out = repo.export_data()["conversations"][0]
    assert out["created_at"].startswith("2023-11-14")
    assert out["messages"][0]["timestamp"] == "2026-10-14T00:00:00+00:00"
    assert out["raw"]["messages"][0]["content"][1]["pointer"] == "synthetic://image"


def test_edited_evidence_is_marked_stale_but_quote_version_remains(repo, sample_bytes):
    _, conv = imported(repo, sample_bytes)
    message = repo.get_conversation(conv["id"])["messages"][0]
    knowledge = repo.create_knowledge({"title": "K", "evidence": [{"message_id": message["id"], "quote": "中文学习"}]})
    data = json.loads(sample_bytes)
    data["messages"][0]["content"] = "Edited"
    repo.import_conversations(parse_upload("x.json", json.dumps(data).encode()))
    evidence = repo.get_knowledge(knowledge["id"])["evidence"][0]
    assert evidence["stale"] is True and evidence["message_version"] == 1
    assert repo.list_jobs()[-1]["payload"]["message_versions"][message["id"]] == 2


def test_missing_id_fingerprint_includes_non_text_source_content(repo):
    first = {"source": "note", "title": "Image", "messages": [{"role": "user", "content": [{"type": "image", "pointer": "synthetic://one"}]}]}
    second = {"source": "note", "title": "Image", "messages": [{"role": "user", "content": [{"type": "image", "pointer": "synthetic://two"}]}]}
    repo.import_conversations(parse_upload("a.json", json.dumps(first).encode()))
    assert repo.import_conversations(parse_upload("b.json", json.dumps(second).encode()))["imported"] == 1


def test_append_does_not_replay_an_intervening_message_edit(repo, monkeypatch):
    conv = repo.create_conversation({"title": "Manual", "messages": [{"id": "u1", "role": "user", "content": "old"}]})
    original_get = repo.get_conversation
    edited = False
    def interleaved_read(conversation_id, branch=None):
        nonlocal edited
        result = original_get(conversation_id, branch=branch)
        if not edited:
            edited = True
            repo.import_conversations(parse_upload("x.json", json.dumps({"source": "manual", "external_id": conv["external_id"],
                "title": "Manual", "messages": [{"id": "u1", "role": "user", "content": "edited"}]}).encode()))
        return result
    monkeypatch.setattr(repo, "get_conversation", interleaved_read)
    repo.append_messages(conv["id"], [{"id": "a1", "role": "assistant", "content": "next"}])
    assert original_get(conv["id"])["messages"][0]["content"] == "edited"


def test_export_reads_a_coherent_snapshot_during_an_external_edit(repo, sample_bytes, monkeypatch):
    _, conv = imported(repo, sample_bytes)
    other = Repository(repo.db.path)
    original_list = repo.list_conversations
    changed = False
    def interleaved_list(**filters):
        nonlocal changed
        result = original_list(**filters)
        if not changed:
            changed = True
            message = repo.get_conversation(conv["id"])["messages"][0]
            other.create_knowledge({"title": "Concurrent", "evidence": [{"message_id": message["id"], "quote": "中文学习"}]})
            data = json.loads(sample_bytes)
            data["messages"][0]["content"] = "changed"
            other.import_conversations(parse_upload("x.json", json.dumps(data).encode()))
        return result
    monkeypatch.setattr(repo, "list_conversations", interleaved_list)
    archive = repo.export_data()
    assert archive["conversations"][0]["revision"] == 1
    assert archive["knowledge"] == []
    assert len(archive["jobs"]) == 1


def test_chatgpt_empty_selected_node_is_preserved_without_fake_branch(repo):
    from test_importers import chatgpt
    data = chatgpt()
    data[0]["current_node"] = "root"
    repo.import_conversations(parse_upload("conversations.json", json.dumps(data).encode()))
    detail = repo.get_conversation(repo.list_conversations()[0]["id"])
    assert detail["current_node_external"] == "root" and detail["raw"]["current_node"] == "root"
    assert detail["current_node"] is None


def test_delayed_append_retry_after_restart_preserves_branch_raw_and_revision(repo):
    conv = repo.create_conversation({"title": "Manual"})
    user = {"id": "u1", "role": "user", "content": "Hi"}
    repo.append_messages(conv["id"], [user])
    before = repo.append_messages(conv["id"], [{"id": "a1", "role": "assistant", "content": "Reply"}])
    jobs = len(repo.list_jobs())
    restarted = Repository(repo.db.path)
    after = restarted.append_messages(conv["id"], [user])
    assert after == before
    assert len(restarted.list_jobs()) == jobs
    chosen = restarted.append_messages(conv["id"], [user], current_node="u1")
    assert chosen["current_node_external"] == "u1"
    assert chosen["current_node"] == chosen["messages"][0]["id"]


def test_unchanged_append_still_rejects_duplicate_message_ids(repo):
    conv = repo.create_conversation({"title": "Manual"})
    user = {"id": "u1", "role": "user", "content": "Hi"}
    before = repo.append_messages(conv["id"], [user])
    with pytest.raises(ValueError, match="Duplicate"):
        repo.append_messages(conv["id"], [user, user])
    assert repo.get_conversation(conv["id"])["revision"] == before["revision"]


def test_append_rejects_explicit_empty_current_node(repo):
    conv = repo.create_conversation({"title": "Manual"})
    user = {"id": "u1", "role": "user", "content": "Hi"}
    before = repo.append_messages(conv["id"], [user])
    with pytest.raises(ValueError, match="current_node"):
        repo.append_messages(conv["id"], [user], current_node="")
    assert repo.get_conversation(conv["id"])["revision"] == before["revision"]


def test_conversation_detail_is_one_snapshot_during_intervening_edit(repo, sample_bytes, monkeypatch):
    _, conv = imported(repo, sample_bytes)
    other = Repository(repo.db.path)
    converter = repo._conversation
    changed = False
    def interleaved_conversion(row):
        nonlocal changed
        result = converter(row)
        if not changed:
            changed = True
            data = json.loads(sample_bytes)
            data["messages"][0]["content"] = "changed"
            other.import_conversations(parse_upload("x.json", json.dumps(data).encode()))
        return result
    monkeypatch.setattr(repo, "_conversation", interleaved_conversion)
    detail = repo.get_conversation(conv["id"])
    assert detail["revision"] == detail["messages"][0]["version"] == 1
    assert "100%" in detail["messages"][0]["content"]
    assert len(detail["messages"][0]["versions"]) == len(detail["raw_versions"]) == 1
    assert other.get_conversation(conv["id"])["revision"] == 2


def test_headingless_markdown_identity_does_not_depend_on_filename(repo):
    payload = b"A synthetic headingless note."
    repo.import_conversations(parse_upload("note-one.md", payload))
    repeated = repo.import_conversations(parse_upload("note-two.md", payload))
    assert repeated["imported"] == 0 and repeated["duplicates"] == 1
    assert len(repo.list_conversations()) == len(repo.list_jobs()) == 1


def test_renamed_headingless_markdown_preserves_user_title_edit(repo):
    payload = b"A synthetic headingless note."
    first = repo.import_conversations(parse_upload("note-one.md", payload))
    before = repo.update_conversation(first["conversation_ids"][0], {"title": "Edited title"})
    repeated = repo.import_conversations(parse_upload("note-two.md", payload))
    assert repeated["imported"] == repeated["updated"] == 0 and repeated["duplicates"] == 1
    assert repo.get_conversation(before["id"])["title"] == "Edited title"
    assert repo.get_conversation(before["id"])["revision"] == before["revision"]
    assert len(repo.list_jobs()) == 1


def test_renamed_markdown_replay_after_append_preserves_title_and_raw_ancestry(repo):
    payload = b"A synthetic headingless note."
    first = repo.import_conversations(parse_upload("first.md", payload))
    conversation_id = first["conversation_ids"][0]
    original = repo.get_conversation(conversation_id)
    repo.update_conversation(conversation_id, {"title": "User title"})
    before = repo.append_messages(conversation_id, [{"id": "added", "role": "user", "content": "Appended text"}])
    assert before["raw"]["source_record"] == original["raw"]
    replay = repo.import_conversations(parse_upload("third.md", payload))
    after = repo.get_conversation(conversation_id)
    assert replay["imported"] == 0
    assert after["title"] == "User title"
    assert after["raw"] == original["raw"]
    assert after["raw_versions"][:len(before["raw_versions"])] == before["raw_versions"]
    assert len(after["messages"]) == 2


def test_storage_json_encoder_rejects_nonfinite_numbers():
    from recallnest.repository_entities import encode
    with pytest.raises(ValueError):
        encode({"nested": [float("inf")]})


def test_valid_older_evidence_version_is_preserved_after_edit(repo, sample_bytes):
    _, conv = imported(repo, sample_bytes)
    message = repo.get_conversation(conv["id"])["messages"][0]
    data = json.loads(sample_bytes)
    data["messages"][0]["content"] = "edited"
    repo.import_conversations(parse_upload("x.json", json.dumps(data).encode()))
    knowledge = repo.create_knowledge({"title": "K", "evidence": [{"message_id": message["id"], "message_version": 1, "quote": "100%"}]})
    assert knowledge["evidence"][0]["message_version"] == 1 and knowledge["evidence"][0]["stale"] is True
