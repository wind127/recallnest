# RecallNest

[![CI](https://github.com/wind127/recallnest/actions/workflows/ci.yml/badge.svg)](https://github.com/wind127/recallnest/actions/workflows/ci.yml)

Keep your AI conversations as searchable knowledge, review material, project records, and personal memory with traceable sources.

[中文](README.md) · [Imports](docs/imports.md) · [Models](docs/models.md) · [CLI / MCP](docs/integrations.md) · [Deployment](docs/deployment.md) · [API contract](docs/api-contract.md)

RecallNest is a local, single-user application with a React workbench, FastAPI service, and SQLite archive. An optional OpenAI-compatible provider handles consolidation and chat. Import, text search, manual editing, and review also work without a model.

## What it does

- Imports ChatGPT JSON/ZIP exports, Codex JSONL, normalized JSON, and Markdown. Preserves branches, raw records, and message versions with stable-ID replay handling.
- Archives in-app chat, captures an explicitly configured Codex directory, and accepts submissions through REST/MCP.
- Provides knowledge search, source citations, project grouping, favorites, and scheduled review cards.
- Builds memory candidates for preferences, background, goals, state, and constraints. You confirm, edit, reject, expire, or supersede them before active confirmed memories inform future answers.

![Knowledge with source evidence](docs/images/knowledge.png)

Screenshots use synthetic conversations and fixed provider test responses. They show source citations and versions; see the [review and scheduling view](docs/images/review.png). They are not a benchmark of real model quality.

## Run locally

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/), Node.js 22.12+, and npm.

```sh
git clone https://github.com/wind127/recallnest.git
cd recallnest
uv sync --locked
cd web
npm ci
npm run build
cd ..
uv run recallnest serve
```

Open <http://127.0.0.1:8787>. Import your files or explicitly load the labeled synthetic demo. RecallNest does not scan your history directories on first launch.

For frontend development, run `npm run dev` inside `web/` alongside the API service. Vite proxies `/api` to the local backend.

### Installation prompt

```text
Install and start https://github.com/wind127/recallnest locally. Prefer Docker Compose; otherwise follow the README source installation. Preserve existing data, verify /api/health and the web UI, and report the URL. I'll configure the model in settings later.
```

## Models and storage

Configure a compatible base URL, chat model, and optional API key in the settings view. An optional embedding model enables semantic retrieval. `.env.example` lists supported environment variables; copying it does not load those values automatically.

A base URL normally ends in `/v1`, for example an adapted local provider at `http://127.0.0.1:11434/v1`. Consolidation requires the model to return the requested JSON structure. A remote provider receives processed conversation text and selected context.

Persistent data defaults to `~/.recallnest`, configurable with `RECALLNEST_DATA_DIR`. Provider keys remain server-side and are excluded from API responses and archive exports. Secrets you put in source conversation text remain part of that source archive.

## Continuous capture and integrations

Preview an explicit Codex log directory before starting the background watcher. Replace these example paths with your log and private data directories:

```sh
uv run --locked recallnest capture preview --root "/path/to/codex-logs" --data-dir "/path/to/private-data"
uv run --locked recallnest capture start --root "/path/to/codex-logs" --data-dir "/path/to/private-data"
uv run --locked recallnest capture status --data-dir "/path/to/private-data"
uv run --locked recallnest capture stop --data-dir "/path/to/private-data"
```

Capture preserves raw records and versions, deduplicates replayed messages, and retries temporarily unreadable or changing files. Automatic model consolidation requires `recallnest serve` to run with the same data directory and a configured provider.

The stdio MCP server exposes `search`, `fetch`, `context`, `submit`, and `remember`. Context includes only active confirmed memories; new memories submitted through the tool remain candidates. The [integration guide](docs/integrations.md) includes generic host configuration and optional Codex CLI registration.

Offline import and export are also available:

```sh
uv run --locked recallnest import examples/conversations.json
uv run --locked recallnest export --output recallnest-export.json
uv run --locked recallnest export --format markdown --output recallnest-export.md
```

## Scope

ChatGPT is supported through exports and explicit submissions; automatic web capture and browser extensions are future work. Memory retrieval supplies context rather than training model weights. Questions and assistant guesses do not establish user facts. Referenced media is archived as raw metadata without fetching or interpreting its pixels/audio.

Full JSON export preserves source versions, citations, and entity history; Markdown export is a readable text view. This release has no full archive restore endpoint, so back up the data directory for migration. The service binds loopback by default and has no public multi-user authentication.

## Development

```sh
uv run pytest -q
cd web
npm test -- --run
npm run build
```

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Verification](docs/verification.md) · [MIT license](LICENSE)

Product ideas were informed by Mem0, Khoj, Basic Memory, and Open WebUI. RecallNest is an independent implementation; see [design references](docs/design-references.md).
