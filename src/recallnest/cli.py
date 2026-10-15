"""Local CLI. MCP dispatch never prints non-protocol output on stdout."""
import argparse
import json
from pathlib import Path
import sys

from fastapi import HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from .app import create_app
from .capture import Capture, CaptureDaemon, atomic_json
from .config import get_settings
from .importers import ImportLimitExceeded, parse_upload
from .repository import Repository


def default_web_dir():
    # Source checkout location, independent of the caller's current directory.
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def build_app(data_dir=None, web_dir=None, *, allow_ai=True):
    app = create_app(data_dir=data_dir, start_worker=True, allow_ai=allow_ai)
    directory = Path(web_dir).expanduser().resolve() if web_dir is not None else default_web_dir()

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        if "\\" in path or any(part in (".", "..") for part in path.split("/")):
            raise HTTPException(404, "Not found")
        target = (directory / path).resolve()
        if not target.is_relative_to(directory):
            raise HTTPException(404, "Not found")
        if target.is_file():
            return FileResponse(target)
        if Path(path).suffix:
            raise HTTPException(404, "Not found")
        index = directory / "index.html"
        if index.is_file() and index.resolve().is_relative_to(directory):
            return FileResponse(index)
        return PlainTextResponse("Build the web UI with npm ci && npm run build in web/, or pass --web-dir to a built UI. The /api endpoints are available.", status_code=503)

    return app


def parser():
    root = argparse.ArgumentParser(prog="recallnest", description="Local evidence-backed knowledge archive")
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Serve REST, background jobs and the built web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8787, type=int)
    serve.add_argument("--web-dir", type=Path)
    serve.add_argument("--no-ai", action="store_true", help="Codex organizes; disable all model API calls and the provider worker")
    imported = commands.add_parser("import", help="Import JSON, Codex JSONL, Markdown or ChatGPT ZIP")
    imported.add_argument("file", type=Path)
    imported.add_argument("--source-identity")
    exported = commands.add_parser("export", help="Export the complete archive without provider settings")
    exported.add_argument("--format", choices=["json", "markdown"], default="json")
    exported.add_argument("--output", type=Path, help="Omit for stdout")
    capture = commands.add_parser("capture", help="Opt in to an explicit Codex JSONL directory")
    actions = capture.add_subparsers(dest="action", required=True)
    for name in ("preview", "start", "stop", "status"):
        action = actions.add_parser(name)
        action.add_argument("--data-dir", type=Path)
        if name in ("preview", "start"):
            action.add_argument("--root", required=True, type=Path)
            action.add_argument("--source-identity", help="Match the source namespace used for historical imports")
        if name == "start":
            action.add_argument("--interval", type=float, default=1.0)
    mcp = commands.add_parser("mcp", help="Run the MCP server using stdio only")
    mcp.add_argument("--local-only", action="store_true", help="Disable model API calls, including semantic search")
    worker = commands.add_parser("_capture-worker", help=argparse.SUPPRESS)
    worker.add_argument("--root", required=True, type=Path)
    worker.add_argument("--token", required=True)
    worker.add_argument("--interval", required=True, type=float)
    worker.add_argument("--source-identity")
    for command in (serve, imported, exported, mcp, worker):
        command.add_argument("--data-dir", type=Path)
    return root


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


def main(args=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    arguments = parser().parse_args(args)
    try:
        if arguments.command == "serve":
            if not 1 <= arguments.port <= 65535:
                raise ValueError("Port must be between 1 and 65535")
            import uvicorn
            uvicorn.run(build_app(arguments.data_dir, arguments.web_dir, allow_ai=not arguments.no_ai), host=arguments.host, port=arguments.port)
        elif arguments.command == "mcp":
            from .mcp_server import build_server
            build_server(arguments.data_dir, local_only=arguments.local_only).run(transport="stdio")
        elif arguments.command == "_capture-worker":
            CaptureDaemon(arguments.data_dir).run(arguments.root, arguments.token, arguments.interval, arguments.source_identity)
        elif arguments.command == "capture":
            if arguments.action == "preview":
                result = Capture(arguments.root, arguments.data_dir, source_identity=arguments.source_identity).preview()
            else:
                daemon = CaptureDaemon(arguments.data_dir)
                result = daemon.start(arguments.root, interval=arguments.interval, source_identity=arguments.source_identity) if arguments.action == "start" else getattr(daemon, arguments.action)()
            emit(result)
            return 1 if result.get("errors") else 0
        elif arguments.command == "import":
            settings = get_settings(arguments.data_dir)
            with arguments.file.open("rb") as stream:
                data = stream.read(settings.max_upload_bytes + 1)
            if len(data) > settings.max_upload_bytes:
                raise ImportLimitExceeded("File exceeds upload byte limit")
            conversations = parse_upload(arguments.file.name, data, source_identity=arguments.source_identity,
                                         max_upload_bytes=settings.max_upload_bytes, max_zip_bytes=settings.max_zip_bytes,
                                         max_zip_members=settings.max_zip_members)
            emit(Repository(settings.data_dir / "recallnest.sqlite3").import_conversations(conversations))
        elif arguments.command == "export":
            repo = Repository(get_settings(arguments.data_dir).data_dir / "recallnest.sqlite3")
            value = repo.export_data() if arguments.format == "json" else repo.export_markdown()
            if arguments.output:
                if arguments.format == "json":
                    atomic_json(arguments.output, value)
                else:
                    arguments.output.write_text(value, encoding="utf-8")
            elif arguments.format == "json":
                emit(value)
            else:
                print(value, end="")
        return 0
    except (ValueError, KeyError) as error:
        # Validation errors from adapters/services contain safe summaries, not raw payloads.
        print("recallnest: " + str(error.args[0]), file=sys.stderr)
        return 1
    except OSError:
        print("recallnest: Unable to access a file or start the service; check paths and permissions", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
