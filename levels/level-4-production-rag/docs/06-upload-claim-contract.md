# Upload claim and execution contract — bounded router integration

> This document records contracts in implementation order. Stage-local statements about deferred router, recovery or real MinIO work are superseded by later sections and [07 — Idempotent PDF Upload and Recovery](07-idempotent-upload-and-recovery.md), the current end-to-end guide. Background scheduling and lease renewal remain deferred.

Use `create_claim_session_factory(engine)` for independent claim sessions. It
sets READ COMMITTED on a dedicated option engine sharing the existing pool;
other session factories retain their isolation configuration. The service also
checks the effective isolation before doing authorization or claim writes.

T1 locks active authorization rows, then the operation. It commits the operation
and attempt together before returning a claim, and closes the session. Existing
operations and attempt identities are never rewritten by claim/replay decisions.
Commit uncertainty survives rollback/close failures; secondary failures are logged.
No storage action is authorized by an uncertain commit or a non-CLAIMED decision.

## Expiry policy

A lease is time-limited, not a permanent capability. After flushing T1, the service
samples PostgreSQL time and computes a conservative local monotonic deadline.
Time in commit and session closure counts against it. If the deadline is reached
before return, T1 remains committed but the result is RECOVERY_REQUIRED with no
claim. It does not delete, renew, take over, or retry the operation.

A pause after this check can still expire a returned claim. Stage 2 must recheck
current operation/attempt identity, active authorization, status, token,
generation and database-time expiry in a short transaction before initiating
storage. An expired claim must not start storage; return recovery-required.
Close that transaction before I/O. This check is not a reservation against future
expiry and is not itself T2 fencing.

T2 uses the same lock order: authorization, operation,
then attempt/result rows. Re-read authoritative data, match the operation's token
and generation to the caller and selected attempt, verify reserved result IDs,
object key and expected content, and require an unexpired lease using PostgreSQL
time at the final conditional completion update. Complete document, version and
operation atomically. Lease expiration after that successful guarded update does
not undo the transaction; operation locking orders a competing takeover after it.

If the lease expired before the guarded update, reject finalization even if the
PDF upload succeeded. Preserve the attempt object for recovery; do not delete it
on an uncertain outcome. A successful upload does not renew a lease. Renewal and
expired-lease takeover are explicit protocols, not implicit retry actions. Stage 3B
implements only expired PROCESSING ownership takeover; renewal remains deferred.

## Remaining boundaries

Storage preflight, execution and T2 are implemented in `fenced_upload_service.py`.
The router remains unchanged. Renewal and recovery workers are not implemented. PostgreSQL locks and statement timeouts do not bound
connection acquisition or every client-network stall. Time sampling is conservative
for ordinary elapsed time, but a database clock adjustment still requires the
fresh authoritative checks at preflight and T2. Trusted callers must supply
verified identity and the fingerprint of the exact validated bytes to be stored.

## Stage 2 API and transaction boundaries

`execute_claimed_upload` accepts a committed T1 claim, authenticated tenant/user,
validated request fingerprint/title, source stream, storage and session factory.
It takes a private bounded snapshot, checks its fingerprint and PDF signature,
then runs a fresh preflight transaction. Preflight loads authorization, operation
and attempt under locks, checks the authoritative identity/metadata/fence/lease,
and closes the transaction before any storage call. A matching completed result
is replayed without re-uploading. The T1 dataclass is never authority by itself.

Storage uses the reserved attempt key. T2 rechecks all invariants and creates the
reserved document and READY version, then conditionally sets COMPLETED and its
exact references in the same transaction. It does not publish an active version.
Concurrent finalizers serialize on the operation row; later callers replay the
same authorized result. Multiple physical writes of identical snapshotted bytes
are possible; this is one logical result, not exactly-once storage execution.

## Safe compensation and terminal failure

A non-retryable confirmed pre-commit T2 rollback attempts a third short
transaction. It rechecks authorization/fencing/expiry and absence of a version
referencing the key, and conditionally marks the operation FAILED. Only after
that commit is acknowledged does deletion run, with no open DB transaction.
FAILED is terminal for this attempt: no caller may finalize it or reset it to
PROCESSING while deletion could still be in flight. Stage 3B never resurrects
FAILED operations. Only expired PROCESSING operations can receive a new attempt/key.

If a concurrent T2 already completed, cleanup observes COMPLETED and does not
delete. If cleanup wins, the concurrent T2 is rejected. A late storage write can
still recreate an orphan after deletion; it cannot become a committed result.
Reconciliation remains necessary. This trades availability of competing callers
for protection against deleting a committed result, without long-lived locks.

Stale/expired/revoked attempts, uncertain commit or rollback outcomes, and cleanup
failures preserve objects. A failed cleanup reservation never authorizes deletion.
Original upload errors survive cleanup errors. Recovery and all future writers
must obey the terminal-failure and fencing rules; arbitrary SQL writers are not
protected by this application protocol. No schema/migration changes were needed.

## Stage 3A failure and lease contract

Preflight samples PostgreSQL time after loading authoritative state and returns a
conservative monotonic deadline. Sampling starts before the database round trip.
Commit and session-close time consume that budget. Immediately before storage,
a known-expired deadline raises UploadRejected(LEASE_EXPIRED) without writing or
deleting an object. A pause after the check remains possible: the final T2
database-time fence is still authoritative. No renewal or takeover is implicit.

UploadRejected.reason is a RejectionReason enum: AUTHORIZATION_DENIED,
LEASE_EXPIRED, STALE_FENCE (token/generation or missing attempt),
METADATA_MISMATCH, TERMINAL_OPERATION, RESULT_UNAVAILABLE, or LEGACY_UNRESOLVED.
These are internal decisions, not public HTTP messages. Existing ClaimOutcome
values remain the structured T1 API. No result is exposed by a rejection.

T2 errors with PostgreSQL SQLSTATE 55P03 (lock timeout/unavailable), 40P01
(deadlock), or 40001 (serialization failure) raise UploadRetryable only when
they occur before commit starts and rollback returns successfully. This preserves
PROCESSING, immutable metadata and the object; it never reserves cleanup.
The service does not automatically retry. A caller may invoke the same claimed
execution again, which takes fresh authorization/fence/lease checks and may
re-upload identical bytes. A bounded T2-only retry API is not implemented.
Expired claims require explicit recovery, not renewal by retry.

Unknown errors retain the existing known-failure compensation policy. SQLSTATE
57014 (query cancellation, including statement timeout) is not classified as
retryable because it can also represent intentional cancellation.
A commit exception is always UploadCommitUncertain, even if it contains a
normally retryable SQLSTATE. No automatic retry or deletion follows it.
A failed rollback before commit produces UploadRollbackUncertain, taking
precedence over retry classification. Both require reconciliation.
Secondary rollback/close failures never replace the primary uncertain outcome.

After commit returns successfully, a session-close exception is logged and the
known committed result is retained, in T1, preflight, T2 and cleanup reservation.
It is not commit uncertainty. Preflight/T1 still check the elapsed lease budget.
A close failure can indicate resource leakage requiring operational attention;
it does not authorize changing a known database outcome.

Tests coordinate overlapping T2 transactions using independent backend PIDs,
observe pg_blocking_pids before releasing the winner, and exercise both commit
and confirmed rollback. Storage remains outside database transactions. MinIO object verification and background scheduling remain deferred.

## Stage 3B: expired PROCESSING ownership and R1 reconciliation

Only recover_upload in upload_recovery_service.py implements R1. It uses a fresh
dedicated READ COMMITTED session through the existing transaction helper, with
1s lock and 5s statement timeouts. No storage call or implicit retry is performed.

Lock order is the same authorization group as T1/T2 (active User, Tenant and
Membership), then the tenant-scoped operation FOR UPDATE, then all attempt rows
FOR UPDATE ordered by generation and ID. PostgreSQL time is sampled only after
these locks. Candidate discovery must not hold an operation lock before entering
this protocol. There is no scanner in this batch.

Only the original active requester may take over. A completed operation replays
only after checking canonical result IDs, tenant/owner, deletion status, READY
version and the current attempt's exact key. FAILED is terminal. Legacy metadata
or inconsistent history produces a stable non-executable decision. Valid live
PROCESSING returns IN_PROGRESS without mutation.

History must start at generation 1, be contiguous through the current operation
generation, share canonical reserved IDs and immutable digest/size, and use exact
attempt-specific namespaces. The latest token must match the operation. The
stored request fingerprint is validated against stored version/title/size/digest.
Processing operations must not already have reserved result rows. Retain all
attempt history: recovery currently locks and validates it in full.

An expired valid operation stays PROCESSING. R1 increments its generation, sets
a fresh token and expiry and inserts exactly one new attempt with the original
reserved document/version IDs, original size/digest, and a fresh attempt-specific
key. Previous attempts and request metadata are never edited. The operation lock
serializes competing recoveries; a waiter observes the winner's live lease and
returns IN_PROGRESS. If that new lease has already expired, a subsequent takeover
is legitimate and fences the earlier generation.

CLAIMED is returned only after acknowledged commit and session closure, subject
to a conservative monotonic deadline including commit/close time. EXPIRED never
includes an executable claim. The downstream fenced service must still perform
fresh preflight and final T2 checks.

A commit exception or unconfirmed rollback returns UNRESOLVED with no claim.
When available, a RecoveryReceipt holds only the proposed operation ID, attempt
ID, generation and token; it is correlation data, never storage authority.
Pass it back as receipt to recover_upload for read-only reconciliation. This
mode uses the SAME authorization/operation/history locks and never creates an
attempt. The operation lock waits for an in-flight R1 to resolve:
- Exact current, live attempt: CLAIMED reconstructed from authoritative rows.
- Exact attempt absent: NOT_COMMITTED; an explicit subsequent recovery is allowed.
- Existing older attempt: SUPERSEDED.
- Exact current attempt expired: EXPIRED.
- Completed/failed/unauthorized/inconsistent state: the corresponding stable decision.
- Lock timeout: BUSY, not evidence of rollback. Commit/rollback uncertainty:
  UNRESOLVED again.

Absence is conclusive only under this locking protocol and retained history;
an unlocked read is not reconciliation. A forged/mismatched receipt never bypasses
authorization or fences. Reconciliation of a completed operation can return its
authorized replay regardless of which generation's receipt was supplied.
Concurrent reconciliations may return the same existing claim, not distinct
ownership generations; duplicate execution remains governed by fenced T2.

Connection acquisition and network stalls are not bounded by SQL timeouts.
No lease renewal, source-byte recovery, cleanup, retention, scheduler, MinIO or
router integration is included. Attempt history growth and shared private helper
coupling remain follow-up concerns. No schema or applied migration changes.

## Stage 3C: verified source recovery and fenced publication

execute_recovery_upload in verified_recovery_service.py accepts a current claim,
authenticated tenant/requester, immutable fingerprint/title and optional retry
body. It does not claim ownership or create attempts. Before any object access,
a short transaction validates authorization, operation and complete attempt history
in R1 lock order, then checks the supplied claim through the fenced loader.
Candidate keys come exclusively from older persisted attempts of that same
operation/tenant, newest first. A valid completed result replays without storage.

The caller's retry body is preferred if valid; its position is restored and it
remains caller-owned. An invalid body falls back to historical objects. Read
errors are not invalid-content evidence and stop execution. Object streams are
closed on success, corruption and exceptions. Verification uses a private spool
(1 MiB in-memory threshold, existing upload size limit), reads at most expected
size plus one byte, and checks exact size, PDF signature and the full versioned
fingerprint including SHA-256. ETags and object metadata are not digest evidence.
A verified snapshot, never an unverified server-side copy, supplies the new PUT.

ObjectMissing is emitted by MinIOStorage.open only for explicit NoSuchKey.
NoSuchBucket and generic 404 remain infrastructure errors. AccessDenied and
credential/signature denial codes become ObjectAccessDenied. Recovery distinguishes:
- Missing or corrupt candidates: continue searching; if none valid, SOURCE_REQUIRED
  with missing/corrupted counts and no new attempt or operation transition.
- Access failure: RecoveryReadFailure(ACCESS_DENIED).
- Other open failure: RecoveryReadFailure(UNAVAILABLE).
- Read or stream-close failure: RecoveryReadFailure(INTERRUPTED).
Infrastructure failures stop the search, never masquerading as SOURCE_REQUIRED.

All GET/read/close/PUT work happens after database transactions have closed.
After verification, hardened preflight rechecks authorization, ownership and lease;
its monotonic deadline includes commit/close time. PUT uses only the current
attempt key. Existing fenced T2 creates the canonical result atomically; it does
not publish an older attempt key. The final database fence remains authoritative
if expiry, revocation or takeover occurs during storage.

Stage 3C performs no deletion or failure reservation. Any PUT exception raises
RecoveryWriteUncertain because bytes may have been written remotely. T2 retryable
errors, rejection, rollback/commit uncertainty and other T2 errors all preserve
objects. PROCESSING remains unchanged on confirmed T2 rollback. No automatic
retry is performed. F01 compensation is unchanged. Integration hardening makes initial keyed PUT
exceptions uncertain too; known T2 rollback compensation remains available.
A later authorized invocation can retry using supplied bytes or historical bytes;
this stage deliberately does not inspect the current attempt object to reconcile
a PUT. That optimization and background reconciliation remain deferred.

Different generations use different keys. A delayed old DELETE cannot delete the
new published key; a late old PUT may recreate an orphan but cannot pass current
T2 fencing. All writers/cleanup implementations must respect persisted key
ownership. Tests use fake storage and real disposable PostgreSQL; live MinIO
network/multipart behavior is not verified by this suite.

No router, scheduler, schema, migration or F01 changes. Blocking storage reads
still rely on adapter/network timeouts, and long histories can require many
candidate GETs. No lease renewal, garbage collection or retry backoff is added.

## Stage 3D: conservative reconciliation and orphan visibility

upload_reconciliation_service.py adds reconcile_upload and
report_orphan_candidates. Neither acquires a generation, renews leases, performs
PUT/DELETE, creates attempts, or schedules work. Both require authenticated active
original-requester access and dedicated READ COMMITTED sessions with the existing
bounded transaction helper.

Reconciliation looks up the tenant/idempotency key under authorization locks,
then locks the operation and ordered attempt history. Supplied request metadata
must match the durable fingerprint/title/size/digest. An absent row is UNRESOLVED
(absence_not_proven): PostgreSQL SELECT FOR UPDATE cannot lock a missing row or
exclude an in-flight initial INSERT. Retry the original conflict-aware T1 claim
to resolve that case; do not infer rollback or authorize storage from absence.
A present live operation without a claim/receipt returns IN_PROGRESS, never an
adopted fence. Completed results return only validated authorized replay.

An exact claim or R1 receipt permits current-object reconciliation. The operation
lock waits for any prior R1/T2 transaction to finish. A missing receipt attempt
under this lock returns RECOVERABLE (r1_not_committed), without creating anything.
A superseded/invalid fence is STALE. Expired ownership requires explicit Stage 3B
takeover, not finalization. FAILED, legacy/inconsistent records, invalid results
and denied access remain non-executable UNRESOLVED outcomes with internal reasons.

After the inspection transaction closes, GET the exact persisted current key and
use the Stage 3C bounded size/digest/PDF verifier. Close the object stream on all
paths. No database transaction spans GET/read/close. A valid current object can
proceed directly to fresh fenced T2, without a PUT. T2 revalidates authorization,
token, generation, status, canonical identity and database-time lease expiry.
It creates document/version and completes the operation in one transaction.

Outcomes:
- COMPLETED: validated durable replay or verified current object finalized by T2.
- IN_PROGRESS: live operation, but no exact ownership correlation supplied.
- SOURCE_REQUIRED: current object missing now or corrupt; late PUT is still possible.
- STALE: supplied ownership changed, or authorization/fence/lease was lost at T2.
- RECOVERABLE: expired ownership, R1 attempt proven absent under lock, or confirmed
  retryable T2 rollback; the reason determines the next explicit action.
- UNRESOLVED: missing T1 row, access/infrastructure/read errors, invalid durable
  state, contention, or uncertain commit/rollback. Never delete or assume failure.

Storage access denial, unavailable/timeout, interrupted read/close, and missing
object have distinct reason codes. T2 commit/rollback uncertainty preserves every
object and can be reconciled on a subsequent call. No automatic retry occurs.

Orphan reports are database-only advisory snapshots. They lock authorization,
operation and ordered attempts and check DocumentVersion references by key.
Entries are referenced_preserve, superseded_possible_orphan,
failed_possible_orphan, or current_or_inconsistent_unresolved. Every entry has
existence=unknown and deletion_authorized=false. Reports do not GET/list objects,
prove physical existence/absence, prove writer quiescence, or grant cleanup
authority. Referenced keys are always marked preserve. Unreferenced entries may
be recovery sources, in-flight writes or absent objects, and a later PUT can
recreate an object. Retained attempt history is required; unknown bucket objects
not represented by attempts are outside this report.

Verification followed by T2 relies on all conforming writers using immutable
validated bytes for a given attempt key and cleanup respecting terminal fencing.
It is not an atomic S3/database snapshot: arbitrary external deletion/overwrite
between GET and T2 is not prevented. No object versioning or write-once policy is
introduced. Live MinIO behavior remains untested here; tests use fake streams and
real disposable PostgreSQL. F01, router, scheduler and migrations are unchanged.

## Integration hardening: unwired application contract

ClaimDecision.operation is an OperationReference containing only operation_id.
It is returned on authorized matching RECOVERY_REQUIRED decisions, including T1
whose lease expires during commit/close. It is NOT an executable fence and must
not be treated as authorization. R1 rechecks requester/tenant/state under locks.
No operation reference is exposed by conflicting/unauthorized decisions.

All keyed PUT exceptions now preserve PROCESSING and objects unless the adapter
can prove non-write (no such proof is currently implemented). Initial execution
raises UploadWriteUncertain; RecoveryWriteUncertain subclasses it. The original
exception remains the cause. No automatic retry, cleanup reservation or DELETE
follows these errors. Known non-retryable T2 rollback can still reserve FAILED
and clean up, with its existing terminal fence. F01 remains unchanged.

valid_completed_result in upload_result.py is the shared replay validator used
by T1, fenced T2, recovery and transitively reconciliation. It validates contiguous
history, canonical IDs, expected size/digest, exact attempt namespaces, current
token, result references, tenant/requester ownership, nondeleted document and
READY version with exact key. Legacy/malformed history cannot replay.
Callers acquire authorization and operation locks first. The operation lock
serializes history validation even when a caller already holds its current
attempt lock. No immutable metadata or old attempt is rewritten.

ClaimRollbackUncertain now takes precedence over BUSY. ClaimCommitUncertain
remains primary if commit failed, even if rollback/close also fails.
Reconciliation diagnostics log only stage, exception type, operation/attempt IDs;
they omit raw exception messages, traceback/SQL parameters, keys and credentials.
Legacy, wrong-owner and metadata-conflict reasons are separate.

get_keyed_upload_principal in app/keyed_upload_auth.py is an opt-in synchronous
dependency. It reuses existing JWT/user/membership checks in its own with-session
scope, returns only frozen principal IDs after session closure, and has no yield
dependency. Do NOT also attach get_current_user/get_current_tenant_member or
get_db_session to the future keyed route: that would retain another transaction.
The existing F01 route/dependencies are untouched.

execute_keyed_upload in keyed_upload_application.py defines the unwired async
boundary. It runs one synchronous application workflow in a non-abandoning AnyIO
worker. It accepts engine, storage, frozen principal and exclusively borrowed
upload stream, never a Session or ORM instance. Dedicated READ COMMITTED sessions
are created/closed inside that worker. The caller must await completion before
closing/reusing the stream; do not abandon the worker on disconnect. It validates
metadata/header/size, computes the fingerprint, executes T1, and performs at most
one explicit R1 handoff for an expired retry. No uncertainty is automatically
retried. A future reconciliation/status workflow can call the existing services;
no public route, polling endpoint or scheduler is added here.

upload_http_contract.py maps exact machine outcomes/reasons and exception types
to HttpDecision, without parsing error text. The output contains only an outcome
and optional UploadReplay: no operation reference, token, key, claim or receipt.
COMPLETED=200; malformed request=400; too large=413; forbidden=403; conflict,
in-progress, terminal, source-required and recovery-required=409; uncertainty or
retryable infrastructure=503; invariant/programming/configuration failures=500.
In-progress/uncertain/retryable responses expose retry_after=1 as guidance.
Authentication retains 401/403 from existing checks. Storage access failures are
service failures (503), not client authorization errors. Unrecognized reasons
fail closed to 500. A successful outcome without a valid replay also fails closed.
Tests enumerate the enum maps and reason table. Unknown ValueError is not
automatically classified as client input; the application validates request input
in a specific scope and converts only those validation failures.

Router integration must explicitly serialize this safe result, keep F01 separate,
and use the short-lived dependency and worker boundary. No schema change is
required. Full real HTTP dependency integration, real MinIO failure behavior,
lease renewal, connection/network deadlines and orphan cleanup remain future work.

## Bounded FastAPI router integration

POST /tenants/{tenant_id}/documents/upload accepts optional Idempotency-Key.
Absent header preserves the existing F01 dependency graph, validation, persistence
and 200 response. Present header selects a separate internal FastAPI handler
before dependency resolution. The two handlers share the public path and existing
multipart body limit; there is no additional public recovery/status route.
BoundedUploadRoute dispatches by header presence, not truthiness, so invalid or
empty keys never silently fall back to non-idempotent behavior.

The keyed handler requires exactly one key, 1–255 printable ASCII characters,
excluding whitespace/control characters. Keys are opaque and case-sensitive,
without trimming or normalization. Invalid/duplicate keys return 400. The original
route's optional Header parameter documents support in OpenAPI; internal dispatch
performs the keyed validation and dependency selection.

Only get_keyed_upload_principal runs for keyed requests. Its session closes before
the handler executes, and it derives user/tenant solely from verified RS256 JWT,
active user, membership and tenant checks. The handler passes that frozen principal
to execute_keyed_upload; it accepts no operation ID, fence, token or storage key
from the client. Multipart validation precedes worker execution. The worker hashes
the actual bytes and owns its own READ COMMITTED sessions.

The route awaits the non-abandoning worker before returning. FastAPI's multipart
exit stack then closes UploadFile; no background task borrows the stream. Blocking
database/hash/storage work runs in the worker. F01 retains its original synchronous
behavior and transaction boundaries; the new no-transaction-during-storage
guarantee applies to keyed execution.

Successful upload and replay retain the F01 JSON shape:
status, document_id, version_id, tenant_id, filename, size_bytes.
Typed keyed failures return {"detail": {"code": "<HttpOutcome value>"}}:
400 invalid_request; 413 too_large; 403 forbidden; 409 conflict/in_progress/
terminal/source_required/recovery_required; 503 unresolved/retryable;
500 internal_error. In-progress, unresolved and retryable include Retry-After: 1.
Existing authentication 401/403 and framework multipart errors retain their
standard response format. Error text, object keys and fencing metadata are never
serialized from internal exceptions or decision objects.

Tests mount the actual router with real JWT verification, disposable PostgreSQL
and fake storage. They exercise both dependency graphs, no-key duplicates,
membership/identity rejection, keyed replay and payload/title conflicts, expired
recovery, uncertain PUTs, duplicate/invalid key headers, typed response mapping,
and an unrelated request plus same-key retry while PUT is blocked. Storage checks
pg_stat_activity to ensure keyed auth/claim transactions are closed. UploadFile is
observed open during blocked work and closed after response.

No migration, scheduler, automatic orphan deletion or F01 service change.
Real MinIO E2E remains the next validation step. Lifespan, proxy limits, cancellation
under real ASGI disconnects and boto3 network/multipart failures need deployment-
representative validation; TestClient coverage is not production readiness.
