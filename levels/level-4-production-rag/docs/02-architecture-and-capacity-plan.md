# Level 4 — Document Q&A Architecture and Capacity Plan

Version: 0.3 — 2 November 2026
Status: Ready for the first schema/authorization milestone; remaining contracts are assigned to their implementation gates. No new infrastructure or capacity evidence is provided.

This revision changes the design document only. It does not deploy infrastructure, change application code, or certify production readiness. Infrastructure is introduced in stages; section 5 defines what is deferred.

## 1. Purpose

Build an independently implemented, multi-tenant document Q&A system that demonstrates production engineering: correct authorization, durable asynchronous processing, repeatable indexing, operational visibility, and measured performance.

The portfolio does not need one million real users or a continuously running 100-million-vector deployment. We will distinguish the workload we design for from the workload we actually test. Neither this document nor the current embedding API proves million-user capacity.

Existing checkpoint: embedding API foundation, factory-based service creation, settings, startup/warm-up, input validation, readiness, logs, request IDs, timing, and 16 reported passing tests. No fresh test execution accompanies this plan.

## 2. Version 1 scope

Users belong to organizations (tenants). V1 supports text-based PDFs, upload status, document versions, authorized Q&A, source/page citations, abstention when evidence is insufficient, and document deletion.

Initial API policy: at most 20 MiB and 100 pages per PDF. These are starting limits, not performance guarantees. Parsing also needs an extracted-text budget and worker execution deadline. Image-only PDFs receive a clear unsupported/OCR-required status; scanned-document OCR is deferred.

V1 questions select up to 10 owner-accessible documents within one tenant. Membership alone does not grant document access; section 7 defines the permission matrix. The application does not send one retrieval request per document; it uses an authorized scope filter. Whole-organization search and large document-sharing ACLs are later extensions. The large corpus sizing scenario therefore differs from searching every document for each question.

Use stateless single-turn Q&A first. Conversation history, risk analysis, obligations, reminders, OCR, additional formats, and enterprise identity controls are future work.

Basic authentication, membership checks, document authorization, quotas, safe upload handling and secret management are V1 requirements, not optional future security.

## 3. Workload assumptions versus evidence

| Measurement | Design scenario | Initial validation workload |
| --- | --- | --- |
| Registered users | 1 million | Synthetic accounts across isolated test tenants |
| Daily active users | 100,000 | Simulated traffic; no claim of real active users |
| Questions per active user/day | 10 | Fixed reproducible query mix |
| Questions/day | 1 million, about 11.6 requests/sec averaged across a day | Begin at 1, 5, 10 requests/sec; increase only while healthy |
| Peak arrival rate | 100 requests/sec for 5 minutes, provisional | Measure the maximum sustainable rate on declared hardware |
| Documents | 1 million | Start with 20–50 representative public/synthetic PDFs |
| Average chunks/document | 100, to be measured | Record average, p95 and maximum chunk counts |
| Vectors | 100 million; sensitivity scenarios 150M and 500M | 10K then 100K; 1M only if hardware/time permit |
| New/updated documents/day | 10,000 | Small controlled ingestion batches plus mixed query/ingestion tests |
| Ingestion burst | 100 document jobs/minute for 10 minutes, provisional | Increase gradually and measure queue age and recovery |

At 100 chunks/document, 10,000 fully indexed documents/day creates about one million chunk embeddings/day. Full document updates can repeat that work. Retained old versions, replicas and reindex migrations increase storage beyond the single-active-version estimate.

Concurrency is an observation, not a synonym for user count. At 100 requests/sec and an average 5-second request duration, roughly 500 requests would be in flight in a stable system. This is an illustration, not a measured capacity result.

## 4. Capacity math and cost controls

Raw float32 vector bytes = vector count × dimensions × 4.

| 384-dimensional vectors | Raw size, decimal |
| --- | ---: |
| 10,000 | 15.36 MB |
| 100,000 | 153.6 MB |
| 1 million | 1.536 GB |
| 100 million | 153.6 GB |

These estimates exclude text, metadata, vector indexes, write buffers, replicas, backups, storage fragmentation and old versions. Raw size is not a RAM requirement or a cloud bill.

Local Docker services are the default development deployment. No always-on paid cluster is required. Paid generation is used only for small quality/integration runs with a fixed request/token budget. Large API load tests use a labelled stub inference backend; retrieval tests can use precomputed queries. Real model tests are reported separately.

A cloud demo is optional, short-lived and requires a concrete cost estimate before provisioning. Billing alerts are useful but are not spending caps. Do not create paid resources automatically as part of this plan.

## 5. Architecture decisions

Use a modular FastAPI application plus separately deployable ingestion workers. Split processes where workload and failure isolation justify it; do not create a microservice per Python class.

| Component | V1 decision | Reason and trade-off |
| --- | --- | --- |
| API | Existing FastAPI app, stateless replicas | Reuse completed foundation; shared state lives outside replicas |
| Metadata and jobs | PostgreSQL, first complete slice | Authority for permissions, documents, versions, leases and durable jobs; no broker required to make a job durable |
| Original files | S3-compatible object-storage adapter; local development instance | Independent of API local disk; provider can change without changing ingestion semantics |
| Queue | PostgreSQL job table first; Celery/RabbitMQ deferred to a separate milestone | Fewer moving parts initially; broker milestone must demonstrate additional delivery boundaries rather than claim automatic reliability |
| Vector retrieval | Qdrant server as initial candidate | Independent shared retrieval process; filtered-search benchmark and recovery test are acceptance gates, not assumptions of capacity |
| Cache | Redis, introduced after an uncached baseline | Performance optimization only; avoid making cache the source of truth |
| Embeddings | Existing local all-MiniLM-L6-v2, pinned artifact/config | Low-cost baseline; enforce tokenizer budget and measure quality before changing models |
| Generation | Provider interface with one configurable hosted LLM and test fake | Small paid real runs; model name/context/pricing verified when integrated |
| Observability | Current logs/IDs; add metrics and traces incrementally | Record stage timings, queue lag, error rates, resource use and token cost |
| Deployment | Docker Compose for reproducibility | Local deployment is not high availability; cloud topology stays a separate deployment profile |

### What we build now versus later

| Phase | Infrastructure and behaviour | Explicitly not required yet |
| --- | --- | --- |
| Current task | This design revision only | No infrastructure or code changes |
| First complete working slice | FastAPI, PostgreSQL, one worker process, local object-storage service and one Qdrant server; owner authorization, versioning, deletion and recovery rules | RabbitMQ, Celery, Redis, Kubernetes, replicas and separate embedding servers |
| Messaging milestone | Celery/RabbitMQ plus transactional outbox and delivery/recovery tests | A separate Celery result backend; PostgreSQL remains job-status authority |
| Measured optimization | Add caching, batching improvements and replicas only after a baseline | Automatic assumption that more services improve throughput |
| Scale/deployment experiments | Filtered-search sizing, optional short cloud deployment, restore/load evidence | Continuously running 100M vectors or one million real users |

The first worker claims due PostgreSQL jobs in a short transaction using row locking/skip-locked semantics, records an ownership token and lease, commits, then processes outside that transaction. It does not hold a database row lock while parsing or calling models. Poll intervals, indexes and fairness are measured. This approach is not claimed to have unlimited queue throughput.

Adding a broker changes job transport, not authorization, ownership, manifests, activation or the source of truth. These correctness rules apply from the first slice.

All technology choices require their relevant integration gate. At 100M vectors, sharding/replication, filter selectivity, index memory, ingestion contention and recovery must be evaluated on a suitable environment. A small local Qdrant deployment does not demonstrate that scale.

## 6. Ingestion, immutable uploads and publication

### 6.1 Upload acceptance is not searchable activation

1. Authenticate the owner in an active tenant membership. Reserve an upload slot and bytes atomically in PostgreSQL. Allocate one version and an unguessable staging object key.
2. Upload through a short-lived staging destination. A reusable upload URL must never let the client modify the committed source used by processing.
3. Completion copies a specific staging object version into a service-controlled object key and records its storage version, byte length and server-verified checksum. If the storage cannot pin/read a source version safely, completion must reject rather than silently rely on a mutable key. No client receives write permission or a signed upload URL for the committed key. Pin the exact committed version on worker reads.
4. Completion binds the source using a conditional PostgreSQL transition. In one transaction it marks the version accepted, updates the document's desired generation, creates one unique processing job, and converts the quota reservation to committed usage. In the later broker phase it also inserts one unique outbox event.
5. A duplicate completion for the same completed upload returns its existing version/job without charging quota again. A conflicting payload returns 409. Competing completion requests cannot create multiple jobs. A copy completed before a database failure is an orphan candidate, not a searchable document; reconciliation adopts only a valid matching completion or cleans it up.
6. Initial upload reservation expiry is 30 minutes. Completion and cleanup coordinate on the upload record rather than only checking object references. Before copying bytes, completion conditionally claims OPEN → COMPLETING, recording the copy token, source version, intended destination and deadline in a short committed transaction. It copies outside the database transaction. Final binding is a conditional COMPLETING → COMPLETED transition requiring the same token and no cleanup claim; the source reference, job and quota conversion commit together.
7. Cleanup first conditionally claims an expired OPEN/COMPLETING operation as CLEANUP_CLAIMED and records a cleanup token; only then deletes its exact staging/copy versions. Completion cannot bind CLEANUP_CLAIMED state. If completion commits first, cleanup cannot claim it. Expiry alone does not delete a source. Cleanup retries after crashes and scans for late copies from a stale completion attempt; a unique copy destination/token prevents it from touching a replacement upload. Do not mark physical cleanup complete until the old copy operation has terminated/drained and a final scan passes. No transaction remains open during external copy/delete work.
8. Reusing a staging URL cannot alter the bound committed version. Clean noncurrent staging versions as well as current abandoned objects, using the upload lifecycle guard and safety grace. Keep logical reservations until referenced work is settled; verify the selected object's versioning/copy semantics through race tests.

Successful completion means immutable source reference plus durable database job, not that the document is already searchable. Object size/type checks are necessary but do not replace parser limits, malware policy or format validation.

### 6.2 Retry-safe processing and immutable manifests

The worker claims a job, downloads its exact committed source version, parses with resource limits and preserves page provenance. Image-only or unsupported documents receive a terminal diagnostic status rather than repeated retries.

Use token-aware, initially page-bounded chunks. Starting proposal: 200 tokens with 30-token overlap, subject to verifying the loaded model's actual window including special tokens. Reject unsupported over-window query input instead of silently truncating it.

An immutable processing profile includes model artifact revision, tokenizer revision, dimensions, normalization, distance metric, extraction/chunking configuration and their code/schema versions. The source and profile are frozen for a job. V1 has one serving profile; an attempted configuration change cannot silently alter a retry.

Persist an indexing manifest with the exact expected chunk IDs, content hashes, source pages and profile. Retrying reuses the frozen parsed/chunk artifacts or verifies regenerated artifacts against the manifest. A different manifest requires a new indexing revision; count equality alone is insufficient.

Each lease claim gets a fresh attempt token and a distinct output namespace. Vector IDs incorporate tenant/document/version/index revision/attempt/chunk identity. Chunk hashes are checked against the immutable manifest. Each bounded batch checks ownership before issuing writes. All writes carry the attempt identity, so a paused old worker can only modify its own invisible namespace, not a replacement worker's published output.

Qdrant starts with one collection for the pinned profile and payload indexes for tenant, document, version and publication/attempt identity. Mandatory filters scope searches to authorized active publication IDs. Do not create a collection per document. Verify exact supported filter/index settings when implementing.

Before activation, verify exact manifest identities/hashes/profile, completed write acknowledgements, and search visibility under the actual reader settings. Point existence or a matching count alone does not prove indexed search visibility. A setting that can omit unindexed points is prohibited until its publication visibility condition is explicitly tested. Define the concrete readiness probe for the pinned server/client version before enabling publication.

### 6.3 Latest accepted update wins

The document has separate `desired_version_id`/generation and `active_publication_id`. Version numbers are assigned atomically; the desired target changes only for a successfully accepted upload completion.

Activation is a conditional PostgreSQL transaction. It requires current membership/owner eligibility, the matching desired generation, a non-deleted document, current worker ownership and unexpired lease, and verified manifest publication. Activation swaps the active pointer and records completion together. Activation and membership revocation both lock the same membership row before document/job rows, then recheck eligibility while holding the locks until commit. Both use the same lock order (membership first, document IDs in sorted order, then job) to reduce deadlocks. If revocation wins first, activation fails; if activation wins first, it commits before revocation. Enforce document-generation and claim-token guards in addition to these locks. Never hold them across model/vector-network work.

Example: V3 is accepted while V2 processes. V2 cannot activate afterward, even if it finishes first. If V3 fails, the previously active V1 remains available; retry V3 or explicitly submit a newer update. Do not silently publish superseded V2. If V2 activated before V3 was accepted, it remains the previous active version until V3 succeeds.

Old active output stays searchable until a successful replacement. Initial cleanup policy retains superseded source/version artifacts for seven days; inactive attempt vectors are eligible after the stale-writer cleanup conditions below. This is a configurable portfolio policy, not a legal retention guarantee. A delete overrides normal old-version retention.

Keep separate state machines:

- Document visibility: LIVE or DELETED tombstone, desired generation and active pointer.
- Version processing: UPLOADING, ACCEPTED, PROCESSING, READY, FAILED or SUPERSEDED.
- Job execution: PENDING, RUNNING, RETRY_WAIT, SUCCEEDED, FAILED or CANCELLED, with durable attempts and lease ownership.

### 6.4 Leases do not stop an old process

Heartbeats, completion and activation require the current claim token and valid lease. A lost worker cannot regain authority merely by resuming. A heartbeat after expiry cannot revive its claim. The replacement claim uses a new token and output namespace.

The initial policy permits four total processing claims (initial plus three retries); crashes, expired leases and redelivery-driven new claims count durably. Broker delivery without a successful claim does not increment work. Permanent failures terminate early; retries use backoff/jitter. Exhausted jobs retain a sanitized error and replay history. Manual replay is authorized and recorded, not a silent counter reset.

Tombstones exclude deleted/superseded publications from all queries. Cleanup repeats for late writes and tracks unfinished cleanup. Since an expired lease does not prove a writer is dead, physical purge is not declared complete until the stale worker is stopped/confirmed terminated and in-flight writes have drained, followed by another namespace scan/delete. Otherwise retain the tombstone and report pending cleanup. Test the selected client write deadlines and worker-supervisor termination behaviour; do not equate timeout with cancellation.

### 6.5 Later broker contract

Do not implement RabbitMQ/Celery in the first slice. Before that milestone can pass, specify durable queues, persistent messages, publisher confirms plus unroutable-return handling, late acknowledgement and worker-loss configuration, bounded prefetch, and observed redelivery behaviour for the pinned versions.

A publish confirmation is not proof of processing. The outbox publisher marks an event sent only after the chosen routing/confirmation conditions pass. Lost confirmation can cause duplicate publication; consumers still use database claims. PostgreSQL reconciliation reschedules overdue unfinished jobs even if an outbox row says published. Do not rely solely on Celery retries, acknowledgements or its result backend to recover work.

## 7. Authorization, query visibility and deletion

### 7.1 Simple V1 permission matrix

| Operation | V1 allowed principal |
| --- | --- |
| Create an upload/document | Authenticated user with active membership in the target tenant and available quota |
| Complete upload, inspect status, list/read document, Q&A | Document owner with active membership in that tenant |
| Read citation source or download original | Same owner/membership check as Q&A; no public source URLs |
| Update, retry processing, delete | Same document owner/membership check |
| Other same-tenant user or tenant administrator | No implicit document access in V1; sharing/admin override deferred |
| Background processing | Restricted service identity; operations are bound to the job's tenant/document/version, not an arbitrary caller tenant |

Tenant and owner come from verified identity plus server-side membership records. Composite tenant-consistent database keys/foreign keys prevent versions/jobs referencing documents in another tenant. Object keys/payload filters are derived by the server. Unknown and unauthorized document IDs receive the same document-not-found response; a mixed selection is rejected as a whole without partial answers. If the authorization database is unavailable, fail closed with a generic 503; do not fall back to cached permissions or unfiltered retrieval.

Membership revocation affects operations authorized after the revocation transaction commits. Background jobs for a revoked owner cannot activate; they become cancelled or blocked according to the durable state transition. Ownership transfer is outside V1.

### 7.2 Query steps

1. Validate identity and quotas. Resolve membership, ownership, document visibility and all requested active publications/profiles in one joined SQL statement, using one statement snapshot. Verify that every distinct requested document is present; never combine an earlier membership read with a later publication read under default isolation. The statement snapshot, not transaction completion, defines authorization visibility. Before returning the result to inference/retrieval code, register bounded read leases using the shared lock protocol in section 7.4. If cleanup/visibility changes prevent safe registration, discard the result and reauthorize instead of proceeding without a pin.
2. A document with no active publication is not ready. Reject the selection with 409 rather than silently omit it. Up to 10 documents are allowed; excessive selections receive validation failure.
3. Embed the question with the pinned serving profile. Mixed profiles are rejected; online model migrations are deferred. Enforce tokenizer limits, not only the 2,000-character ceiling.
4. Retrieve with mandatory tenant and allowed publication filters. Check returned tenant/document/publication IDs match the authorized snapshot before constructing context; never rely on post-filtering alone.
5. Build bounded context with immutable source/page/chunk identities. Empty retrieval returns an explicit insufficient-evidence result without generation.
6. Generate a bounded, non-streamed answer treating document text as untrusted data. Require citations drawn from supplied evidence and abstention when evidence is insufficient.
7. Buffer the full answer, validate schema and citation identifiers, then return it. Invalid citations produce an explicit unable-to-validate result, not an unchecked answer. Identifier validity does not prove claim support; evaluate support separately. No automatic second generation call in V1.

V1 returns the answer after validation, not token streaming. Remove the earlier three-second first-token promise. Streaming and its provisional/final validation protocol require a later design decision.

### 7.3 Visibility and deletion contract

The single authorization statement's snapshot is the request's visibility boundary; a transaction alone does not imply a consistent multi-statement snapshot. A request authorized before an update/delete/revocation commits may complete using its pinned publication only within its registered read deadline. Requests authorized afterward must obey the new state. This is an explicit V1 policy, not instantaneous cancellation of in-flight work.

Deletion locks/conditionally updates the same document generation used by activation: set a tombstone, clear the active/desired publication targets, invalidate generation, cancel pending jobs and schedule durable cleanup in one transaction. An activation cannot resurrect the tombstoned document. Existing request artifacts cannot be physically removed while pinned reads require them.

In V1 download originals through an authorized server endpoint rather than releasing long-lived object-store URLs. An already-authorized download may finish. If direct signed downloads are later introduced, their expiry/revocation exposure must be documented before release.

A separate durable deletion ledger records document/generation tombstones for recovery. A separate deletion-operation record has states DELETION_PENDING, LEDGER_DURABLE, PURGING and PURGED; the document visibility becomes DELETED immediately and stays distinct from that operation status. A deletion operation remains DELETION_PENDING until its ledger record is durably persisted outside the PostgreSQL rollback boundary; only then acknowledge the deletion as committed to the caller. Failures remain hidden and retryable, not falsely reported as fully purged. See restore rules below for reconciling both stores and retaining this history.

### 7.4 Bounded readers and cleanup coordination

Use PostgreSQL read-lease records for the first slice so API and cleanup worker processes share the same protection. Begin a short READ COMMITTED transaction: lock the current membership row, then requested document rows in sorted order; run the single joined authorization statement after acquiring those locks; insert publication/object read leases before committing. Cleanup and visibility mutations use the same document-row locking protocol. Cleanup cannot claim artifacts with live read leases; once an artifact is CLEANUP_CLAIMED it cannot receive a new lease. Thus snapshot authorization and pin registration are coordinated rather than two unrelated reads.

Initial nonrenewable lifetime: 60 seconds from authorization for Q&A storage access, and 120 seconds for an original download. A Q&A request materializes and verifies its context while the lease is valid, then releases the storage lease before calling the LLM; generation no longer needs vector/object access. Access after expiry is forbidden. Do not start a new storage operation if its remaining lease cannot cover the configured operation deadline. A stalled download is cancelled/closed at its deadline; unlimited completion is not promised.

Expiry bounds logical access, but does not prove an issued network read has stopped. Physical cleanup waits for expired readers' bounded operations to drain or the owning process to be confirmed terminated, then rechecks under the cleanup guard. Configure/test storage deadlines and process termination; if reader termination cannot be established, retain artifacts and report cleanup pending. On API crash, recorded leases remain until expiry and recovery verifies the dead reader before purge. Never hold a database transaction open while downloading or generating.

## 8. Resource protection, security and implementation fixes

### 8.1 Initial configurable development limits

These are conservative policy starting points, not throughput claims. Benchmark and revise them explicitly.

| Resource | Initial policy |
| --- | --- |
| File | 20 MiB, 100 pages; reject encrypted/unsupported PDFs |
| Tenant queued/running work | At most 5 outstanding document jobs and 200 MiB outstanding upload reservations |
| Retained originals | Initially 100 live documents and 1 GiB committed original/version bytes per tenant; retained and failed-version originals count until verified purge |
| Indexed/derived data | Initially 100,000 reserved/retained chunk points per tenant; count all attempt namespaces, not only active points; separately measure actual vector/artifact disk bytes |
| Global disk admission | Pause new uploads/claims when any required data volume has less than max(5 GiB, 15% of capacity) free; reserve operational headroom and report the limiting volume |
| Extraction | At most 2 million extracted characters and 5,000 chunks per version |
| Parser worker | Isolated subprocess, 60-second wall deadline and 512 MiB memory cap; verify OS/container enforcement |
| Embeddings | One active batch per worker, batch size 16 initially; start one ingestion worker |
| Q&A | At most 2 in-flight requests per tenant, 4 process-wide and 10 selected documents |
| Model budgets | Query fits embedding tokenizer window; context ≤4,000 generation-model tokens; output ≤512 tokens |
| Deadlines | Embedding batch 30 sec, retrieval 2 sec, generation 30 sec, complete job 10 min; timeout alone does not stop computation |
| Paid demonstration | Maximum 50 generation calls and 250,000 reserved input/output tokens per run; no automatic paid retries |

Reserve tenant/global quota atomically in PostgreSQL before accepting work or issuing a paid call. If quota cannot be checked, fail closed. Outstanding/reserved counters have unique operation keys and expiry/reconciliation rules so duplicates and crashes neither double charge nor release capacity while work still runs. Preserve committed-byte, retained-version, reserved-chunk and attempt-artifact accounting fields from schema design. Atomically reserve each attempt's chunk allowance before writes; release only after verified physical purge. Retried and superseded attempts consume allowance too. Tenant document/original quotas do not estimate Qdrant index, WAL or backup bytes: poll actual disk across PostgreSQL, object and vector volumes as a separate global safety signal. The free-space threshold reduces risk but cannot guarantee no disk exhaustion between samples; storage errors still require safe failure handling. Reconcile logical counters against physical inventory and clean noncurrent staging versions. Do not add a billing platform for this slice.

Rotate bounded job selection across tenants and cap running work per tenant; a full tenant cannot monopolize the worker by queueing infinitely. Reject new work with 429 when tenant quota is exhausted; return 503 when global capacity/dependencies prevent acceptance. Return actionable retry guidance. Count rejected, timed-out and unfinished work in benchmark outcomes.

Paid-call reservations include worst-case configured input/output budget for each permitted call. Keep unknown-outcome reservations until usage is reconciled; do not release and blindly retry a timed-out provider request. Report actual and reserved usage separately. Token caps reduce exposure but are not a currency spending guarantee; verify current provider pricing and account-side limits before paid runs.

### 8.2 Model and cache rules

A serving profile pins model/tokenizer artifact revisions, dimensions, normalization and distance settings. V1 uses one profile. Reindex-and-cutover migrations and a separate model-serving tier are deferred. Same-model failover is distinct from switching to an incompatible model.

Redis is deferred. When introduced, authorize before cache access and include tenant, authorized scope/publication versions and prompt/model profiles in keys. Deletion/revocation must affect cache visibility; cache is never authorization authority.

### 8.3 Existing embedding foundation fixes before public deployment

- Add tokenizer-based over-window rejection, including special tokens, with a token-heavy test that fits under 2,000 characters. Do not silently truncate an accepted debug request.
- Unexpected exceptions outside inference must emit a sanitized completion/failure event with request ID and elapsed time. Define and test a controlled generic 500 response with that ID; do not assume code after `call_next` always runs.
- Production logs use stable error codes and safe metadata. Raw exception strings/tracebacks can contain input or secrets; suppress/redact them by policy and restrict any diagnostic sink. Test with a sentinel secret in an exception, including framework/server logging paths.
- Update the foundation guide: its factory-default problem is already fixed according to the supplied review. Do not present it as an outstanding code defect.

These are planned corrections, not changes implemented by this document revision. Preserve current test evidence as historical until checks are actually rerun.

## 9. Service objectives and measurement boundaries

| Objective | Proposed target | Verification condition |
| --- | --- | --- |
| Availability | 99.9% monthly | Design objective only until production monitoring exists |
| Vector retrieval | p95 ≤300 ms | Includes vector lookup/filtering; excludes query embedding and generation; report corpus/filter shape |
| First visible answer | Same as validated complete-answer latency in non-streaming V1 | No separate first-token SLO; streaming is deferred |
| Complete answer | p95 ≤15 sec | Bounded answer size; provider-dependent and provisional |
| Ingestion freshness | 95% within 5 min | From successful upload completion to verified active searchable publication; includes queueing and retries |
| Recovery | Metadata RPO ≤15 min; degraded-service RTO ≤4 hr, provisional | Full-corpus search recovery measured separately; no claim that rebuilding 100M vectors fits four hours |

Measure offered and successful achieved throughput separately. Report all 429/5xx errors, timeouts, dropped iterations and unfinished jobs; do not improve reported latency by silently discarding them. Successful-request percentiles are accompanied by completion/error fractions and the full configured deadline. Performance acceptance requires at least 99% success for valid within-quota requests in the declared load envelope; out-of-envelope overload tests evaluate bounded failure behaviour separately.

For freshness, include every successfully completed upload in the measurement cohort. Failed and still-unsearchable jobs are misses, not omitted samples. Record age of the oldest job and time to drain the burst backlog. The proposed ingestion burst implies 10,000 chunks/minute, approximately 167 embeddings/sec before retries, at 100 chunks/document; benchmark this independently from daily averages.

Each report records corpus page/text/token/chunk distributions; tenant size and traffic skew; 1/5/10-document query mixes; query and output token budgets; cache hit state; and concurrent indexing. Separate query embedding, vector search, context building, real generation and client-observed total time. Client timing begins when the request/upload completion is sent and ends at the complete validated response or searchable activation probe, as applicable. Test/load-generator timestamps and server stage spans must be distinguished.

Use reported p50/p95/p99, achieved arrival rate, errors, timeouts and saturation. Declare test duration, warm-up, cache state, machine specifications and bottlenecks. An HTTP 200 with unsupported answers does not satisfy product quality.

## 10. Recovery contract and proof plan

### 10.1 Cross-store restore procedure

PostgreSQL is the live visibility authority, but restoring an old snapshot must not undo later acknowledged deletion/revocation. Original sources, manifests, extracted artifacts and embedding profiles are immutable rebuild inputs. Store deletion history in an independently durable append-only ledger outside the metadata snapshot rollback boundary, retaining it for at least as long as any restorable backup. For the laptop drill, immutable deletion-operation records in the existing object store are the initial candidate; use unique operation IDs and preserve that ledger namespace while restoring PostgreSQL. No additional ledger database is required. This tests survival of a PostgreSQL rollback with object storage intact, not loss of the laptop/object-store disk. Host-loss resilience requires separate off-host backups and a distinct restore test.

The first restore drill is an offline maintenance operation, not an online recovery protocol. Stop query serving and API mutations (uploads, completion, deletion and membership changes), workers, publishers and reconcilers; verify every old process/subprocess and outstanding external writer has terminated before changing data. Do not rely on an old database flag to fence a process holding restored tokens.

Restore metadata, invalidate all restored execution/read claims and tokens, replay the complete retained deletion ledger, and reconcile object versions and indexed manifests before exposing active publications. Start only fresh processes after reconciliation; restart pending work with new claim identities and output namespaces. Enable API mutations and query serving only after the corresponding gates pass. If old writers cannot be confirmed stopped, abort the drill rather than serving a supposedly reconciled state. Conflicts resolve to hidden/not-ready rather than visible stale data. If ledger coverage is unavailable or its recovery point is uncertain, do not claim safe restored visibility. Independently verify current identity/membership authority; restored membership snapshots alone cannot override later revocation. V1 can require reauthorization/re-enrolment before serving recovered accounts when current authority cannot be established.

Restore vector snapshots only when their manifests/profile mapping match restored metadata; otherwise rebuild from immutable artifacts. Re-dispatch unfinished jobs and clear only verified stale claims. Never let old background messages bypass new claim/generation checks.

The four-hour RTO proposal means a clearly labelled degraded service with identity/metadata reconciled and verified publications searchable. Documents missing verified artifacts remain unavailable, with an explicit status. Full-corpus rebuild time and missing-data count must be reported separately. If a tested restoration cannot meet this objective, revise it rather than state it as an achieved guarantee.

Physical purge evidence includes object versions, attempt namespaces, derived artifacts and cache entries. Backup copies expire by the declared backup-retention policy; restoration always reapplies tombstones. Immediate physical erasure from every backup is not promised.

### 10.2 Evidence to collect

- Quality set: begin with at least 50 reviewed questions over representative PDFs, including unanswerable and cross-tenant cases. Label source/page evidence; preserve a held-out subset.
- Functional checks from the first slice: cross-tenant and same-tenant non-owner access across every endpoint; repeated upload completion; overwrite attempts; crash after job commit; stale lease; partial upsert; manifest mismatch; V3-before-V2 completion; delete-versus-activation; in-flight deletion policy; owner membership revocation; quota races. Broker milestone adds lost confirmations, unroutable messages and worker-loss redelivery.
- Retrieval tests: 10K and 100K vectors; optional 1M. Random/synthetic vectors establish only index behaviour, not semantic answer quality. Include realistic tenant/filter distributions and mixed indexing traffic.
- API tests: controlled arrival rates and latency/error thresholds. Stub-provider runs test application capacity, not real inference throughput or API quota.
- Real runs: a small set of live embeddings/generation calls with token/cost accounting, separately labelled.
- Recovery demo: restart a worker mid-job, replay a duplicate, interrupt index writes and perform the offline restore procedure. Also test completion-versus-cleanup, membership-revocation-versus-activation, read registration versus purge, expired/stalled readers, retained-storage exhaustion and noncurrent staging-version cleanup. Record expected versus observed state.
- Publish reproducible scripts, raw result JSON, hardware/configuration, commit SHA and a short findings report. Record failures as evidence too.

Resume claims must use actual X vectors/Y requests per second/Z p95 results. Say designed for the larger scenario, not serves one million users. Extrapolated estimates are hypotheses requiring validation.

## 11. Implementation order and acceptance gates

**The review requests explicit rules now, not every infrastructure component now.** This document selects contracts; upcoming work teaches and implements them one small slice at a time.

1. Resolve the documented embedding/token/logging gaps with targeted tests and remove stale factory-default documentation. No new infrastructure required for this checkpoint.
2. Define PostgreSQL identities/membership, owner authorization, tenant-consistent document/version/job relationships, generations, claims, quotas and deletion tombstones together. Gate: unauthorized access and invalid cross-tenant references fail.
3. Introduce object storage, immutable upload completion and PostgreSQL job claiming by one worker. Gate: repeated completion creates one job; process restart preserves accepted work; unreferenced upload cleanup is safe.
4. Implement extraction, frozen manifest, batch embedding and one shared vector server. Gate: owner-scoped upload → indexing → retrieval → deletion works as one slice; partial indexing, stale claims and reverse-order version completion cannot publish stale data. Include deletion ledger/restore visibility checks before claiming deletion durability.
5. Add non-streamed generation, citation validation and abstention with a small quality set. Gate: bounded output, invalid citations and absent evidence produce defined results; no unauthorized content reaches generation.
6. Establish baseline metrics, mixed-load measurements, coherent restore drills and resource-admission tests. Keep evidence scoped to the actual tested workload.
7. Add RabbitMQ/Celery/outbox as an explicit messaging-learning milestone if still justified. Gate: routing/confirmation loss, duplicate delivery, worker loss and database-driven redispatch pass. No separate result backend needed.
8. Optimize from measurements: Redis only if useful, then batching/index tuning/replicas and an optional costed cloud demonstration. 100M topology, streaming, enterprise SSO, OCR and later agents remain deferred.

Every stage needs targeted failure checks alongside its happy path; authorization, deletion and recovery are not postponed until after activation code is complete. No code from earlier learning levels is imported.

## 12. Future extensions

Risk analysis can consume a published document-version event and produce version-linked results. Reminder workflows need their own durable scheduling/delivery semantics and idempotency. Neither belongs on the synchronous Q&A request path.

Later security may include enterprise SSO, fine-grained sharing, advanced audit retention, scanning/DLP and regional residency. V1 tenant isolation and access controls remain mandatory.

## 13. Decisions to verify before each integration

Exact compatible package/server versions, vector filter/index settings, embedding artifact revision and token window, hosted-model pricing/context limits, authentication lifecycle, worker deadlines, deletion retention, and cloud-specific recovery/cost settings need documented verification before implementation. Exact vendor-specific implementation details must satisfy the explicit contracts above; unverified defaults are not production guarantees. A contract must be revised openly if a selected implementation cannot enforce it.

## 14. Review resolution and remaining limits

| Review area | Revision decision | Evidence still required |
| --- | --- | --- |
| Authorization | Owner-only matrix and fail-closed all-or-nothing selections | Endpoint and database constraint tests |
| Mutable/repeated completion | Immutable source reference and conditional once-only job/quota transition | Object-store overwrite and completion-race tests |
| Broker delivery | Deferred milestone with explicit transport contract; DB-authoritative recovery | Broker failure experiments when introduced |
| Stale workers | Ownership tokens, attempt-isolated output, publication guards and repeated cleanup | Pause/resume and in-flight-write tests |
| Concurrent updates/deletes | Latest accepted generation wins; tombstone coordinates activation | Reverse completion and delete-race tests |
| Index publication | Immutable manifest, single profile and real read-visibility gate | Exact backend-version integration tests |
| Streaming/citations | Buffer/validate in V1; remove first-token SLO | Citation/abstention evaluation |
| Workload claims | Complete timing cohorts, success fractions, skew and burst definitions | Raw benchmark reports |
| Restore | Reconcile stores and deletion ledger before enabling queries | Safe degraded/full recovery drill |
| Cost/fairness | Configurable atomic reservations, tenant/global limits | Concurrency, saturation and accounting tests |
| Delivery order | Complete vertical slice with early security/failure tests | Implementation milestones |

This revision addresses design decisions, not proof that implementations are correct. External review should check the new contracts, especially source-copy semantics, stale-writer termination, deletion-ledger durability and restore-time authorization. Technology settings remain subject to official-documentation verification at integration time. None of the new behaviour is claimed implemented by the existing 16-test embedding foundation.

## 15. Second-review clarifications and immediate next task

The supplied second review judged version 0.2 ready for the first schema/authorization milestone and reported 16 existing tests passing with one dependency warning. Version 0.3 documents its five remaining coordination rules; it does not claim those rules are implemented or tested.

| Remaining finding | Chosen contract | Implementation gate |
| --- | --- | --- |
| Cleanup racing upload completion | Recorded copy token and mutually exclusive completion/cleanup claims | Upload lifecycle schema and completion integration |
| Inconsistent authorization reads | One joined statement snapshot; shared membership/document lock protocol for pins and activation/revocation | First authorization repository and concurrency tests |
| Unbounded reader pins | Database read leases, explicit deadlines and drain/termination-aware physical purge | Query/download plus deletion slice |
| Writers active during restore | Offline maintenance with verified process stop, claim invalidation and fresh restart | Recovery demonstration; no online restore now |
| Unbounded retained storage | Committed/retained quotas plus physical disk admission and artifact inventory | Accounting fields now, ingestion/resource tests later |

Next implementation task: PostgreSQL identity/membership and owner-scoped document repository. Introduce tenant-consistent constraints and test same-tenant non-owner denial, cross-tenant references, inactive membership, consistent selection and activation/revocation ordering. Reserve upload/deletion/read-lease/accounting lifecycle fields when their tables are introduced; do not implement every table/service at once.

No RabbitMQ, Redis, replicas, new security service or online restore protocol is required to start this milestone. The three embedding/token/logging code gaps remain separately planned fixes; architecture revisions do not fix them automatically. Update stale foundation documentation as part of that bounded code checkpoint. Proceed through targeted acceptance gates instead of repeating unrestricted full-system review indefinitely.
