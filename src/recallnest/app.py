"""ASGI application; storage is initialized lazily on the first repository read."""
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from . import __version__
from .config import get_settings
from .importers import ImportFailure, ImportLimitExceeded
from .repository import Repository
from .routes import conversations, entities, imports, ai_routes
from .ai import AIClient, AIError
from .provider_settings import ConnectionSettings
from .jobs import JobService
from .search import SearchService
from .chat import ChatService


class BodyTooLarge(HTTPException):
    def __init__(self):
        super().__init__(status_code=413, detail="Request exceeds byte limit")


class LocalBoundaryMiddleware:
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("latin1")
        try:
            hostname = urlsplit("http://" + host).hostname
            origin = headers.get(b"origin", b"").decode("latin1")
            parsed_origin = urlsplit(origin) if origin else None
        except ValueError:
            return await JSONResponse({"detail": "Invalid request host or origin"}, 400)(scope, receive, send)
        if hostname not in ("localhost", "127.0.0.1", "::1"):
            return await JSONResponse({"detail": "Untrusted request host"}, 400)(scope, receive, send)
        if parsed_origin and (parsed_origin.scheme not in ("http", "https") or parsed_origin.hostname not in ("localhost", "127.0.0.1", "::1")):
            return await JSONResponse({"detail": "Only loopback browser origins are allowed"}, 403)(scope, receive, send)
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > self.max_bytes:
            return await JSONResponse({"detail": "Request exceeds byte limit"}, 413)(scope, receive, send)
        length = 0
        async def bounded_receive():
            nonlocal length
            event = await receive()
            length += len(event.get("body", b""))
            if length > self.max_bytes:
                raise BodyTooLarge()
            return event
        try:
            await self.app(scope, bounded_receive, send)
        except BodyTooLarge:
            await JSONResponse({"detail": "Request exceeds byte limit"}, 413)(scope, receive, send)


def create_app(data_dir=None, start_worker=False, *, settings=None):
    explicit_settings = settings is not None
    settings = settings or get_settings(data_dir)
    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            app.state.jobs.start()
            app.state.worker_running = True
        try:
            yield
        finally:
            if start_worker:
                app.state.jobs.stop()
                app.state.worker_running = False
    app = FastAPI(title="RecallNest", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.connections = ConnectionSettings(settings, load_saved=not explicit_settings)
    app.state.repository = Repository(settings.data_dir / "recallnest.sqlite3")
    app.state.ai_factory = lambda: AIClient(app.state.connections.current(), getattr(app.state, "provider_transport", None))
    app.state.jobs = JobService(app.state.repository, app.state.ai_factory)
    app.state.search = SearchService(app.state.repository, app.state.ai_factory)
    app.state.chat = ChatService(app.state.repository, app.state.ai_factory, app.state.search)
    app.state.worker_running = False
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?", allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Content-Type"])
    app.add_middleware(LocalBoundaryMiddleware, max_bytes=settings.max_upload_bytes + 65536)

    @app.exception_handler(KeyError)
    async def missing_handler(request, exception):
        return JSONResponse({"detail": str(exception.args[0])}, status_code=404)

    @app.exception_handler(ImportFailure)
    async def import_handler(request, exception):
        return JSONResponse({"detail": str(exception)}, status_code=400)

    @app.exception_handler(ImportLimitExceeded)
    async def import_limit_handler(request, exception):
        return JSONResponse({"detail": str(exception)}, status_code=413)

    @app.exception_handler(ValueError)
    async def value_handler(request, exception):
        return JSONResponse({"detail": str(exception)}, status_code=422)

    @app.exception_handler(AIError)
    async def ai_handler(request, exception):
        status = 413 if exception.kind == "request_too_large" else 409 if exception.kind in ("configuration_required", "configuration_changed") else 502
        return JSONResponse({"error_kind": exception.kind, "detail": exception.message}, status_code=status)

    async def validation_handler(request, exception):
        return JSONResponse({"detail": [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exception.errors()]}, status_code=422)
    app.add_exception_handler(ValidationError, validation_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    def status():
        return {"status": "ready", "version": __version__, "database": "sqlite", "model_configured": app.state.connections.current().model_configured,
                "worker_running": app.state.worker_running, "limits": {"upload_bytes": settings.max_upload_bytes,
                "zip_expanded_bytes": settings.max_zip_bytes, "zip_members": settings.max_zip_members}}

    @app.get("/api/stats")
    def stats():
        return app.state.repository.stats()

    @app.get("/api/export")
    def export(format: str = "json"):
        if format == "json":
            return JSONResponse(app.state.repository.export_data(), headers={"Content-Disposition": 'attachment; filename="recallnest-export.json"'})
        if format == "markdown":
            return PlainTextResponse(app.state.repository.export_markdown(), media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="recallnest-export.md"'})
        raise ValueError("Export format must be json or markdown")

    @app.post("/api/demo")
    def demo():
        from .demo import seed_demo
        return seed_demo(app.state.repository)

    app.include_router(conversations.router)
    app.include_router(entities.router)
    app.include_router(imports.router)
    app.include_router(ai_routes.router)
    return app


_default_app = None


async def app(scope, receive, send):
    """Lazy conventional ASGI entrypoint; importing code never reads user settings."""
    global _default_app
    if _default_app is None:
        _default_app = create_app(start_worker=True)
    await _default_app(scope, receive, send)
