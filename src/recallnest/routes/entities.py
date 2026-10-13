from fastapi import APIRouter, Depends, Response
from ..models import (KnowledgeInput, KnowledgePatch, FavoriteInput, ProjectInput, ProjectPatch,
                      MemoryInput, MemoryPatch, ReviewInput, ReviewPatch, GradeInput)
from .common import repository, filters

router = APIRouter(prefix="/api")


@router.get("/knowledge")
def knowledge_list(repo=Depends(repository), query=Depends(filters)):
    return {"items": repo.list_knowledge(**query)}


@router.post("/knowledge", status_code=201)
def knowledge_create(body: KnowledgeInput, repo=Depends(repository)):
    return repo.create_knowledge(body.model_dump())


@router.get("/knowledge/{entity_id}")
def knowledge_get(entity_id: str, repo=Depends(repository)):
    return repo.get_knowledge(entity_id)


@router.patch("/knowledge/{entity_id}")
def knowledge_edit(entity_id: str, body: KnowledgePatch, repo=Depends(repository)):
    return repo.update_knowledge(entity_id, body.model_dump(exclude_unset=True))


@router.post("/knowledge/{entity_id}/favorite")
def knowledge_favorite(entity_id: str, body: FavoriteInput, repo=Depends(repository)):
    return repo.update_knowledge(entity_id, body.model_dump())


@router.delete("/knowledge/{entity_id}", status_code=204)
def knowledge_delete(entity_id: str, repo=Depends(repository)):
    repo.delete_knowledge(entity_id)
    return Response(status_code=204)


@router.get("/projects")
def project_list(q: str | None = None, status: str | None = None, repo=Depends(repository)):
    return {"items": repo.list_projects(q=q, status=status)}


@router.post("/projects", status_code=201)
def project_create(body: ProjectInput, repo=Depends(repository)):
    return repo.create_project(body.model_dump())


@router.get("/projects/{entity_id}")
def project_get(entity_id: str, repo=Depends(repository)):
    return repo.get_project(entity_id)


@router.patch("/projects/{entity_id}")
def project_edit(entity_id: str, body: ProjectPatch, repo=Depends(repository)):
    return repo.update_project(entity_id, body.model_dump(exclude_unset=True))


@router.get("/projects/{entity_id}/links")
def project_links(entity_id: str, repo=Depends(repository)):
    return repo.project_links(entity_id)


@router.delete("/projects/{entity_id}", status_code=204)
def project_delete(entity_id: str, repo=Depends(repository)):
    repo.delete_project(entity_id)
    return Response(status_code=204)


@router.get("/memories/context")
def memory_context(repo=Depends(repository)):
    return {"items": repo.active_memories()}


@router.get("/memories")
def memory_list(q: str | None = None, status: str | None = None, category: str | None = None, repo=Depends(repository)):
    return {"items": repo.list_memories(q=q, status=status, category=category)}


@router.post("/memories", status_code=201)
def memory_create(body: MemoryInput, repo=Depends(repository)):
    return repo.create_memory(body.model_dump())


@router.get("/memories/{entity_id}")
def memory_get(entity_id: str, repo=Depends(repository)):
    return repo.get_memory(entity_id)


@router.patch("/memories/{entity_id}")
def memory_edit(entity_id: str, body: MemoryPatch, repo=Depends(repository)):
    return repo.update_memory(entity_id, body.model_dump(exclude_unset=True))


@router.delete("/memories/{entity_id}", status_code=204)
def memory_delete(entity_id: str, repo=Depends(repository)):
    repo.delete_memory(entity_id)
    return Response(status_code=204)


@router.get("/reviews")
def review_list(due: bool = False, paused: bool | None = None, repo=Depends(repository), query=Depends(filters)):
    return {"items": repo.list_reviews(due=due, paused=paused, **query)}


@router.post("/reviews", status_code=201)
def review_create(body: ReviewInput, repo=Depends(repository)):
    return repo.create_review(body.model_dump(exclude_unset=True))


@router.get("/reviews/{entity_id}")
def review_get(entity_id: str, repo=Depends(repository)):
    return repo.get_review(entity_id)


@router.patch("/reviews/{entity_id}")
def review_edit(entity_id: str, body: ReviewPatch, repo=Depends(repository)):
    return repo.update_review(entity_id, body.model_dump(exclude_unset=True))


@router.post("/reviews/{entity_id}/grade")
def review_grade(entity_id: str, body: GradeInput, repo=Depends(repository)):
    return repo.grade_review(entity_id, body.grade)


@router.delete("/reviews/{entity_id}", status_code=204)
def review_delete(entity_id: str, repo=Depends(repository)):
    repo.delete_review(entity_id)
    return Response(status_code=204)
