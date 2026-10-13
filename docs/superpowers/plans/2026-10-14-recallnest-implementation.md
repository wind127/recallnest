# RecallNest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver and publish a usable local personal knowledge application covering history import, continuous capture, review, and evidence-backed user memory.

**Architecture:** A React/TypeScript web client talks to a FastAPI service backed by SQLite. Import adapters normalize conversations; durable jobs produce source-linked knowledge, review cards, and memory candidates through an optional configured model. CLI/MCP and a Codex watcher reuse the same service rather than implement another storage layer.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, httpx, SQLite, MCP Python SDK, pytest; Node 22+, React, TypeScript, Vite, Vitest, Playwright. Server default 127.0.0.1:8787; Vite proxies /api to it.

## Shared boundaries

Repository: `F:/Workspace/idea/recallnest`, branch `feat/initial-release`. Approved requirements: `docs/superpowers/specs/2026-10-14-recallnest-design.md`.

Python package: `src/recallnest/`; tests: `tests/`; frontend: `web/`; synthetic fixtures: `examples/`. Default persistent data lives in `~/.recallnest`, configurable through `RECALLNEST_DATA_DIR`. No private data is committed.

Module responsibilities: `config.py` connection settings; `db.py` schema and transactions; `importers.py` normalization; `repository.py` entity persistence; `models.py` validated contracts; `ai.py` provider calls and evidence validation; `jobs.py` durable processing; `search.py` text/vector retrieval; `app.py` application assembly with routers under `routes/`; `cli.py`, `capture.py`, `mcp_server.py` external integrations.

API list responses use `{ "items": [...] }`. Detail responses contain entity fields and relevant evidence. API failures use meaningful 4xx/5xx JSON details. The backend implementer must write `docs/api-contract.md` with exact final routes and response shapes before frontend work begins.

## Task 1: Persistent service, import and user-facing entities

**Create:** `pyproject.toml`, `src/recallnest/{__init__,config,db,models,repository,importers,app}.py`, `src/recallnest/routes/`, `tests/{conftest,test_importers,test_repository,test_api,test_memory_review}.py`, `examples/{conversations.json,codex-session.jsonl,notes.md}`, `docs/api-contract.md`.

- [x] Write behavior-first tests for ChatGPT branches, ZIP limits, Codex JSONL, generic JSON/Markdown, invalid files, repeat imports and edits. Include this contract:

```python
def test_repeat_import_is_idempotent(client, sample_bytes):
    first = client.post('/api/import', files={'file': ('history.json', sample_bytes, 'application/json')})
    second = client.post('/api/import', files={'file': ('history.json', sample_bytes, 'application/json')})
    assert first.status_code == second.status_code == 200
    assert second.json()['imported'] == 0
```

- [x] Run `uv run pytest tests/test_importers.py tests/test_repository.py -q`, recording the expected missing-behavior failures.
- [x] Implement normalization, transactional persistence, raw versions, branch display, stable identities and import preview. Bound upload bytes, ZIP expanded bytes and member counts. Do not extract ZIP members to disk.
- [x] Add tested endpoints for health/status, statistics, conversation creation/detail/append, knowledge creation/edit/detail/favorite, project creation/edit/links, memory CRUD/status/supersession, review create/edit/pause/grade, and JSON/Markdown export.
- [x] Test confirmed-only context with rejected/expired memories excluded and superseded history preserved. Test escaped Chinese substring search and grade scheduling with injected dates.
- [x] Run `uv run pytest -q`, inspect diff, commit only task files.
- [x] Spec review, fix missing behavior, then separate quality review, fix findings and re-run tests.

## Task 2: Model, durable jobs, retrieval and personalized chat

**Create/modify:** `src/recallnest/{ai,jobs,search}.py`, AI/settings/chat/job routers, `tests/{test_ai,test_jobs,test_chat,test_search}.py`, `docs/api-contract.md`.

- [x] Write tests for provider HTTP success/failure, invalid JSON, non-existing citations, assistant-derived user facts, unconfigured model, interrupted jobs, duplicate processing, message edits and stale evidence. Use an httpx transport as a provider boundary, not a substitute memory implementation.
- [x] Verify failing tests using `uv run pytest tests/test_ai.py tests/test_jobs.py tests/test_chat.py tests/test_search.py -q`.
- [x] Implement configurable OpenAI-compatible chat completion and embedding calls. Protect keys in settings/status/export/errors. Validate extraction schema, source quotes and source roles before storing derived items.
- [x] Implement durable queued/running/completed/failed jobs with recovery, bounded retries, visible errors, manual retry, per-conversation version and transactional result insertion. Start/stop worker through FastAPI lifespan. If no model exists, expose explicit configuration-required state.
- [x] Implement hybrid retrieval using text matching and persisted optional vectors, stable similarity ranking and bounded context. Personalized chat loads confirmed active memories and cited knowledge, saves both turns, reports used context, and queues consolidation.
- [x] Update exact API contract, run all backend tests, inspect diff and commit.
- [x] Spec review followed by quality review; fix and re-test before continuing.

## Task 3: Continuous capture, CLI and MCP

**Create:** `src/recallnest/{cli,capture,mcp_server}.py`, `tests/{test_capture,test_cli,test_mcp}.py`, `docs/integrations.md`.

- [x] Write a capture test that scans one synthetic file, appends a message, recreates the capture instance and proves replay imports only the new message. Test a partial trailing JSON line, malformed complete line, stale PID/status and paths outside the configured root.
- [x] Run `uv run pytest tests/test_capture.py tests/test_cli.py tests/test_mcp.py -q` to observe missing behavior.
- [x] Implement `recallnest serve`, `import`, `export`, `capture preview/start/stop/status`, and `mcp`. `serve` binds loopback by default and serves `web/dist` after building. Capture requires an explicit directory and keeps progress in the data directory, not the repository.
- [x] Expose MCP tools to search knowledge, fetch conversation/knowledge evidence, read active memory/context, submit a normalized conversation and create memory candidates. STDIO stays protocol-only; diagnostics go to stderr.
- [x] Verify the MCP server with a real SDK client over STDIO. Run capture lifecycle on the supported OS and all backend tests. Commit and perform sequential spec/quality reviews.

## Task 4: Accessible knowledge and review workbench

**Create:** `web/package.json`, `web/index.html`, `web/vite.config.ts`, TypeScript configs, `web/src/{main,App,api,types}.tsx/ts`, `web/src/components/`, `web/src/pages/`, `web/src/styles.css`, `web/src/*.test.tsx`, `web/e2e/`, `web/playwright.config.ts`.

- [x] Write failing interaction tests for import preview/confirm, memory confirmation/exclusion and review reveal/grade. Configure Vitest with a browser-like DOM and real component rendering.
- [x] Run `npm test -- --run` and inspect expected failures before implementing screens.
- [x] Build six working views: overview, knowledge library, conversations/chat, projects, review, memories, plus model settings and import modal. Follow `docs/api-contract.md` exactly; no hard-coded production data. Use calm pale blue/white, navy text and teal action color, system Chinese sans-serif typography, readable source rail, and subtle nest motif drawn as vector/CSS.
- [x] Implement text/date/type/source/tag/project filters, source-message navigation and branch selection, favorites, knowledge editing, project links/status, review editing/pause/date filters, memory editing/confirm/reject/expire/supersede, chat context display and export downloads.
- [x] Implement keyboard navigation, visible focus, responsive sidebar, loading/errors/empty states, and safe Markdown rendering. Show a clear model-not-configured state and keep basic features available.
- [x] Run `npm test -- --run`, `npm run build`, and Playwright on the real backend for import → inspect evidence → confirm memory → review card, plus empty/unconfigured and mobile viewport flows. Capture and inspect screenshots.
- [x] Commit, perform spec review and quality review, fix all important findings, repeat affected verification.

## Task 5: Open-source release and publication

**Create:** `README.md`, `README.en.md`, `LICENSE`, `.env.example`, `Dockerfile`, `compose.yaml`, `.dockerignore`, `.github/workflows/ci.yml`, `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/verification.md`.

- [x] Document exact install/build/run, import formats, model setup, continuous capture, MCP, memory lifecycle, review rules, local-only deployment and data export. Attribute researched design sources without claiming code reuse.
- [x] Build a multi-stage Docker image with frontend assets and Python service; bind Compose host publishing to 127.0.0.1. CI runs backend tests and frontend tests/build with locked dependencies.
- [x] Run `uv run pytest -q`, `npm test -- --run`, `npm run build`, real browser acceptance and a source/package secret/private-data audit. Record actual command outcomes and remaining platform limitations.
- [x] Final fresh independent code review; fix findings before release.
- [x] Commit and prepare public `main` with the verified source tree and GitHub noreply identity, create the authorized public `wind127/recallnest` repository, push source and verify remote default branch/commit and CI status. Retain private development history locally; do not publish local identity metadata, running data or credentials.

## Plan self-review

All four approved capabilities map to tasks. Import and core storage precede model consolidation; both precede integrations and UI. The API contract is finalized before UI implementation. Optional embeddings, editable review sets, project/state history, job recovery, secret isolation and release checks are explicitly included. No independent multi-tenant or browser-extension scope is added.
