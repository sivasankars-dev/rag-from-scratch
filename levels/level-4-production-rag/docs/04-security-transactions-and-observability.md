# Production Security, Transactions, and Observability

**Level 4 Production RAG — consolidated implementation notes (Days 03–05)**  
**Checkpoint:** 11 November 2026  
**Previous checkpoint:** [03 — Document access and versioning](03-document-access-and-versioning.md)

**Historical note:** This chapter supersedes chapter 03’s older statements that the publication helper does not enforce authorization, that access-denial tests are absent, and that all version tests only roll back. Chapter 03 remains a record of the earlier checkpoint.

## 1. Scope and evidence

This document records the improvements made after the original document-access/versioning checkpoint. It is based on the implementation of `app/auth.py`, `app/tenant_auth.py`, `app/dependencies.py`, `services/jwt_verifier.py`, `services/document_version_service.py`, `app/repositories/document.py`, and `app/middleware.py`, together with the shared document-version tests and the latest reported test run.

**Latest test evidence (reported locally):** `55 passed, 2 warnings in 4.21s` for the Level 4 test suite. The dedicated committed-publication visibility test passed (`1 passed in 0.34s`). These results are not a load test, concurrency proof, or deployment certification.

## 2. Day 03 follow-up — authorization and database consistency

### Access rules

`get_accessible_document(session, document_id, tenant_id, user_id, for_update=False)` queries the document with joins to membership, user, and tenant. It requires:

- Exact document, tenant, and owner-user IDs.
- `Document.deleted_at IS NULL`.
- `Membership.status == "ACTIVE"`.
- `User.status == "ACTIVE"`.
- `Tenant.status == "ACTIVE"`.

This is an **owner-only** access model, not a general shared-document permission system. A membership alone does not grant another member access to the owner's document. A revoked member, disabled user or tenant, wrong owner, wrong tenant, or soft-deleted document is excluded by the query.

### Row locking and ORM freshness

When `for_update=True`, the repository applies:

```python
statement.with_for_update(of=Document).execution_options(populate_existing=True)
```

`FOR UPDATE OF documents` locks the selected document row for the current database transaction; it does not lock every joined membership, user, or tenant row. `populate_existing=True` refreshes an already-loaded ORM entity from the selected database row rather than silently retaining stale identity-map attributes.

A separate stale-ORM test uses two sessions: one session loads version V1, another commits a change to V2, and the first session demonstrates the stale in-memory value before reloading through the locked repository query. This verifies ORM refresh behavior in that scenario; it does not prove the absence of all concurrent authorization races. The default `for_update=False` query does **not** force a refresh of an already-loaded ORM entity. The scalar active-version lookup selects the ID directly rather than returning a cached Document object.

**Concrete race:** The document row is locked, but membership, user and tenant rows are not. Another transaction could revoke membership or disable the user/tenant after the eligibility query and before the publication transaction commits. Eligibility is checked at query time, **not guaranteed through commit**. Current denial tests set the status before publication; they do not exercise this interleaving.

### Isolated test database

The test fixtures use `load_test_database_url()`, which checks that the configured test URL differs from the development URL and that its database name ends in `_test`. The `db_session` fixture in `test_document_versions.py` additionally verifies `current_database() == "rag_level4_test"`; **not every fixture does this**. In particular, `two_session_factory` and the authentication integration fixture do not independently assert the connected database name. Verify configuration before running committing tests. A dedicated two-session factory supports tests that commit data and reopen independent sessions. Because committed test data cannot be removed by an outer rollback alone, those tests perform explicit cleanup in `finally` blocks.

## 3. Day 04 — verified request identity (JWT RS256)

### Token verification

`services/jwt_verifier.py` calls PyJWT `jwt.decode()` with:

```python
jwt.decode(
    jwt=token,
    key=public_key,
    algorithms=["RS256"],
    issuer=issuer,
    audience=audience,
    options={"require": ["sub", "iss", "aud", "exp", "iat"]},
)
```

The verifier checks the signature using the configured public key and restricts the accepted algorithm to RS256. It validates the configured issuer and audience and requires the listed claims. The `exp` claim is validated by PyJWT's default expiry verification behavior. PyJWT also validates `iat` and validates `nbf` if supplied. Requiring `iat` ensures its presence; it is **not** a maximum-token-age policy. No explicit clock-skew leeway or maximum token lifetime is configured. The supplied code does not establish key rotation, JWKS fetching, revocation lists, or refresh-token handling.

### Authentication dependency

`get_current_user()` uses `HTTPBearer(auto_error=False)` to extract a bearer token. Missing credentials produce **401** with `WWW-Authenticate: Bearer`. Invalid tokens, malformed/missing `sub`, and non-UUID subjects also produce **401**. A validly signed token is still rejected with **401** if its subject does not identify an ACTIVE user in the database.

The returned `AuthenticatedUser` is an immutable dataclass containing the verified `user_id`. The identity comes from the verified token and database lookup, not from a caller-controlled `user_id` in a request body.

### Tenant-scoped authorization dependency

`get_current_tenant_member(tenant_id, current_user, session)` checks for an ACTIVE membership linking the verified user to the requested tenant, with an ACTIVE tenant record. It returns an immutable `TenantPrincipal(user_id, tenant_id)` on success, otherwise **403** (`Tenant access denied`).

**Important distinction:** a valid JWT proves an authenticated user identity; it does **not** automatically authorize that user in every tenant. A valid token for user A cannot grant access to tenant B unless the active membership and tenant checks pass.

### Implemented HTTP protection boundary

Authentication and tenant authorization are **FastAPI dependencies, not global middleware**. In the reviewed application, the two routes in `app/routers/auth.py` use these dependencies. The embedding endpoint in `app/routers/embedding.py` and the database debug endpoint in `app/main.py` do **not** have an authentication dependency. Exposing them publicly could allow unauthenticated inference calls or database identity inspection; restrict or remove debug routes before deployment. No document HTTP route currently wires the full authenticated publish/read lifecycle together.

### Intended request lifecycle (future document HTTP integration)

1. Client sends `Authorization: Bearer <token>` and requests a tenant-scoped resource.
2. The authentication dependency verifies RS256 signature and token claims.
3. The `sub` is parsed as a UUID and matched to an ACTIVE user.
4. The tenant dependency verifies ACTIVE membership and ACTIVE tenant status.
5. A future document HTTP router must pass **verified** `user_id` and `tenant_id` from these dependencies into the document service, then apply owner-only document authorization and publication-specific rules.

`publish_document_version()` currently accepts plain UUID arguments. It authorizes the **supplied identities** but does not authenticate where they came from. Never take these IDs directly from untrusted request-body identity fields when wiring the HTTP endpoint.

**HTTP semantics in this implementation:** 401 for missing/invalid credentials or inactive users; 403 for a verified user without permitted tenant membership. The internal document publication helper raises `ValueError("Access denied")` when its document authorization query finds no eligible document; translating that error to an HTTP status is the responsibility of a caller/router and is not shown here.

## 4. Day 05 — authorized publication and transaction visibility

### Publication service

`publish_document_version()`:

1. Retrieves an accessible document with `for_update=True`.
2. Raises `ValueError("Access denied")` if owner/tenant/membership/user/document checks fail.
3. Retrieves the requested `DocumentVersion`, constrained to the same document, with `FOR UPDATE` and `populate_existing=True`.
4. Rejects an unknown or mismatched version with `ValueError("Version does not belong to this document")`.
5. Rejects any version whose status is not `READY`.
6. Assigns `document.active_version_id = version.id` and calls `session.flush()`.

The service permits **any READY version belonging to the document**, not necessarily the newest. Publishing V2 and then V1 would move the active pointer backward; there is no latest-version or desired-generation guard.

**Transaction boundary:** the service does **not** call `session.commit()`. The caller must commit to persist the publication or roll back to discard it. A database `flush()` sends pending SQL within the current transaction but does not make it durable across independent sessions.

`get_readable_active_version_id()` returns the active version ID only if the document is eligible under the owner-only, ACTIVE membership/user/tenant, non-deleted access checks. It returns `None` if no eligible row or published version exists.

### Test: publication visible after commit

The dedicated test `test_published_version_visible_after_commit_in_new_session` establishes:

- **Session A:** create ACTIVE user, tenant, membership, document, and READY version; commit.
- **Session B:** call `publish_document_version()`; commit.
- **Session C:** load the document and assert its `active_version_id` equals the published version ID; also assert the readable active version lookup returns that ID.
- **Cleanup:** clear the active-version foreign key, delete version/document/membership/tenant/user in dependency order, and commit cleanup.

This confirms committed publication visibility across new database sessions in the tested scenario. It does not test simultaneous publishers, deadlocks, retry behavior, or transaction isolation anomalies.

### Negative-path coverage

The shared document-version tests include attempts to publish as a disabled owner, under a disabled tenant, after membership revocation, as a same-tenant non-owner, and as a cross-tenant user. They also cover invalid version statuses, duplicate version numbers, cross-document active-version foreign-key rejection, revoked-member reads, and soft-deleted document reads.

## 5. Day 05 — HTTP middleware observability

`register_middleware(app)` installs an HTTP middleware that creates a UUIDv4 request ID, stores it at `request.state.request_id`, and measures elapsed time with `time.perf_counter()`. **The measurement stops when `call_next()` returns a response object**, not after the complete response body has been sent to the client.

### Successful response path

After `call_next(request)` returns a response, the middleware adds:

- `X-Request-ID: <uuid>`
- `X-Response-Time-Ms: <duration formatted to 2 decimals>`

It logs `Request completed` with request ID, method, URL path, actual response status, and elapsed milliseconds using the `uvicorn.error` logger at INFO level. This is a completed **`call_next()`** path, not proof that the client received the complete response body. A handled HTTP error response may also take this path. Streaming/body-transmission errors or later background-task failures can occur after this log line and may not be caught by this middleware branch.

### Unhandled exception path

If `call_next()` raises **before returning the response object**, the middleware logs `Request failed` at ERROR level via `logger.exception(...)`, including a traceback, request ID, method, URL path, a logged `status=500`, and elapsed milliseconds. It then uses bare `raise` to preserve the original exception.

**Limitation:** the exception path does not construct a response or attach `X-Request-ID` / `X-Response-Time-Ms` headers to the resulting HTTP 500. The logged `500` is the middleware's failure classification, not a status read from an actual response object.

### Failure test

`test_middleware_failure.py` registers middleware on an isolated FastAPI app with an endpoint that raises `RuntimeError("simulated failure")`. `TestClient(..., raise_server_exceptions=False)` allows the test to assert the HTTP 500 response, while `caplog` checks the ERROR log and original exception evidence. The reported dedicated middleware test passed. The latest full suite also passed with this test included.

**Operational caution:** URL paths and tracebacks may contain sensitive values. Production logging must account for sensitive exception messages and tracebacks as well as URL paths; apply redaction, log-access controls, retention limits, structured fields, and route templates as appropriate. A single request's `duration_ms` is not a p95/p99 latency metric.

## 6. Production scenarios and expected behavior

| Scenario | Enforcement | Expected result |
|---|---|---|
| Client alters JWT `sub` without a valid new signature | RS256 signature verification | Token rejected (401) |
| JWT has wrong issuer or audience | PyJWT issuer/audience validation | Token rejected (401) |
| JWT valid but database user disabled | ACTIVE user query | Authentication rejected (401) |
| JWT valid but tenant membership revoked | Tenant membership dependency | Tenant access denied (403) |
| User belongs to tenant but does not own document | Owner-only document query | Internal publication denied; HTTP mapping depends on caller |
| Version is `PENDING` or `FAILED` | READY-only publication check | Publication rejected |
| Publication flushed but not committed | Transaction semantics | Not durably published to independent sessions |
| Application raises an unhandled exception before `call_next()` returns | Middleware exception branch | ERROR log with traceback and request ID; exception re-raised |
| Response streaming or background work fails after `call_next()` returns | Outside the measured/caught boundary | May not appear in the middleware failure log; success may already be logged |

## 7. Verification commands

Run from the repository root with the local PostgreSQL test database provisioned and migrations applied. Level 4 loads its `.env` configuration; check that `DATABASE_URL` and `TEST_DATABASE_URL` are configured for the intended databases, and that `JWT_PUBLIC_KEY_PATH`, `JWT_ISSUER`, and `JWT_AUDIENCE` are set to valid startup values. The authentication integration tests replace JWT settings with generated test values **after application lifespan startup**, so those startup settings are still required. Do not commit real keys or passwords.

The database URL loader guards against a matching development/test URL and requires a `_test` suffix, but this does not replace verifying the actual database target before tests that commit data.

Example verification commands:

```bash
PYTHONPATH=levels/level-4-production-rag \
uv run pytest levels/level-4-production-rag/tests/ -q

PYTHONPATH=levels/level-4-production-rag \
uv run pytest \
  levels/level-4-production-rag/tests/test_document_versions.py::test_published_version_visible_after_commit_in_new_session \
  -v

PYTHONPATH=levels/level-4-production-rag \
uv run pytest \
  levels/level-4-production-rag/tests/test_middleware_failure.py -v
```

**Latest user-reported result:** `55 passed, 2 warnings in 4.21s`. The warnings were a Starlette/AnyIO `BlockingPortal` deprecation warning and a test HS256 key-length warning (`InsecureKeyLengthWarning`). Neither caused test failure; the latter concerns a deliberately tested HS256 token and does not mean the RS256 verifier accepts HS256.

## 8. Interview revision: questions to be able to answer

1. Why does changing a JWT payload invalidate its RS256 signature?
2. Why must the server pin `algorithms=["RS256"]` rather than trust the token header?
3. What is the difference between 401 authentication failure and 403 tenant authorization failure?
4. Why is an ACTIVE user check still needed after a valid JWT signature?
5. Why does membership in a tenant not automatically grant document ownership?
6. What does `FOR UPDATE OF Document` lock, and what does it **not** lock?
7. How can SQLAlchemy's identity map return stale attributes after another session commits?
8. Why is `populate_existing=True` relevant to a locking query?
9. Why can `session.flush()` succeed while another session still cannot see the publication?
10. What does a fresh-session visibility test prove, and what concurrency properties remain untested?
11. When is `logger.exception()` useful for diagnosing unexpected failures, and how would you prevent sensitive values in exception messages or tracebacks from leaking into logs?
12. Why do unhandled 500 responses currently lack the middleware's normal response headers?

## 9. Remaining work / limitations

- Automatic upload validation, version-number allocation, processing, ingestion, and chunk-to-version retrieval scoping are not implemented by the shown code.
- No claim is made here about JWT key rotation, refresh-token lifecycle, revocation lists, or rate limiting.
- Concurrency races (especially revocation between eligibility check and commit), simultaneous publishers, isolation levels, deadlock/retry policy, and rollback visibility from a new session need separate design and tests.
- Publishing an older READY version is currently allowed; a monotonic-version or generation guard would require an explicit product rule and implementation.
- JWT verifier tests do not exhaustively cover all required-claim omissions, malformed subjects, or future `iat`/`nbf`; HTTP authentication tests also lack several malformed/missing bearer-token cases. Tenant tests do not cover every missing-membership/unknown-tenant variant.
- HTTP response headers for unhandled 500s, structured/redacted logging, and metrics aggregation remain future observability improvements.
- A passing unit/integration suite is necessary evidence, not proof of production readiness.

## 10. Checkpoint summary

After the original document-access/versioning checkpoint, the implementation gained verified RS256 identity, active-user and tenant membership authorization, document-level owner checks with row locking and ORM refresh, authorized READY-only publishing with caller-controlled commits, cross-session publication verification, and request-level success/failure observability. The latest **user-reported** Level 4 test suite passed **55 tests**. A subsequent Codex review ran only the isolated JWT verifier and middleware tests (**9 passed, 2 warnings in 0.45s**); it did not rerun the database suite. Neither result proves production readiness.
