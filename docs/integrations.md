# CLI, continuous capture and MCP

Install with `uv sync --locked`; all commands below run from the RecallNest checkout. An installed package also exposes the `recallnest` executable. Python 3.10 or newer is supported. The official MCP Python SDK is pinned to 2.3.0 and its real stdio client is tested with both automatic negotiation and the legacy initialization handshake.

## Local service

For the recommended **Codex organizes / RecallNest stores** workflow, follow [codex.md](codex.md). `serve --no-ai` provides the viewing/review UI without any direct model calls; `mcp --local-only` runs archive tools and host-generated consolidation without a provider. These options work even if provider settings were saved previously.

```powershell
uv run --locked recallnest serve
uv run --locked recallnest serve --data-dir "D:\RecallNest Private" --port 8787
uv run --locked recallnest serve --host 0.0.0.0 --port 8787 --web-dir "/app/web/dist"
```

The default bind is `127.0.0.1:8787`. The last command is for containers; REST and UI requests still enforce the loopback Host/Origin boundary. Publish container ports to loopback and use `localhost` or `127.0.0.1` in the browser. See [deployment.md](deployment.md).

`serve` loads saved provider settings and runs the durable job worker. UI connection changes survive a CLI restart. It serves `web/dist` relative to the source checkout, independent of the shell's current directory; `--web-dir` selects another built directory. Build with `npm ci` and `npm run build` inside `web/`. Without a build, the UI responds with HTTP 503 and build instructions while `/api` remains available. Installed wheels require an explicit built UI directory. Existing assets are served safely, browser routes fall back to `index.html`, and unknown `/api` routes and missing assets remain 404.

The default private directory is `~/.recallnest`; `RECALLNEST_DATA_DIR` or each command's `--data-dir` selects another directory. Importing Python modules does not inspect default provider configuration. Configuration is loaded when a service is explicitly created or the conventional `recallnest.app:app` ASGI entrypoint receives its first request/lifespan event.

## Import and export

```powershell
uv run --locked recallnest import "D:\Synthetic Exports\conversations.json" --data-dir "D:\RecallNest Private"
uv run --locked recallnest import "D:\Synthetic Exports\session.jsonl" --source-identity "my-codex-account"
uv run --locked recallnest export --data-dir "D:\RecallNest Private" --output "D:\Backups\recallnest.json"
uv run --locked recallnest export --format markdown --output "D:\Backups\recallnest.md"
```

Import uses the same adapters, graph validation, deduplication, archival transactions and limits as REST: JSON, Codex JSONL, Markdown and ChatGPT ZIP; 32 MiB upload, 128 MiB expanded ZIP and 1000 members by default. `RECALLNEST_MAX_UPLOAD_BYTES`, `RECALLNEST_MAX_ZIP_BYTES` and `RECALLNEST_MAX_ZIP_MEMBERS` configure those limits. Oversized files fail explicitly before unlimited reads. JSON import results are printed on stdout. Errors use stderr and a nonzero exit status.

Export defaults to JSON on stdout. `--format markdown` produces readable UTF-8 text. JSON preserves every branch, source record and version, derived entities and evidence in one database snapshot. Provider connection settings and API keys are excluded. Source content is exported exactly, including anything a user put in a conversation. See [api-contract.md](api-contract.md#export) for restoration limits.

## Explicit continuous Codex capture

Preview only the directory you intend to grant access to:

```powershell
uv run --locked recallnest capture preview --root "D:\Synthetic Codex Logs" --data-dir "D:\RecallNest Private"
uv run --locked recallnest capture start --root "D:\Synthetic Codex Logs" --data-dir "D:\RecallNest Private"
uv run --locked recallnest capture status --data-dir "D:\RecallNest Private"
uv run --locked recallnest capture stop --data-dir "D:\RecallNest Private"
uv run --locked recallnest capture start --root "D:\Synthetic Codex Logs" --source-identity "my-codex-account" --data-dir "D:\RecallNest Private"
```

`--root` is mandatory for preview/start and must be an existing explicit directory. RecallNest never defaults to a Codex history folder. Preview parses eligible recursive `.jsonl` files without writing the database, progress or process state. It reports relative paths, message counts, pending trailing bytes and safe parse errors. The test/demo fixtures are synthetic; setup never imports personal history automatically.

Start creates a background process with no visible window on Windows. `--interval 1` sets the poll interval in seconds (0.05–3600). There is one daemon per private data directory. OS locks prevent two starts; PID, process creation time, exact worker command and a unique token verify ownership. Stop requests cooperative completion and waits for the verified worker to exit. A timeout reports that stopping is still in progress. Unrelated/recycled PIDs are never signaled or killed; Windows does not use `os.kill(pid, 0)` for liveness. A stale state is recoverable by the next start. Status includes a heartbeat and the last scan, including file failures. Diagnostics are stored in `<data-dir>/capture/daemon.log`.

Capture defaults to the same `codex` source identity as ordinary REST/CLI Codex imports: importing history and then enabling capture reuses those conversations. If history used `--source-identity "my-codex-account"`, pass that same option to capture preview/start. This also separates deliberately distinct account archives. Progress files are scoped by the resolved root and chosen source identity; the root hash is not a logical source identity.

The scanner skips unchanged files by size, modification time and file identity. It checks those attributes on the opened file before and after reading and against the current path. A file that changes during the read reports a retry error without importing that read or advancing its checkpoint; the next stable scan replays the current content. Changed files are replayed through the existing Codex adapter, retaining stable message IDs and event/response pair deduplication. Only new messages/changed versions are imported; replay preserves full unsupported/tool records and source-version archives. Replay is bounded by the upload byte limit, with an explicit oversized-file error. This first release reparses each changed file rather than introducing a second streaming parser.

Missing or inaccessible directories and unreadable entries appear as safe relative-path errors in preview/scan results and the daemon's `last_scan`. The scan continues with already discovered files and unaffected subtrees. The daemon keeps polling, so a temporarily missing root or child directory can be captured after it recovers.

Partial trailing JSON or split UTF-8 bytes remain pending until completed; a valid final JSON record is imported even without a newline. A malformed newline-terminated record reports its line number, leaves the file checkpoint unchanged and is retried on the next scan. Truncation/rewrite also replays; prior messages and source versions remain archived. Symbolic links and Windows junction/reparse entries are skipped, and resolved paths must stay within the configured root. Checkpoints are atomically replaced in the private data directory after the archive transaction commits. A crash between those writes safely replays through deduplication.

Capture and MCP archive sources and enqueue consolidation jobs. In Codex mode, use the skill to organize them through the two handoff tools below; the web service is optional for consolidation. For standalone provider consolidation only, keep `recallnest serve` running with a configured provider. Do not run both organizers concurrently.

## MCP: stdio only

The server exposes seven tools using the official SDK:

| Tool | Inputs | Result |
| --- | --- | --- |
| `search` | `query`, `limit=20` (1–50), `semantic=false` | Bounded archive search hits and evidence; local text search by default. Semantic search explicitly requests the configured embedding provider. |
| `fetch` | `kind`: conversation/knowledge/message/memory, internal `source_id`, optional positive `version`, `offset=0`, `limit=4000` (1–8000 characters) | Paged full source text with source ID, version, offset, requested limit, total length, next offset, stale status and bounded evidence. |
| `context` | `offset=0`, `limit=20` (1–50 memories) | Only active confirmed memories with current proof, total and next offset. Long content is marked `content_truncated`; retrieve it through `fetch(kind="memory")`. |
| `submit` | `conversation` in the strict REST normalized conversation shape | Transactional import counts and internal conversation IDs in the shared archive. |
| `remember` | `memory` in the strict REST memory shape | A validated memory **candidate**, internal ID and bounded proof. Requested confirmed/rejected/etc. status is overridden to candidate. Human confirmation remains in RecallNest. |
| `prepare_consolidation` | Optional internal `conversation_id`; omit for the authorized backlog | `idle`, or a persisted `ready` batch with `batch_id`, conversation revision and one lossless message slice: ID, role, version, parent ID, offset/total and bounded branch metadata. No model call. |
| `complete_consolidation` | `batch_id`, `output` matching the exposed `Extraction` schema (`knowledge`, `memories`, `reviews`) | Atomically validates and stores host-generated results, returning counts. Exact citations must match the prepared chunk/version. Memories are candidates. Empty arrays explicitly acknowledge a read chunk with no reusable output. Completed-batch retries return `replayed=true`; changed sources must prepare again. |

Codex uses its own reasoning to produce the handoff output. A batch is capped at 18,000 escaped JSON bytes and 3,500 source characters; outputs are capped at 512,000 escaped bytes plus the extraction schema's item/field limits. The SQLite checkpoint advances only with a valid atomic write. All nonempty message versions across all branches are traversed; new/edited versions re-enter the backlog. Demo/synthetic-marked sources are excluded. A running provider job blocks Codex handoff. Derived entities use the existing `extracted` source and evidence/history contracts; completed jobs show disposition `codex`. The progress/batch bookkeeping lives in the data directory, not the full archive export; back up the complete stopped data directory to retain it.

Source/tool data is marked `untrusted_source=true`; it is evidence to inspect, never instructions to execute. System/developer/tool records remain source material. Import and memory validation reuse the existing Pydantic/repository contracts; unknown fields, invalid roles and invalid quotes fail without writing. There is no HTTP MCP listener. Stdout contains only SDK protocol messages; diagnostics go to stderr.

Source text uses character offsets, including NUL and four-byte Unicode characters. Preserve the returned version for subsequent pages and follow `next_offset` until null; the actual returned length can be smaller than the requested limit to bound the complete serialized result. Message pages recover exact current or historical text. Conversation pages recover the ordered transcript at a stored revision using its durable message-version snapshot. Knowledge pages contain title, summary and body; memory pages contain the full memory content. Knowledge/memory versions are 1-based creation/update history indexes. Their stale evidence remains available as archive proof and is excluded from active personal context. The raw source archive, full proof collections and entity history remain available through JSON export/REST detail.

MCP projections bound titles, source labels, subjects, content previews and evidence quotes (five proofs, up to 250 characters each, with `quote_truncated`). Shortened titles, source labels, subjects and memory content carry their corresponding `*_truncated` flags; search excerpts are previews. Current/previous message text can recover the complete quoted source. Tool result JSON is capped at 24,000 escaped bytes before the SDK wraps it in text/structured protocol content. Search/context pages expose `truncated` when the byte budget removes a trailing suffix or shortens a preview. A nonempty page always retains its first item's internal ID and proof references, shortening preview fields further if needed; that item carries `projection_truncated` and flags for the shortened fields. Context advances by returned items, so every remaining active memory can be reached by following `next_offset`. Use the returned ID with `fetch` and follow its versioned text pages to recover complete content. Raw source metadata and huge external IDs are not copied into read results.

Run manually only when a host is connected to its stdin/stdout:

```powershell
uv run --locked recallnest mcp --data-dir "D:\RecallNest Private"
```

Generic host configuration, with properly escaped Windows paths:

```json
{
  "mcpServers": {
    "recallnest": {
      "command": "uv",
      "args": ["--directory", "D:\\Projects\\recallnest", "run", "--locked", "recallnest", "mcp", "--data-dir", "D:\\RecallNest Private"]
    }
  }
}
```

Optional Codex CLI registration (this changes the host's configuration only when you execute it):

```powershell
codex mcp add recallnest -- uv --directory "D:\Projects\recallnest" run --locked recallnest mcp --data-dir "D:\RecallNest Private"
```

Example normalized submission:

```json
{"conversation":{"source":"synthetic-integration","external_id":"example-1","title":"Synthetic learning","messages":[{"id":"u1","role":"user","content":"A synthetic note about SQLite"}]}}
```

Use an internal `message_id` and its positive `message_version` returned by source retrieval when submitting memory evidence; external importer message IDs are not citation IDs. Quotes must occur exactly in that stored message version. See [api-contract.md](api-contract.md) for the normalized conversation, memory and evidence schemas.
