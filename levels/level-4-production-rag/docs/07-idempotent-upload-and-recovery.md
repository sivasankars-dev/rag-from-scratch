# 07 — Idempotent PDF Upload and Recovery

## 1. Scope and evidence

**Level:** 4 — Production RAG

**Milestone:** Day 07 / F02 — tenant-scoped idempotent PDF upload

**Status:** Bounded HTTP integration and explicit recovery/reconciliation services implemented; background recovery and production readiness are not established.

The earlier [validation guide](05-secure-pdf-upload-validation.md) introduced authenticated multipart validation. F01 subsequently added MinIO storage and PostgreSQL document/version persistence. F02 addresses the next problem: a client can lose a response even though an upload succeeded. Repeating that request must not silently create another logical document.

This guide explains the current implementation. The [claim contract](06-upload-claim-contract.md) retains the detailed, chronological contracts for T1, T2 and Stages 3A–3D. Earlier stage limitations in that document are historical, not a statement that later stages remain absent.

Recorded verification evidence from the preceding implementation task: **18 real PostgreSQL + MinIO E2E tests passed**, and **319 combined relevant tests passed, 1 warning, in 14.26 seconds**. These are local verification results, not CI or load-test guarantees. This documentation-only task did not rerun them or change a database.

## 2. What are we learning?

By the end of this checkpoint, be able to explain:

- Why an idempotency key identifies a request within a tenant, while a fingerprint identifies its exact intended content.
- Why PostgreSQL can atomically commit document metadata but cannot atomically commit a MinIO PUT with it.
- Why an expired lease permits takeover but does not stop the old process.
- How generation/token checks protect logical completion, and separate object keys protect newer attempts from old writes or cleanup.
- Why an unknown outcome must be reconciled rather than treated as failure.

This is upload acceptance, not RAG ingestion. T2 creates version 1 with status `READY`; it does not set the document's active version, parse pages, create embeddings or make the PDF searchable. The distinction follows the [architecture and capacity plan](02-architecture-and-capacity-plan.md).

## 3. F01 and F02 share an endpoint

`POST /tenants/{tenant_id}/documents/upload` accepts multipart field `file` and a verified bearer JWT.

| Request | Implementation | Retry behavior |
| --- | --- | --- |
| No `Idempotency-Key` header | F01 `persist_document_upload` | Another request can create another document |
| Header present and valid | F02 keyed application | Same tenant/key is coordinated through PostgreSQL |
| Header present but invalid | Keyed rejection | Never falls back to F01 |

Both paths retain extension, non-empty file, 10 MiB file limit and leading `%PDF-` checks. The route caps the whole multipart body at 11 MiB. Multipart parsing can precede authentication; this is not a concurrent-upload quota or an upload-duration limit.

A key must occur exactly once, contain 1–255 printable ASCII characters with codes 33–126, and contain no whitespace. There is no trimming or case normalization. Identity comes from JWT verification and active user/tenant/membership checks, never multipart identity fields.

F01 retains its existing response and error behavior. Its synchronous persistence/storage flow can hold a database transaction during storage. The short-transaction and worker-thread guarantees below describe **F02**, not a retrofit of F01.

## 4. Responsibilities and relevant files

Paths are relative to `levels/level-4-production-rag/`.

| File | Responsibility |
| --- | --- |
| `app/routers/documents.py` | Select dependency graph by header presence, bound/validate multipart, serialize typed outcomes |
| `app/keyed_upload_auth.py` | Resolve verified principal in a short-lived session; return frozen IDs |
| `app/auth.py`, `app/tenant_auth.py` | JWT identity and active tenant membership |
| `app/database.py` | Dedicated READ COMMITTED session factory sharing the engine pool |
| `services/keyed_upload_application.py` | Worker-thread boundary, server fingerprint, T1 and bounded recovery handoff |
| `services/upload_idempotency.py` | Versioned deterministic fingerprint |
| `services/upload_claim_service.py` | T1 atomic claim or authorized existing-operation decision |
| `services/fenced_upload_service.py` | Private snapshot, fresh preflight, PUT, atomic fenced T2 and limited compensation |
| `services/upload_recovery_service.py` | R1 expired-lease takeover and receipt reconciliation |
| `services/verified_recovery_service.py` | Verify retry/historical bytes and write the current attempt key |
| `services/upload_reconciliation_service.py` | Resolve durable state/current object; advisory orphan inventory |
| `services/upload_result.py` | Shared completed-result validation |
| `services/upload_http_contract.py` | Typed internal decisions to stable HTTP outcomes |
| `services/document_storage.py`, `services/minio_storage.py` | Storage protocol and S3-compatible implementation |
| `services/document_upload_service.py` | Existing F01 no-key persistence |

PostgreSQL owns logical identity, authorization coordination and publication state. MinIO stores bytes. A storage key or a returned Python claim object alone is never sufficient authority to complete a document.

## 5. Durable operation, physical attempts and fingerprint

### One operation, potentially several attempts

`app/models/upload_operation.py` stores the tenant/key, original requester, fingerprint version/hash, title, size, content digest, status, current lease generation/token/expiry and completed result IDs.

`app/models/upload_attempt.py` records each physical intent: operation/tenant, generation/token, reserved document/version IDs, unique storage key, expected size/digest and creation time.

Important database constraints:

- Unique `(tenant_id, idempotency_key)` arbitrates simultaneous first requests.
- The requester has a composite foreign key to tenant membership. Active status still requires application checks.
- Attempts reference `(operation_id, tenant_id)` together, preventing cross-tenant association.
- `(operation_id, lease_generation)` and `storage_key` are unique; generation/size are positive and digest is lowercase SHA-256 hex.
- Completed operations require paired document/version references, with composite relationships enforcing document/version and tenant/document consistency.
- Existing document/version constraints remain, including unique document/version number and a nonblank storage key for a `READY` version.

Reserved IDs intentionally have no foreign key to result rows: those rows do not exist until T2. Every later attempt preserves the first attempt's canonical IDs. A new generation means another physical upload intent, not another logical document.

The migration chain adds storage keys (`3e8decfb45b9`), the READY constraint (`4c2a23ad91fa`), operations (`183436ed67c3`), then durable attempts/request/lease fields (`7b9c2d4e6f80`). The last migration allows the new request metadata group to remain entirely null for existing operations, with generation default 0. It does not fabricate ownership or recovery history for legacy rows. Services refuse to execute or replay unresolved legacy state. No new migration is needed for the integrated router.

> **Legacy database migration limitation:** The storage-key migration
> (`3e8decfb45b9`) adds a nullable `storage_key` column. The subsequent
> constraint migration (`4c2a23ad91fa`) requires every `READY`
> document version to have a nonempty storage key.
>
> Existing databases containing `READY` versions without storage keys
> will fail this upgrade unless those rows are migrated first. The
> current development database was verified at revision
> `7b9c2d4e6f80` with no document-version rows.
>
> This milestone validates fresh-install/development migrations, not
> upgrades of populated legacy databases. Existing-data upgrades
> require a separately tested data-transition strategy. Do not
> fabricate storage keys or reset existing data to bypass the constraint.

Immutability across attempts is enforced by these services and history validation, not a database trigger preventing arbitrary updates. Retain history: current recovery/replay checks require contiguous generations from 1 through the current generation.

### Why length prefixes matter

Fingerprint v1 hashes the domain tag `production-rag/pdf-upload/v1\x00`, followed by three fields, each preceded by its byte length encoded as an unsigned 8-byte big-endian integer:

1. Exact stored title/filename in UTF-8.
2. Exact byte count as decimal ASCII.
3. Raw SHA-256 digest of the entire PDF byte stream.

Lengths prevent ambiguous concatenation boundaries. The helper hashes from offset zero, verifies the declared size, and restores the original cursor even on size mismatch. The caller validates PDF policy; the fingerprint helper alone is not a PDF validator.

Changing bytes, size or title changes the request identity. Retrying identical bytes as `renamed.pdf` conflicts with an original `handbook.pdf` under the same key. Tenant and requester are enforced separately by durable ownership checks. Filenames are stored as metadata, not interpolated into object paths.

## 6. Follow a first keyed request: T1 → PUT → T2

```text
Client       Router/auth       Keyed worker          PostgreSQL        MinIO
  | POST          |                  |                   |               |
  |-------------->| verify identity; close auth session |               |
  |               | validate PDF     |                   |               |
  |               |----------------->| fingerprint       |               |
  |               |                  | T1 claim+attempt->| COMMIT        |
  |               |                  | fresh preflight-->| close         |
  |               |                  | PUT snapshot -------------------->|
  |               |                  |<-------------------- acknowledged |
  |               |                  | T2 rows+COMPLETED>| COMMIT        |
  |<--------------------- 200 canonical document/version IDs             |
```

1. Keyed authentication opens and closes its own session before storage. It returns IDs, not live ORM entities.
2. `execute_keyed_upload` awaits `anyio.to_thread.run_sync(..., abandon_on_cancel=False)`. Synchronous hashing, database and storage orchestration run in that worker. Sessions are created there; none crosses the thread boundary. The upload stream remains borrowed until the await completes and FastAPI closes the multipart resource.
3. T1 locks active authorization rows, then uses `INSERT ... ON CONFLICT DO NOTHING` against the tenant/key constraint. A winning insertion persists `PROCESSING` plus generation 1's attempt in one transaction. A conflicting insertion uses a separate READ COMMITTED statement to inspect the winner after contention resolves.
4. T1 commits before returning an executable claim. It creates no document/version result rows yet.
5. Fenced execution copies and verifies a private snapshot. A short preflight reloads authorization, operation and attempt, matching identity, metadata, status, token, generation and unexpired lease.
6. Preflight closes before PUT. A conservative monotonic deadline includes transaction completion and session-close time; known-expired work is rejected immediately before storage.
7. PUT writes only the reserved attempt key, outside a database transaction.
8. T2 reloads authoritative state, inserts the reserved document and version, then conditionally changes the operation to `COMPLETED` with those exact IDs. The final update checks status, generation, token and `lease_expires_at > clock_timestamp()`. Any failed guard rolls back both result inserts.

Concurrent finalizers serialize on the operation row; a valid completed result replays rather than creating another result. Expiry after the successful guarded update does not undo it: the operation lock orders any takeover after this transaction resolves.

The default lease is 120 seconds. Dedicated sessions require READ COMMITTED; the common helper sets transaction-local 1-second lock and 5-second statement timeouts. These are not pool-acquisition, network or total-request deadlines.

Lock order is active authorization rows (`User`, `Tenant`, `Membership`) → tenant operation → attempt rows → result work. History reads order attempts by generation and ID. This protocol reduces conflicting lock order; it is not a guarantee against all database deadlocks, particularly with unrelated writers.

## 7. State transitions and retry decisions

| Durable state | Condition/action | Resulting state / decision |
| --- | --- | --- |
| Absent | Authorized T1 wins tenant/key insertion | `PROCESSING`, generation 1 |
| `PROCESSING` | Same requester and metadata, live lease | Unchanged; `IN_PROGRESS` |
| `PROCESSING` | Different request metadata | Unchanged; `CONFLICT` |
| `PROCESSING` | Expired valid operation; R1 commits | `PROCESSING`, next generation, fresh attempt |
| `PROCESSING` | Current authorized fence passes T2 | `COMPLETED`, canonical result IDs |
| `PROCESSING` | Known non-retryable T2 failure; cleanup reservation succeeds | `FAILED` before external deletion |
| `COMPLETED` | Same authorized request and valid result | Unchanged; replay |
| `FAILED` | Retry or recovery | Unchanged; terminal rejection |
| Any | Wrong requester, revoked membership, disabled user/tenant | No executable claim or exposed result |
| Legacy/inconsistent | Ownership/history/result cannot be validated | No automatic repair or execution |

Completed validation is shared across services. It checks canonical history/IDs, tenant/requester ownership, a nondeleted document, a READY version and the exact current attempt key. Replay does **not** GET MinIO or establish that the object still exists after completion.

A tenant/key is not transferable between users in that tenant. A second active member cannot retrieve the first requester's result using the same key. The same text key in another tenant is a different operation, subject to that tenant's authorization.

## 8. Lease expiry and atomic recovery ownership

A lease measures permission to finalize, not whether a process is alive. A slow worker can continue a PUT after expiry. PostgreSQL time, sampled after operation/history locking, decides whether R1 may take over.

`recover_upload` accepts the authorized operation reference returned by T1's `RECOVERY_REQUIRED`. R1 rechecks original requester authorization, status, history and lease. It returns replay for completed work, in-progress for a live owner, and stable non-executable decisions for FAILED, legacy or inconsistent state.

For expired valid PROCESSING state, one short transaction:

1. Preserves original request metadata and first attempt's reserved IDs.
2. Increments generation and creates a fresh token, expiry and attempt UUID.
3. Persists a new unique key:

```text
tenants/{tenant}/documents/{document}/versions/{version}/attempts/{attempt}/source.pdf
```

4. Commits before returning a usable claim. Previous attempts are not modified.

Two recovery workers contend on the operation lock. The waiter sees the winner's live lease and does not create a competing generation. If that new lease has itself expired, a later takeover is legitimate. Fresh preflight and T2 still validate every returned claim.

There is no heartbeat, implicit lease renewal or background scanner. The router performs at most one recovery handoff per request, using the supplied retry body. A completed R1 alone does not mean bytes have been recovered.

## 9. Recovering verified bytes

`execute_recovery_upload` first validates current ownership and persisted history in PostgreSQL, then closes that transaction. Candidate keys come only from older attempts of the same operation and tenant, newest first. Callers cannot supply arbitrary historical object keys.

A valid retry body is preferred. Otherwise the service reads historical candidates into a private spool with a 1 MiB memory threshold and the existing 10 MiB upload limit. Reads are bounded to expected size plus one byte; verification requires exact size, `%PDF-`, SHA-256 and the complete versioned fingerprint. ETags or claimed object metadata are not accepted as proof.

Storage streams close on success and failure. The caller retains ownership of the retry stream and its cursor is restored. A valid snapshot supplies a new PUT to the **current attempt key**, followed by fenced T2. Recovery never publishes an older attempt key or trusts an unverified server-side copy.

| Observation | Meaning/action |
| --- | --- |
| Explicit `NoSuchKey` | Candidate missing; try another |
| Wrong digest, truncated/oversized bytes or wrong signature | Candidate corrupt; try another |
| No valid body/candidate | `SOURCE_REQUIRED`; no additional takeover attempt created by this service |
| Access/credential denial | Infrastructure/access failure; stop |
| Timeout or other open error | Unavailable; stop |
| Interrupted read or stream-close failure | Interrupted; stop |

A missing bucket or generic HTTP 404 is not mapped to a missing object. Infrastructure failures must not be disguised as a request for the user to re-upload.

## 10. Uncertain outcomes and reconciliation

A successful remote write followed by a lost acknowledgment looks like an exception. A database commit exception can likewise mean either committed or rolled back. Automatically deleting or blindly retrying would guess at the outcome.

| Failure window | Current behavior |
| --- | --- |
| T1 commit unacknowledged | No executable claim; preserve uncertainty; retry the same conflict-aware T1 |
| R1 commit unacknowledged | `UNRESOLVED`, no claim; internal receipt may correlate the proposed attempt |
| PUT raises | Initial and recovery keyed writes are uncertain; preserve state and possible object |
| T2 commit unacknowledged | Preserve object; reconcile authoritative database state |
| Rollback cannot be confirmed | Uncertainty takes precedence over BUSY/retry classification |
| Commit acknowledged, session close fails | Keep known committed result; log resource-cleanup failure |
| T2 pre-commit SQLSTATE `55P03`, `40P01`, `40001`, rollback confirmed | Retryable; preserve PROCESSING/object; no automatic retry |

Statement cancellation `57014` is not in the T2 retryable classification. T1/R1 contention classification is broader; do not infer one universal SQL retry policy. See the detailed [failure contract](06-upload-claim-contract.md).

`reconcile_upload` locks authorization, operation and ordered history before deciding. A missing T1 row is `UNRESOLVED`: SELECT cannot lock absence or exclude an in-flight INSERT. Conflict-aware T1 is the resolution path. A live operation with key-only correlation is `IN_PROGRESS`; reconciliation does not adopt another worker's fence.

An exact current claim or R1 receipt allows current-object verification after the transaction closes. Valid current bytes can proceed directly to fresh fenced T2 without another PUT. Expired or superseded ownership cannot finalize; expired work needs R1 first. Completed state returns authorized replay. R1 receipt reconciliation waits on the same operation lock and can distinguish an absent proposed attempt from an older/superseded one under retained history.

Internal outcomes are `COMPLETED`, `IN_PROGRESS`, `SOURCE_REQUIRED`, `STALE`, `UNRESOLVED` and `RECOVERABLE`; the reason selects the next action. For example, RECOVERABLE may require takeover or mean a confirmed retryable T2 rollback. It is not permission to execute arbitrary storage work.

Reconciliation is an explicit service API, not an automatic HTTP retry, public status endpoint or scheduler. Public responses never contain claims, tokens, receipts or storage keys. After process loss, a normal same-key HTTP retry may wait for expiry and then recover with the request body.

## 11. Cleanup, stale workers and orphan visibility

Different generations use different keys. A delayed old PUT cannot overwrite the new generation's key, and an old DELETE cannot remove that new key. It can still recreate an orphan at the old key. Fencing prevents that old worker from completing the logical result; it cannot cancel remote I/O.

The initial fenced upload path retains narrow compensation for known non-retryable pre-commit T2 failures. A separate transaction rechecks ownership/fence/lease and absence of a version reference, marks FAILED, and must commit before deleting that attempt's key. A concurrent completed T2 prevents this reservation; FAILED prevents a later conforming T2. Uncertain outcomes, retryable errors and stale/expired/revoked workers do not authorize cleanup. Cleanup failure preserves the original error.

Verified recovery and reconciliation perform no deletion. `report_orphan_candidates` is a database-only, read-only advisory snapshot, using locks for consistent inspection:

- `referenced_preserve`
- `superseded_possible_orphan`
- `failed_possible_orphan`
- `current_or_inconsistent_unresolved`

Every entry has `existence=unknown` and `deletion_authorized=false`. No bucket listing or GET proves object existence here. An unreferenced key can still hold a recovery source or receive a delayed PUT. Automatic orphan deletion and a retention policy are deliberately absent; this is distinct from the narrow initial-upload compensation above.

## 12. HTTP contract and practical retries

Example from a configured local application, using an existing valid JWT and active tenant membership:

```bash
curl -i "http://127.0.0.1:8000/tenants/${TENANT_ID}/documents/upload" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H 'Idempotency-Key: handbook-upload-001' \
  -F 'file=@handbook.pdf;filename=handbook.pdf;type=application/pdf'
```

Repeat with the same tenant, requester, key, bytes and filename for replay. Changing bytes or filename under that key returns conflict. Omit the header to exercise F01. Do not use a new key merely to escape uncertainty: that requests a different logical upload.

Success remains HTTP 200 with `status: "uploaded"`, `document_id`, `version_id`, `tenant_id`, `filename` and `size_bytes`. A successful replay returns the same canonical IDs.

Keyed application errors have shape `{"detail":{"code":"in_progress"}}`. Mapping is by enum/reason code, never exception-message parsing:

| HTTP | `detail.code` | Interpretation |
| --- | --- | --- |
| 400 | `invalid_request` | Invalid key or keyed input validation |
| 403 | `forbidden` | Application authorization rejection |
| 409 | `in_progress` | Live owner; retry later with same request |
| 409 | `conflict` | Same key with different request metadata |
| 409 | `terminal` | FAILED operation; no automatic resurrection |
| 409 | `source_required` | Recovery needs valid original bytes |
| 409 | `recovery_required` | Ownership must be recovered/rechecked |
| 413 | `too_large` | Keyed file-size validation |
| 503 | `unresolved` | Unknown outcome or recovery infrastructure/read failure |
| 503 | `retryable` | Typed retryable database/contention outcome |
| 500 | `internal_error` | Invalid durable result/legacy state or unexpected internal failure |

`in_progress`, `unresolved` and `retryable` include `Retry-After: 1`. This is a hint, not a completion deadline. The application normally consumes T1's recovery-required operation reference itself; the mapping also covers later stale/expired decisions.

JWT/dependency 401/403, malformed multipart/UUID or missing-field validation, and the outer body-limit response retain framework/auth-specific shapes. Not every endpoint error uses `detail.code`. The public endpoint still requires a PDF body; SOURCE_REQUIRED and bodyless historical recovery are mainly explicit service workflows, not a separate HTTP recovery endpoint.

## 13. Testing and reproducible commands

### What the evidence covers

| Layer | Evidence and boundary |
| --- | --- |
| Unit/metadata tests | Determinism, same-length changed bytes, changed title, length-prefix boundaries, cursor restoration, size mismatch, fixed v1 golden vector; schema constraints and typed outcomes |
| PostgreSQL + fake storage | Independent sessions/backend PIDs, observed lock blocking, winner commit/rollback, expiry, authorization, stale fencing, recovery, delayed writes/deletes, cleanup and uncertainty injection |
| Real PostgreSQL + MinIO | Signed JWT/multipart API, bytes/hash/size/key persistence, replay/conflict/concurrency, authorization, F01, fresh-key historical recovery, real missing/access-denied reads |
| Fault wrappers over real services | Exception after actual PUT; interrupted/timeout read after opening real GET; commit wrappers distinguishing committed and rolled-back outcomes |
| Process/TCP checks | Child process exits after T1, after PUT, immediately before/after T2 commit; real uvicorn listener, actual generated PDF, client disconnect after PUT before T2 |

The real-storage wrapper checks `pg_stat_activity` before keyed storage calls to detect active database transactions; F01 explicitly opts out because it retains its original transaction policy. PostgreSQL/fake-storage tests also cover auth-session closure and event-loop responsiveness with blocked storage.

Most real-service API cases use ASGI TestClient with the actual router/authentication and disposable database, not the full production application startup. One test uses a TCP listener with lifespan disabled. Its disconnect case completed the durable operation after the client closed; this is an observation for that controlled phase, not a guarantee for all ASGI cancellation paths.

The real-service tests are in `tests/test_upload_minio_e2e.py`. Wrapper exceptions are deterministic fault injection, **not** actual network partitions or socket loss during PostgreSQL COMMIT. Boundary process exits do not establish behavior at every instant inside a remote commit or multipart transfer.

### Disposable infrastructure

Run from the repository root with the existing `.venv` dependencies installed. Configure a local `TEST_DATABASE_URL` accepted by `app/config.py`, distinct from `DATABASE_URL`, and a local MinIO endpoint with the storage settings required by `services/storage_factory.py`: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`, `MINIO_REGION`. Do not paste credentials into documentation or logs.

The PostgreSQL fixture requires permission to create/drop databases. It creates a unique `rag_claim_verify_*_test` database, verifies its identity, migrates **that database only** to `7b9c2d4e6f80`, and drops it on teardown. The configured test database supplies the connection for creating the disposable database; it is not reset.

The MinIO fixture requires a loopback endpoint and creates a unique `rag-f02-e2e-*` bucket distinct from the configured bucket. Teardown removes only objects in that new bucket and the bucket itself. No development reset or manual migration command is needed for these tests. Fixture teardown is test-resource cleanup, not application orphan deletion.

Real-service suite:

```bash
RUN_REAL_MINIO_E2E=1 RUN_DISPOSABLE_UPLOAD_CLAIMS=1 \
PYTHONPATH=levels/level-4-production-rag \
.venv/bin/python -m pytest -q --tb=short \
  levels/level-4-production-rag/tests/test_upload_minio_e2e.py
```

Combined relevant suite matching the recorded **319 passed, 1 warning in 14.26s** evidence:

```bash
level4=levels/level-4-production-rag
RUN_REAL_MINIO_E2E=1 RUN_DISPOSABLE_UPLOAD_CLAIMS=1 PYTHONPATH="$level4" \
.venv/bin/python -m pytest -q --tb=short \
  "$level4/tests/test_upload_minio_e2e.py" \
  "$level4/tests/test_keyed_upload_router_postgres.py" \
  "$level4/tests/test_upload_contract_postgres.py" \
  "$level4/tests/test_upload_http_contract.py" \
  "$level4/tests/test_upload_reconciliation_postgres.py" \
  "$level4/tests/test_verified_recovery_postgres.py" \
  "$level4/tests/test_upload_recovery_postgres.py" \
  "$level4/tests/test_fenced_upload_postgres.py" \
  "$level4/tests/test_upload_claim_postgres.py" \
  "$level4/tests/test_upload_idempotency.py" \
  "$level4/tests/test_upload_metadata.py" \
  "$level4/tests/test_document_upload_service.py" \
  "$level4/tests/test_document_storage.py" \
  "$level4/tests/test_minio_storage.py" \
  "$level4/tests/test_upload_validator.py"
```

The warning concerns Starlette TestClient's deprecated AnyIO BlockingPortal alias. This selected suite is not every repository test. Opt-in tests skip without their flags; a green run containing skips is not real-service evidence. The fixture's explicit short boto3 timeouts/retry settings are test configuration, not proof of equivalent production adapter settings.

## 14. Debugging without guessing the outcome

| Symptom | Check / next action |
| --- | --- |
| PROCESSING persists | Inspect authorized durable status, current generation and database-time lease; it may represent live work, lost acknowledgment or a crash. No scheduler advances it automatically. |
| 409 `in_progress` | Retry the same request after the hint; do not mutate metadata or manufacture a claim. |
| 409 `conflict` | Compare exact filename, byte count and content; changing title alone is enough. |
| SOURCE_REQUIRED | Supply original matching bytes or investigate missing/corrupt persisted candidates. Missing now does not exclude a delayed PUT. |
| Stale token/generation | Discard that worker's execution authority. Resolve current state; never change the database token to make an old claim pass. |
| 503 `unresolved` | Preserve objects. Reconcile using authoritative state and any internal correlation; do not assume rollback or delete by key. |
| 503 `retryable` | Diagnose contention/database availability; retry with fresh checks. It does not authorize bypassing lease expiry. |
| Completed result unavailable | Investigate canonical history, ownership, deletion, READY status and exact key. Do not return IDs merely because status says COMPLETED. |
| Recovery access/read failure | Check storage credentials, endpoint, bucket and service health; do not relabel infrastructure failure as missing source. |
| Session-close failure after success | Treat commit as known; investigate resource leakage separately. |

Reconciliation diagnostics record stage, exception type and operation/attempt correlation without exception strings or tracebacks. Public errors do not disclose fencing tokens, object keys or backend exceptions. Other service cleanup logging still needs an operational logging review; this is not a claim that every log path is fully sanitized.

## 15. Earlier documentation versus current behavior

The documentation is a learning sequence, not seven interchangeable current API specifications:

- [01](01-api-foundation.md) and the original README checkpoint describe 16 embedding/API tests and early setup/factory issues. Current `app/config.py` loads the Level 4 `.env`; the earlier statement that it does not is historical.
- [02](02-architecture-and-capacity-plan.md) includes intended ingestion/capacity designs. Upload recovery does not implement the entire plan or validate its capacity targets.
- [03](03-document-access-and-versioning.md) and [04](04-security-transactions-and-observability.md) establish access/version/publication and JWT/transaction foundations. Statements about future document HTTP integration predate the current upload route.
- [05](05-secure-pdf-upload-validation.md) correctly records its validation-only checkpoint, but its `status: validated`, no-persistence status and future storage milestones are superseded by F01/F02. Current success is `status: uploaded` with result IDs; ingestion remains absent.
- [06](06-upload-claim-contract.md) contains stage-local statements that router integration, current-object inspection or live MinIO verification are deferred. Later stages and this guide supersede those statements. Renewal and background scheduling remain deferred.

Earlier measurements remain attributed to their original checkpoint. They are not silently replaced with the F02 test count.

## 16. Limitations, lessons and next steps

The implemented guarantee is coordinated logical completion for a tenant/key under the service protocol. It is **not exactly-once execution**: repeated physical PUTs, delayed writes and orphan objects remain possible.

Remaining work includes:

- A recovery scheduler, bounded retries/backoff, lease-renewal policy and operational status tooling. Explicit services exist; unattended progress is not promised.
- Attempt/key retention and conservative garbage collection. History currently grows and is locked/validated in full; arbitrary pruning breaks recovery checks.
- Real network partitions, mid-COMMIT connection loss, long storage stalls, multipart interruption, server restart/failover, proxy behavior and broader disconnect phases.
- Production storage/pool timeouts, admission control, rate/tenant quotas, disk-spool budgets, metrics and alerts. Per-file bounds do not bound aggregate concurrency.
- Deep PDF parsing, malware scanning and isolated ingestion. A matching header and digest establish byte identity, not document safety.
- Object immutability/access policy and protection against out-of-band changes. Reconciliation verifies bytes before T2, but another privileged writer could later alter an object; normal replay checks database result integrity only.
- Full application startup/deployment tests, backups/cross-store restoration, and load measurements. Local E2E counts do not establish production readiness.

The central lessons are practical: keep identity separate from physical attempts, commit ownership before I/O, recheck authority after I/O, and preserve evidence when the outcome is uncertain. F02 now has an HTTP path and explicit recovery tools to test those boundaries; the next milestone must supply the operational policies around them.
