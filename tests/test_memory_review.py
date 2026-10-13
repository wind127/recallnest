from datetime import datetime, timezone, timedelta
import pytest


def test_memory_lifecycle_and_manual_source(repo):
    old = repo.create_memory({"content": "Studying", "category": "state", "subject": "learning"})
    assert old["status"] == "candidate" and old["source"] == "manual" and old["evidence"] == []
    assert repo.active_memories() == []
    repo.update_memory(old["id"], {"status": "confirmed"})
    assert len(repo.active_memories()) == 1
    new = repo.create_memory({"content": "Graduated", "category": "state", "subject": "learning", "status": "confirmed", "supersedes": old["id"]})
    assert repo.get_memory(old["id"])["status"] == "superseded"
    assert [m["id"] for m in repo.active_memories()] == [new["id"]]
    assert len(repo.list_memories()) == 2
    repo.update_memory(new["id"], {"status": "expired"})
    assert repo.active_memories() == []
    rejected = repo.create_memory({"content": "No", "category": "preference"})
    repo.update_memory(rejected["id"], {"status": "rejected"})
    assert repo.active_memories() == []


def test_expiration_date_excludes_confirmed_memory(repo):
    repo.create_memory({"content": "Old", "category": "state", "status": "confirmed", "expires_at": "2000-01-01T00:00:00Z"})
    assert repo.active_memories() == []


def test_supersession_requires_matching_subject_and_preserves_history(repo):
    old = repo.create_memory({"content": "Old", "category": "state", "subject": "work", "status": "confirmed"})
    with pytest.raises(ValueError, match="subject"):
        repo.create_memory({"content": "New", "category": "state", "subject": "other", "supersedes": old["id"]})
    assert repo.get_memory(old["id"])["status"] == "confirmed"
    assert len(repo.list_memories()) == 1


@pytest.mark.parametrize("grade,minutes", [("again", 10), ("hard", 1440), ("good", 4320), ("easy", 10080)])
def test_review_grade_scheduling_with_clock(repo, grade, minutes):
    now = datetime(2026, 10, 14, tzinfo=timezone.utc)
    card = repo.create_review({"question": "Q", "answer": "A", "due_at": now.isoformat()}, now=now)
    assert len(repo.list_reviews(due=True, now=now)) == 1
    updated = repo.grade_review(card["id"], grade, now=now)
    assert datetime.fromisoformat(updated["due_at"]) == now + timedelta(minutes=minutes)
    assert updated["grade_history"][0]["grade"] == grade
    assert repo.list_reviews(due=True, now=now) == []


def test_paused_review_and_project_date_sets(repo):
    project = repo.create_project({"name": "Learning"})
    card = repo.create_review({"question": "Q", "answer": "A", "project_id": project["id"], "due_at": "2026-10-14T00:00:00Z"})
    assert len(repo.list_reviews(project_id=project["id"], date_from="2026-10-14", date_to="2026-10-14")) == 1
    repo.update_review(card["id"], {"question": "Edited", "paused": True})
    assert repo.list_reviews(due=True) == []
    assert repo.get_review(card["id"])["question"] == "Edited"
    with pytest.raises(ValueError, match="paused"):
        repo.grade_review(card["id"], "good")


def test_future_confirmed_supersession_is_rejected_without_gap(repo):
    old = repo.create_memory({"content": "Current", "category": "state", "subject": "work", "status": "confirmed"})
    with pytest.raises(ValueError, match="future"):
        repo.create_memory({"content": "Future", "category": "state", "subject": "work", "status": "confirmed",
                            "supersedes": old["id"], "effective_at": "2100-01-01T00:00:00Z"})
    assert repo.get_memory(old["id"])["status"] == "confirmed"
    assert [m["id"] for m in repo.active_memories()] == [old["id"]]


def test_candidate_supersession_waits_for_confirmation(repo):
    old = repo.create_memory({"content": "Current", "category": "state", "subject": "work", "status": "confirmed"})
    new = repo.create_memory({"content": "New", "category": "state", "subject": "work", "supersedes": old["id"]})
    assert [m["id"] for m in repo.active_memories()] == [old["id"]]
    repo.update_memory(new["id"], {"status": "confirmed"})
    assert repo.get_memory(old["id"])["status"] == "superseded"
