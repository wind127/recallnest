"""Settings, jobs, search and chat HTTP contracts."""
from datetime import date
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from ..ai import AIError
from ..chat import ChatInput
from ..provider_settings import SettingsInput


router = APIRouter(prefix="/api")


@router.get("/settings")
def settings(request: Request):
    return request.app.state.connections.public()


@router.post("/settings")
def save_settings(body: SettingsInput, request: Request):
    result = request.app.state.connections.save(body.model_dump(exclude_unset=True))
    if result["model_configured"]:
        request.app.state.jobs.wake_configuration()
    return result


@router.post("/settings/test")
def test_settings(request: Request):
    ai = request.app.state.ai_factory()
    ai.chat([{"role": "user", "content": "Reply with OK."}])
    if not request.app.state.connections.mark_verified(ai.settings):
        raise AIError("configuration_changed", "Provider configuration changed during the test; test it again")
    return {"connection_verified": True, "model_configured": True}


@router.get("/jobs")
def jobs(request: Request, status: str | None = None):
    return {"items": request.app.state.jobs.list(status)}


@router.post("/jobs/{job_id}/run")
def run_job(job_id: str, request: Request):
    return request.app.state.jobs.run(job_id, force=True)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, request: Request):
    return request.app.state.jobs.retry(job_id)


@router.post("/jobs/run")
def run_next_job(request: Request):
    return {"job": request.app.state.jobs.run(force=True)}


@router.get("/search")
def search(request: Request, q: str = Query(min_length=1, max_length=2000), limit: int = Query(default=20, ge=1, le=50), semantic: bool = False,
           source: str | None = None, project_id: str | None = None, type: str | None = None, tag: str | None = None,
           entity_type: str | None = None, date_from: date | None = None, date_to: date | None = None):
    return request.app.state.search.search(q, limit=limit, semantic=semantic, source=source, project_id=project_id, type=type, tag=tag,
                                         entity_type=entity_type, date_from=date_from, date_to=date_to)


@router.post("/search/reindex")
def reindex(request: Request):
    return request.app.state.search.reindex()


@router.post("/chat")
def chat(body: ChatInput, request: Request):
    result, status = request.app.state.chat.send(body)
    return JSONResponse(result, status_code=status)
