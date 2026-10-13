# RecallNest API contract

Implemented version: 0.1.0. JSON archive schema: 1. Default base URL: http://127.0.0.1:8787/api. This contract covers the archive, manual entities, provider settings, consolidation worker, search and personalized chat. See [integrations.md](integrations.md) for the CLI, continuous capture lifecycle and five stdio MCP tools, which share these validation and archival services.

All lists return {"items":[...]}. IDs are opaque strings. Source external IDs differ from internal database IDs. Output dates use ISO 8601 UTC (+00:00). Valid ISO/epoch source dates are normalized; epoch numbers mean seconds, dates without an offset mean UTC. Unknown message timestamps remain null. Missing conversation dates use ingestion time. Text and Markdown are untrusted: clients must escape HTML and sanitize Markdown rendering.

Success: GET/PATCH/actions/import 200; entity creation 201; DELETE 204 with no body. Missing IDs: 404 {"detail":"..."}. Unsupported/malformed imports: 400. Invalid evidence/branches/relationships: 422 with string detail. Pydantic failures: 422 {"detail":[{"loc":[...],"msg":"...","type":"..."}]}, omitting input values and tracebacks. Create/PATCH reject unknown fields. PATCH validates the resulting full entity; omitted fields stay unchanged, explicit nulls are validated.

HTTP Host and browser Origin must be loopback (localhost, 127.0.0.1, [::1]). Untrusted Host gets 400; Origin gets 403. CORS permits HTTP/HTTPS loopback origins and optional ports, GET/POST/PATCH/DELETE/OPTIONS and Content-Type. Requests without Origin work for local CLI/MCP. This local single-user service has no public deployment authentication.

## Service state and configuration

| Method/path | Response |
| --- | --- |
| GET /health | {"status":"ok","version":"0.1.0"} |
| GET /status | Shape below; never returns keys/provider URLs. |
| GET /stats | Shape below. |
| GET /jobs?status=queued | Durable job list; optional queued/running/completed/failed filter. |

~~~json
{
  "status":"ready","version":"0.1.0","database":"sqlite",
  "model_configured":false,"worker_running":false,
  "limits":{"upload_bytes":33554432,"zip_expanded_bytes":134217728,"zip_members":1000}
}
~~~

~~~json
{
  "conversations":0,"messages":0,"knowledge":0,"projects":0,
  "memories":0,"reviews":0,"jobs":0,"confirmed_memories":0,"due_reviews":0
}
~~~

model_configured means a base URL and chat model are present, not that a connection was verified. Python factory: create_app(data_dir=..., start_worker=False, settings=...). The explicit factory eagerly loads saved provider configuration from the selected data directory; passing explicit settings bypasses saved configuration for isolated tests. Normal CLI serve calls create_app(data_dir=..., start_worker=True), so UI connection settings survive restart. start_worker=True starts/stops a background thread within the FastAPI lifespan. The conventional recallnest.app:app ASGI entrypoint constructs this worker-enabled app lazily on its first ASGI request/lifespan event. Importing modules reads no default private configuration and creates no directory; the first repository read/write initializes SQLite.

Data directory: RECALLNEST_DATA_DIR, default ~/.recallnest; database recallnest.sqlite3. Server-side connection environment: RECALLNEST_BASE_URL, RECALLNEST_API_KEY, RECALLNEST_CHAT_MODEL, RECALLNEST_EMBEDDING_MODEL. Providers use OpenAI-compatible POST {base_url}/chat/completions and optional /embeddings. Include the provider's API path (often /v1) in base_url.

### Provider settings

GET /settings returns exactly:

~~~json
{"base_url":"https://provider.example/v1","chat_model":"model-name","embedding_model":"", "has_api_key":true,"model_configured":true,"connection_verified":false,"storage":"server_file"}
~~~

POST /settings accepts a subset of {"base_url":"...","chat_model":"...","embedding_model":"...","api_key":"..."}; every field is a string. Omitted fields preserve their value; api_key="" explicitly clears the key; a nonempty api_key replaces it; null and unknown fields fail 422. Empty model/base URL strings clear those fields. URL must be complete HTTP(S) without embedded credentials, query, fragment, whitespace, C0/DEL controls or invalid port. URL control validation applies equally to REST, direct Settings and environment configuration; rejected saves make no configuration/file changes. Invalid URL errors omit the supplied value. Limits: URL 2048, key 4096, model 200 characters; control characters fail validation. Success returns the GET shape. Saving resets connection_verified and wakes configuration_required jobs when the chat connection fields are present.

Settings persist in provider-settings.json inside the data directory. This file contains the key, has best-effort owner-only file permissions, and is not encrypted. It is excluded from archive exports. On ordinary startup, explicitly set environment connection fields override saved fields; explicit Python Settings bypass the saved file. POST changes the running connection and file; an environment override applies again on next startup.

POST /settings/test has no body and makes one short chat request. Success: 200 {"connection_verified":true,"model_configured":true}. Verification applies only to the exact running configuration tested, is reset on changes/restart, and tests chat rather than embeddings. A concurrent settings change returns 409 {"error_kind":"configuration_changed","detail":"Provider configuration changed during the test; test it again"}. Missing configuration: 409 {"error_kind":"configuration_required","detail":"..."}; provider failures: 502 {"error_kind":"provider_http|provider_timeout|provider_network|invalid_output","detail":"..."}. Messages are sanitized; provider response bodies, keys and credential URLs are never echoed. No redirects are followed. Connection timeout is 10 seconds, with a 30-second overall request deadline; responses above 1 MiB are rejected.

Positive integer limits: RECALLNEST_MAX_UPLOAD_BYTES (32 MiB), RECALLNEST_MAX_ZIP_BYTES (128 MiB), RECALLNEST_MAX_ZIP_MEMBERS (1000). The request body is limited to upload limit + 64 KiB for multipart overhead, including chunked requests. The individual file is also read in bounded chunks and limited separately. Limit failures return 413. Deliberately increase limits for larger trusted exports.

## Import preview and confirmation

POST /import/preview and POST /import accept multipart/form-data with required file and optional text source_identity. Use identical bytes/identity for preview and confirmation. Identity defaults to the JSON-provided identity, then source name. Stable identities (e.g. chatgpt-account-a) distinguish exports with the same source/external ID. Preview does no database operations or job creation.

Supported extensions: .json, .jsonl, .md, .markdown, .zip. JSON accepts ChatGPT conversation lists with mapping, one normalized conversation, a normalized list, or {"conversations":[...]}. ZIP reads nested conversations.json directly in memory. All members, including ignored files, are checked for absolute, drive-qualified and .. paths. Upload bytes, total expanded bytes and member counts are bounded. Unknown structures/formats fail explicitly. Imports are atomic, with no partial persistence on errors.

Normalized file input:

~~~json
{
  "source":"tool-name","source_identity":"account-or-workspace",
  "external_id":"session-42","title":"学习计划",
  "created_at":"2026-10-14T00:00:00Z","updated_at":"2026-10-14T00:01:00Z",
  "current_node":"a1","project_id":null,"metadata":{},
  "messages":[
    {"id":"u1","role":"user","content":"我偏好中文。","timestamp":"2026-10-14T00:00:00Z","parent_id":null},
    {"id":"a1","role":"assistant","content":"已收到。","parent_id":"u1"}
  ]
}
~~~

source and messages are required for normalized file input; other fields are optional. Message external_id is accepted when id is absent. Roles: user/assistant/system/developer/tool. Input message IDs/parents are external IDs. Parents must exist in the input or previously imported conversation. Duplicate IDs and parent cycles fail transactionally. Without conversation external IDs, a canonical fingerprint of title, normalized messages and full raw source is used. Renamed files replay without duplicates. Edits/appends of no-ID conversations can create new fingerprints; integrations should provide stable IDs. No-ID message fingerprints include position; stable message IDs are required to recognize edits.

Preview:

~~~json
{
  "conversations":1,"messages":2,"errors":0,"non_text_blocks":0,"warnings":[],
  "items":[{"source":"tool-name","source_identity":"account-or-workspace","external_id":"session-42","title":"学习计划","messages":2,"current_node":"a1"}]
}
~~~

Import:

~~~json
{
  "imported":1,"updated":0,"duplicates":0,"messages":2,"edited_messages":0,
  "duplicate_messages":0,"errors":0,"error_details":[],
  "conversation_ids":["internal-conversation-id"]
}
~~~

imported = new conversations; updated = changed existing conversations; duplicates = unchanged conversations; messages = newly added messages; edited_messages = changed existing message versions; duplicate_messages = identical incoming messages. Successful imports have errors=0; error_details=[]; failed uploads use HTTP detail. Repeat import creates no duplicate messages/jobs. Each changed conversation revision creates one consolidation job; raw metadata changes also advance revision.

ChatGPT preserves full mapping, parents, all branches and current_node. Empty/root nodes remain raw; rendered parents skip those nodes. metadata.node_message_ids maps source graph node IDs to external message IDs. Non-text/image/audio blocks remain raw metadata and appear in non_text_blocks/warnings; referenced media pixels/audio files are not fetched or extracted.

Codex requires session_meta and supports response_item message plus event_msg user_message/agent_message shapes. Adjacent equal event/response representations are deduplicated; raw.records archives every parsed record, including duplicate representations, tool calls and unsupported blocks. Malformed complete JSONL lines report one-based line numbers. Parser allow_partial=True is reserved for a future watcher; uploads remain strict. Markdown recognizes # through ###### user/assistant or 用户/助手 headings; generic notes become one user-role source record. Import performs no automatic fact extraction.

## Conversations and branches

| Method/path | Request/result |
| --- | --- |
| GET /conversations | List; q, source, project_id, date_from, date_to filters. |
| POST /conversations | Create fields below; returns detail. |
| GET /conversations/{id}?branch={message_id} | Detail; branch is an internal message ID. |
| PATCH /conversations/{id} | Subset of title, project_id, current_node; current_node is internal ID. |
| POST /conversations/{id}/messages | {"messages":[...],"current_node":null}; detail response. |

Create fields/defaults: source="manual", source_identity=null, external_id=null, title="Untitled", project_id=null, current_node=null, messages=[]. Absent external IDs are allocated for application-created conversations. Create messages use the normalized message shape. Append messages have id=null, required role/content, timestamp=null, parent_id=null, raw={}, metadata={}. Input IDs/parents are external IDs. Absent append IDs are allocated; integrations should provide them for idempotent retry. Omitted parents attach new messages to the selected branch, then the preceding new message; explicit null detaches. Repeated IDs edit existing messages rather than duplicate; omitted timestamp/parent preserve old values. Append current_node is an external ID. The append read/write is atomic and only incoming messages are updated.

List fields: id, source, source_identity, external_id, title, created_at, updated_at, imported_at, project_id, current_node, current_node_external, revision, metadata, message_count. Detail adds raw, messages, raw_versions, branches, active_message_ids.

~~~json
{
  "id":"conversation-id","source":"tool-name","source_identity":"account-a",
  "external_id":"session-42","title":"学习计划",
  "created_at":"2026-10-14T00:00:00+00:00","updated_at":"2026-10-14T00:01:00+00:00",
  "imported_at":"2026-10-14T02:00:00+00:00","project_id":null,
  "current_node":"internal-a1","current_node_external":"a1","revision":1,
  "metadata":{},"raw":{},"message_count":2,
  "messages":[{
    "id":"internal-u1","conversation_id":"conversation-id","external_id":"u1","role":"user",
    "content":"我偏好中文。","timestamp":"2026-10-14T00:00:00+00:00",
    "parent_id":null,"parent_external_id":null,"position":0,"version":1,"raw":{},"metadata":{},
    "versions":[{"id":"version-id","message_id":"internal-u1","version":1,"role":"user",
      "content":"我偏好中文。","timestamp":"2026-10-14T00:00:00+00:00","parent_external_id":null,
      "raw":{},"metadata":{},"recorded_at":"2026-10-14T02:00:00+00:00"}]
  }],
  "branches":[{"leaf_id":"internal-a1","external_id":"a1","message_ids":["internal-u1","internal-a1"]}],
  "active_message_ids":["internal-u1","internal-a1"],
  "raw_versions":[{"conversation_id":"conversation-id","revision":1,"raw":{},"metadata":{},"recorded_at":"2026-10-14T02:00:00+00:00"}]
}
~~~

The abbreviated sample omits the second message object. messages contains all branches; active_message_ids selects root-to-leaf order. Branch queries are read-only; PATCH selection persists the display branch. Source current_node_external/raw graph remain archived. Versions preserve prior raw/content/role/time/parent with increasing version numbers. Source-replay omissions retain existing archive nodes. Latest application-append raw contains original source_record plus incoming messages; raw_versions preserves each previous append event.

## Evidence and derived conventions

Evidence input: {"message_id":"internal-u1","quote":"偏好中文","conversation_id":null,"message_version":null}. The message must exist and quote must be a non-empty exact substring of the archived referenced message version. Conversation ID is filled/checked; omitted version binds current. Output adds resolved conversation_id/message_version and stale=false. Message edits can set stale=true while the old quote/version remains retrievable; clients should mark stale evidence visibly.

Every derived entity returns its create fields plus id, created_at, updated_at. Detail/create/update also includes history=[prior complete payload snapshots]. Lists omit entity history. Reviews always include grade_history. JSON export includes global entity_history. Handwritten content can have empty evidence; no source links are fabricated.

## Knowledge

GET/POST /knowledge; GET/PATCH/DELETE /knowledge/{id}; POST /knowledge/{id}/favorite with {"favorite":true}.

Create: required non-empty title; summary="", body="", type="note" (extensible string), tags=[], project_id=null, favorite=false, unresolved=false, evidence=[], source="manual". PATCH edits any create field. For open questions use type="unresolved" and unresolved=true. Delete unlinks review knowledge_id but retains card answers/evidence.

List filters: q, source, project_id, type, tag, date_from, date_to, favorite, unresolved. Source matches entity source or evidence conversation source. Tags match exact tag strings. q matches title/summary/body/tags as literal substrings, including Chinese; SQL %, _ and backslash are escaped. Date filters are inclusive YYYY-MM-DD creation dates. Lists sort newest first.

## Projects

GET/POST /projects; GET/PATCH/DELETE /projects/{id}; GET /projects/{id}/links.

Create: required non-empty name; description="", status="active", goals=[], artifact_links=[]. Status: active/paused/completed/archived. Links contain title="" and required HTTP/HTTPS url; script schemes fail. List filters: q, status. PATCH edits create fields. Deletion unlinks related conversations/knowledge/cards, preserving entities and sources.

Links response: {"project_id":"id","artifact_links":[{"title":"Repo","url":"https://example.com"}],"conversations":[...],"knowledge":[...],"reviews":[...]}. Link conversations by PATCH project_id; link knowledge/cards through create/edit project_id.

## Memories

GET/POST /memories; GET/PATCH/DELETE /memories/{id}; GET /memories/context. Context returns confirmed active memories only. List filters: q, status, category.

Create: required non-empty content and category; subject="", status="candidate", supersedes=null, effective_at=null, expires_at=null, evidence=[], source="manual". Categories: preference/background/goal/state/constraint. Status: candidate/confirmed/rejected/expired/superseded. Source: manual/extracted/demo. Missing effective_at uses creation time. Handwritten memories stay manual without fabricated evidence. Consolidation rejects personal candidates from assistant text or user questions.

Confirm/reject/expire via PATCH {"status":"confirmed"}, rejected or expired. Explicit replacement uses supersedes="old-memory-id" with matching category/subject; self/cyclic relations fail. Candidate replacements leave current confirmed memories active. Confirming a replacement atomically supersedes its predecessor and preserves predecessor/history. A future-dated confirmed replacement is rejected; keep it candidate until effective. Context excludes expired-by-date, future-effective and all-stale/no-valid-proof memories; manual confirmed memories with evidence=[] remain allowed. A confirmed exact memory with renewed current proof stays active even when older proof is stale. Active projections contain only current valid evidence and omit original source_context; full stale/current proof and original derivation metadata remain in detail, ordinary lists, history and export. The same projection feeds chat, repository/MCP context and memory search, so no stale proof is labeled active. Candidate/rejected/expired/superseded statuses remain inactive regardless of new proof. Rejecting/expiring a replacement does not automatically reactivate its predecessor. Deleting a referenced predecessor fails; preserve its history and expire instead.

## Review

GET/POST /reviews; GET/PATCH/DELETE /reviews/{id}; POST /reviews/{id}/grade.

Create: required non-empty question; answer="", knowledge_id=null, project_id=null, evidence=[], due_at=null, paused=false, source="manual". Linked knowledge must exist; omitted project/evidence inherit from knowledge. Missing due_at is immediately due. PATCH edits create fields, including question/answer, custom due_at and paused=true/false.

List filters: q, source, project_id, date_from, date_to, due=false, paused (optional). Review date filters apply to due date for project/date review sets. due=true excludes paused/future cards. Sort: earliest due first. Grade body: {"grade":"again"}, choices again/hard/good/easy. Paused cards cannot be graded.

Response includes interval_minutes, repetitions and grade_history:

~~~json
{
  "id":"card-id","question":"Q","answer":"A","knowledge_id":null,"project_id":null,"evidence":[],
  "source":"manual","paused":false,"created_at":"2026-10-14T00:00:00+00:00",
  "updated_at":"2026-10-14T00:00:00+00:00","due_at":"2026-10-17T00:00:00+00:00",
  "interval_minutes":4320,"repetitions":1,"history":[],
  "grade_history":[{"id":"grade-id","review_id":"card-id","grade":"good",
    "reviewed_at":"2026-10-14T00:00:00+00:00","previous_due_at":"2026-10-14T00:00:00+00:00",
    "next_due_at":"2026-10-17T00:00:00+00:00","interval_minutes":4320}]
}
~~~

Simple intervals from grading time: again=10 minutes; hard=max(1 day, floor(previous interval×1.2)); good=max(3 days, previous interval×2); easy=max(7 days, previous interval×3). Repetitions counts every grade. Each event saves previous/next due times. This is not FSRS. Repository methods accept an injected UTC clock for deterministic tests; HTTP uses server time.

## Consolidation jobs

~~~json
{
  "id":"job-id","type":"consolidate","conversation_id":"conversation-id","conversation_revision":1,
  "status":"queued","attempts":0,"error":null,"error_kind":null,
  "created_at":"2026-10-14T00:00:00+00:00","updated_at":"2026-10-14T00:00:00+00:00",
  "payload":{"message_versions":{"internal-u1":1}},
  "next_attempt_at":null,"disposition":null,"result":null
}
~~~

GET /jobs returns {"items":[jobs...]}, sorted by created_at then ID. Unknown status filters fail 422. POST /jobs/{id}/run immediately runs a queued job, bypassing its backoff for this explicit action; already running/completed/failed jobs return their current state. POST /jobs/run runs the next queued job and returns {"job":job-or-null}. POST /jobs/{id}/retry resets a non-running job to queued with attempts=0 and clears its error/disposition/result. Running jobs cannot be retried (422); missing IDs are 404. Retry queues work; use /run for an immediate manual attempt. Completed source versions remain in the processing ledger, so retry never duplicates or overwrites successful derived items.

Source imports/appends enqueue transactionally, unique by type/conversation/revision. The worker atomically leases one queued job, records running, then makes provider calls outside the write transaction. Leases last 120 seconds and renew before each chunk. Expired/interrupted claims recover to queued, or failed after three attempts. A replaced/expired token cannot commit a late result. Shutdown interrupts between chunks and waits for the active HTTP request to finish. Temporary provider HTTP 429/5xx, timeout/network and interruption failures retry up to three attempts with 10/20-second backoff (no hot loop). Authentication/validation/other failures need manual retry. Unconfigured jobs fail with configuration_required, attempts=0; valid settings save wakes them. Other error_kind values: provider_http, provider_timeout, provider_network, invalid_output, input_limit, interrupted, internal_error. Error strings are fixed sanitized text or a numeric HTTP status, never provider bodies.

Completed disposition is extracted, superseded (source changed), synthetic_skipped (explicit demo), or no_new_text. result={"knowledge":N,"memories":N,"reviews":N,"processed_messages":N}; counts identify new derivations, including corroborating memory merges. Skips have zero counts and make no AI result claim. Demo jobs never call a provider. Empty/whitespace-only message text is excluded from processing; a job with no pending nonblank text completes as no_new_text with zero attempts/counts/model calls. A later nonblank edited version is still processed.

The initial current revision processes **all nonblank messages at their current versions on every branch**, including long single messages, using lossless slices up to 3500 characters. Slices shrink when JSON escaping/UTF-8 encoding requires it; the complete serialized source JSON (including conversation metadata) is capped at 14000 bytes and the complete serialized provider request (including schema prompt/model/options) at 65536 bytes. Both budgets are checked during batching and again before extraction HTTP calls. Source/title/external-ID metadata sent to the model uses at most 200-character previews, with original length and SHA-256 when shortened; archives keep full values. Citation, parent and branch internal IDs remain real. Very wide branch identity lists carry a count/hash and first 32 leaf IDs; the complete graph remains archived. Prior edited message versions remain archived; they do not become current personal context. A persisted message/version ledger makes later jobs send only new/edited versions. Unchanged text on conversation-only raw-record revisions needs no new model call. Chunk source includes internal/external ID, role, version, parent, offset, conversation, source, revision and branch identities. The model is instructed to treat branches separately and source text as untrusted data.

Extraction must provide all three arrays knowledge/memories/reviews. Every item needs at least one exact quote, internal message ID and current positive version from its actual supplied chunk. Knowledge types are summary/topic/qa/decision/unresolved. Strict bounded schemas reject unknown/missing fields, oversized lists/text and nonfinite numbers. Every personal candidate additionally requires assertive user-role evidence and exact verbatim content inside that quote; no case/whitespace normalization crosses this gate. Normalization is used only to merge already validated corroborating memories. Assistant/tool text, questions, hypothetical/quoted text and unsupported paraphrases are conservatively rejected. Explicit personal statements in knowledge/review factual fields are rejected and the prompt directs them into memory candidates. This conservative screening does not prove truth or detect every linguistic formulation. All extracted memories remain candidate until user confirmation.

All chunk outputs are validated before one transactional insertion. The same transaction checks conversation revision, the complete message-version map and lease token; changed sources discard the whole result as superseded. Stable derivation keys and the processing ledger prevent duplicate writes. User-edited knowledge/cards are not overwritten. Exact normalized category/subject/content memory matches merge evidence while preserving status, content, expiry and history, including rejected/expired records. Conflicting state stays a separate candidate for explicit supersedes confirmation. Derived payloads may add read-only source_context={"conversation_id":"...","revision":1,"source":"...","messages":[{"id":"...","role":"user","parent_id":null,"version":1,"branch_leaf_ids":["..."]}]}; manual edits preserve it. Historical/stale evidence remains displayable in the archive and is excluded from future personal context.

## Search and vectors

GET /search requires q (1–2000 characters), optional limit (1–50, default 20), semantic=false, source, project_id, type, tag, entity_type, date_from and date_to. entity_type values used by results: conversation, message, knowledge, memory. type is conversation/message/memory or a knowledge type. Tags match exactly; source matches an entity source or its evidence conversation source; date filters are inclusive YYYY-MM-DD creation/message dates. Only active confirmed memories are searchable as personal context; raw messages and stale knowledge remain searchable as archive material. Conversation text search/index uses its title; message search uses its full text. Literal queries, Latin tokens and Chinese bigrams supply text ranking. Stable ties sort entity_type then ID.

~~~json
{"items":[{"id":"...","entity_type":"knowledge","title":"SQLite","excerpt":"...","source":"extracted","project_id":null,"type":"topic","tags":["db"],"created_at":"2026-10-14T00:00:00+00:00","evidence":[{"message_id":"...","conversation_id":"...","message_version":1,"quote":"...","stale":false}],"score":0.65,"text_score":0.65,"semantic_score":null}],"mode":"text","warning":null}
~~~

Excerpts are at most 1000 characters; message hits provide a real quote up to 500 characters. Manual entries/conversation titles without evidence keep evidence=[]; references are never fabricated. score/text_score are bounded 0–1; semantic_score is null or cosine in −1–1. Hybrid score uses 0.7×text + 0.3×max(0,cosine), capped at 1. semantic=true requests a query embedding and considers compatible persisted vectors. mode=hybrid indicates query embeddings were available, not that reindexing has completed. On unavailable/failed embeddings, search falls back to text and warning={"error_kind":"...","detail":"sanitized message"}; otherwise warning=null. Text search works without any model configuration.

POST /search/reindex has no body and explicitly indexes current conversations/messages/knowledge/active confirmed memories. Success: {"indexed":N,"skipped_changed":N,"model":"embedding-model","status":"completed"}. Missing provider/embedding model returns 409 configuration_required; HTTP/output errors return 502 with sanitized error_kind/detail. All vectors validate finite nonzero numeric components, bounded dimensions (1–8192), consistent dimensions and complete provider indices. Long source texts are embedded in full 3500-character slices and combined with a character-weighted mean, then validated. A failed indexing request writes no partial vectors; items changed during the request are skipped at commit. Vectors persist with a full text/content-version hash, hashed provider identity (URL/key) and embedding model. Changed source versions/content, provider/key or model never uses an old incompatible vector. No automatic indexing completion is implied; invoke reindex after relevant changes.

## Personalized chat

POST /chat accepts {"conversation_id":null,"branch":null,"content":"message","client_turn_id":"stable-client-generated-id"}. client_turn_id is required (1–200 characters), content is required/nonblank and at most 16000 characters. conversation_id omitted/null creates a chat conversation. A non-null branch requires an explicit existing conversation and a nonempty valid internal message ID in it; empty/invalid branches or a branch without an existing conversation fail 422 before user/conversation writes or model calls. Omitted/null branch attaches to current_node. Reuse the same client_turn_id and content/branch on transport/provider retry. IDs are global per data directory; reusing one with a different request or conversation fails 422.

~~~json
{"conversation_id":"...","client_turn_id":"...","user_message":{"id":"...","role":"user","content":"...","parent_id":"..."},"assistant_message":{"id":"...","role":"assistant","content":"...","parent_id":"user-internal-id"},"used_context":{"memory_ids":["..."],"knowledge_ids":["..."],"message_ids":["..."],"evidence":[{"message_id":"...","conversation_id":"...","message_version":1,"quote":"...","stale":false}]},"error_kind":null,"detail":null}
~~~

The message objects are complete archived message objects from conversation detail, including external ID, version/raw/metadata/versions; the example abbreviates them. The user message is persisted **before** the provider request or missing-configuration failure. Success saves a real assistant reply with an explicit parent to that user, enqueues source revision jobs and returns 200. A completed retry returns the same user/reply IDs with no provider call. An in-flight retry returns 409 turn_running and the existing user. Provider failure returns 502 with the same shape, assistant_message=null, error_kind and sanitized detail. Unconfigured provider returns 409 configuration_required. Branch/cited-source edits during the provider call return 409 stale_turn with no assistant; an expired execution lease returns 409 turn_interrupted. Concurrent later turns keep their newer current_node; the older reply remains archived on its actual branch.

The provider context includes active confirmed memories with only their current valid proof, relevant cited non-stale knowledge and appropriate active-branch messages. Knowledge with any stale evidence remains conservatively excluded because it may contain compound claims. Candidate/rejected/expired/superseded memories are excluded. The complete serialized UTF-8 chat request, including model/system/options and JSON escaping, is capped at 65536 bytes. Context construction reserves the complete current user turn first, then includes whole memory/knowledge blocks that fit, then fitting tails of older active-branch messages. Secondary caps are 10000 characters for combined memory/knowledge JSON, 24000 characters for active messages and up to 4000 characters per older tail; the byte budget can trim further. The current user turn is never silently truncated. AIClient.chat independently enforces the final serialized byte limit before HTTP.

If a configured chat's current user turn cannot fit by itself with the required system/model envelope, /chat returns 413 with the normal chat result shape: assistant_message=null, used_context={"memory_ids":[],"knowledge_ids":[],"message_ids":[],"evidence":[]}, error_kind="request_too_large", detail="Chat request exceeds the 65536-byte provider request limit". conversation_id/client_turn_id/user_message identify the saved full user turn. No provider call or fake assistant occurs, and retry with the same client_turn_id preserves that user ID without duplicating it. The 16000-character REST field limit still applies separately (422 for invalid input before persistence).

Imported system/developer/tool content is downgraded to ordinary source content. used_context reports only items actually attempted/sent, with source evidence; omitted memory/knowledge blocks and older messages are omitted from its IDs/evidence. Unconfigured or locally oversized chat makes no HTTP call and returns empty context even though its user turn is saved. Retry after configuration rebuilds the context from current valid records. Manual confirmed memories may have empty evidence. Connection keys/headers never enter the system prompt. No fake assistant is written on any failure.

## Explicit synthetic demo

POST /demo has no body. Imports three embedded labeled synthetic sources (demo:chatgpt, demo:codex, demo:markdown), creates a labeled project, source-linked knowledge/card and candidate memory, and calls no model. Embedded examples work in an installed wheel; examples/ provides separately importable public fixtures. Deterministic demo entity IDs make it idempotent and preserve edits on repeat.

Response: import count fields plus demo=true and created={"projects":1,"knowledge":1,"reviews":1,"memories":1} initially (zero on repeat). Demo memory remains candidate until confirmed. Source/title labels and metadata.synthetic=true distinguish demo conversations. This tests the actual UI with an unconfigured model; it is not AI extraction.

## Export

GET /export?format=json (default) downloads recallnest-export.json as application/json. Root fields: schema_version=1, exported_at, conversations, knowledge, projects, memories, reviews, jobs, entity_history. One SQLite read snapshot covers the complete export, preventing mixed revisions during imports/worker writes. Conversations include every branch, raw source records and all message/conversation versions. Evidence, review grades and supersession history remain linked by stable IDs/versions. Entity-history rows: id, entity_type, entity_id, payload, recorded_at.

Configuration, provider URLs and API keys are excluded. Secrets a user put in conversation content are user source data and remain in the archive.

GET /export?format=markdown downloads UTF-8 recallnest-export.md as text/markdown, containing source/derived text and message/version evidence references. JSON is the complete source/entity archive with non-text metadata; Markdown is a readable text view. Unknown formats return 422. Schema 1 preserves restoration data, but there is no archive-restore endpoint. Importing exported conversations as ordinary normalized input does not restore derived entities/IDs. Operational leases, processing ledgers, chat idempotency reservations and vectors are database-only; back up the data directory for full operational recovery or retain the JSON pending restore support.
