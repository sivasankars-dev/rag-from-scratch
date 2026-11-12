# 05 — Secure PDF Upload Validation

## Scope and status

**Level:** 4 — Production RAG
**Feature:** Tenant-authorized PDF upload validation
**Status:** Implemented as a **validation-only** endpoint; storage and ingestion are **not** implemented.

Before this review, the user reported **90 passing Level 4 tests and 2 warnings**. This is a reported local test result, not an independent CI verification.

## Objective

Accept a multipart PDF upload only from an authenticated, active member of the requested tenant. Validate the filename, non-empty size, maximum size, and leading PDF signature before returning validation metadata. Do not trust a client-supplied user identity.

## Relevant files

- `app/main.py` — registers the documents router.
- `app/routers/documents.py` — tenant-scoped upload endpoint.
- `services/upload_validator.py` — filename, size, and header validation.
- `app/auth.py` — verifies bearer JWT and resolves an active user.
- `app/tenant_auth.py` — resolves authorized tenant membership.
- `tests/test_upload_validator.py` — validator unit tests.
- `tests/test_auth_integration.py` — authentication, tenant authorization, and upload API integration tests.

All paths above are relative to `levels/level-4-production-rag/`.

## API contract

**Method:** `POST`
**Path:** `/tenants/{tenant_id}/documents/upload`
**Request:** `multipart/form-data`, field name `file`; `Authorization: Bearer <JWT>` header.

The route uses the `get_current_tenant_member` dependency, which in turn relies on authenticated user resolution. The response derives `tenant_id` and `user_id` from the authorized principal, not from multipart fields.

Example successful response:

```json
{
  "status": "validated",
  "tenant_id": "<authorized-tenant-uuid>",
  "user_id": "<authenticated-user-uuid>",
  "filename": "test.pdf",
  "size_bytes": 27
}
```

The example is illustrative; actual `size_bytes` is the length of the submitted file.

### Observed/implemented error mapping

| Condition | HTTP status | Detail |
|---|---:|---|
| Missing or invalid bearer token | 401 | Authentication-specific message |
| No active membership in requested tenant | 403 | `Tenant access denied` |
| Missing or non-`.pdf` filename | 400 | `Only PDF files are allowed` |
| Empty file | 400 | `Empty file` |
| File without `%PDF-` at the beginning | 400 | `Invalid PDF signature` |
| File larger than 10 MiB, within the request-body cap | 413 | `File too large` |
| Entire multipart body larger than 11 MiB | 413 | `Content Too Large` (framework response; may be plain text) |

Missing multipart fields and malformed request bodies may be rejected by FastAPI before the route runs; they are not covered by the table above.

## Validation flow

1. A route-scoped Starlette body limiter bounds the entire request to 11 MiB, including multipart overhead and extra fields. It counts received bytes even without a trustworthy `Content-Length`. FastAPI then parses the bounded multipart request and resolves dependencies. Body-limit or parser errors can precede authentication errors.
2. The JWT is verified and an active user is resolved.
3. Membership in the **requested** tenant is checked; unauthorized access is rejected.
4. `validate_pdf_extension(file.filename)` requires a case-insensitive `.pdf` suffix.
5. `validate_file_size(file)` first seeks to zero, then reads in **1 MiB chunks**, rejects empty files and files **over 10 MiB**, and returns the byte count.
6. `validate_pdf_signature(file)` first seeks to zero, then reads the first five bytes and requires `b"%PDF-"`.
7. Both file-reading validators reset the stream to offset zero in `finally` blocks, including on content-validation failure. This is rewind-to-zero behavior, not restoration of an arbitrary original cursor. A broken or closed stream can itself fail to seek.
8. The route returns validation metadata; it does **not** persist the document.

### Size boundaries

- `MAX_FILE_SIZE = 10 * 1024 * 1024` bytes (10 MiB).
- `CHUNK_SIZE = 1024 * 1024` bytes (1 MiB).
- The condition is `total_size > max_file_size`: exactly 10 MiB is allowed; 10 MiB plus one byte is rejected.
- `max_file_size <= 0` is a configuration error, not a client-content error.
- The 11 MiB total-body cap is separate from the 10 MiB file limit; excessive multipart overhead or additional files can trigger it.

## Authorization model

The path parameter `tenant_id` identifies the tenant whose document space is being accessed. The authorization dependency must verify that the authenticated user is an **active member of that tenant** and that the tenant is active. Membership in Tenant A alone does not authorize uploads to Tenant B; a user with active memberships in both may use either. Multipart identity fields do not override the path tenant or verified user.

Authentication and authorization are distinct: a correctly signed JWT alone does not grant tenant membership.

## Testing

The reported local regression command and result were:

```bash
PYTHONPATH=levels/level-4-production-rag \
uv run pytest levels/level-4-production-rag/tests/ -q
# 90 passed, 2 warnings
```

The original tests cover:

- Valid and invalid file-size cases, empty file, extension, signature, and pointer-reset checks in validator tests.
- Missing JWT (401), invalid JWT (401), authorized tenant member (200), revoked membership (403), and cross-tenant access (403).
- Fake PDF header (400), oversized upload (413), and empty upload (400).

The warnings reported were a Starlette/AnyIO deprecation and a short HMAC test-key warning in a negative JWT algorithm test. Neither was a failing test.

After the validation-only review fixes, the same full-suite command passed **106 tests, 2 warnings in 5.34s** on 12 November 2026. Neither warning was suppressed. New regression cases cover prior cursor movement, read failures, typed error mapping, multipart cleanup on success/rejection/denial, and total-body rejection with missing or false Content-Length. Authorization integration checks also cover disabled users/tenants, spoofed multipart identity fields, and an exactly 10 MiB PDF. These results do not establish deployment capacity or complete PDF safety.

## Security boundaries and known limitations

**This is an initial validation gate, not complete production upload security.**

1. **Header-only check:** `b"%PDF-"` is not proof of a structurally valid or safe PDF. A malicious or malformed file can pass. Use a hardened PDF parser and appropriate scanning/isolation before ingestion.
2. **Request buffering:** Multipart parsing still precedes authentication and may spool temporary files. The route now limits total body bytes to 11 MiB before parser consumption. This does not cap bytes already buffered by a server/proxy, concurrent requests, or upload duration. Ingress limits, timeouts and concurrency controls remain required before public exposure.
3. **No application persistence:** Temporary multipart spooling can write to disk; there is no durable object-storage write, document metadata transaction, checksum, idempotency, version publication, or ingestion job in this endpoint.
4. **Typed errors:** `FileTooLargeError` maps to 413 and other `UploadValidationError` instances map to 400. Unexpected errors are not exposed as client-validation details. Existing content-rejection messages remain unchanged.
5. **Filename safety:** The original filename is returned as metadata. Never use an untrusted filename directly as a storage path; generate server-controlled storage keys and normalize/sanitize any display name.
6. **Abuse controls:** Rate limiting, quotas, audit logs, malware scanning, and resource exhaustion protections have not been demonstrated for this endpoint.
7. **Lifecycle:** FastAPI closes parsed form uploads through its request exit stack; the installed Starlette parser closes partial files when parsing fails. Regression tests check success, rejection, authorization denial and body-limit cleanup. Abrupt process termination and deployed-server cancellation still require operational testing.
8. **Authorization regression:** Continue to test disabled users, disabled tenants, revoked membership, and cross-tenant access as storage and ingestion are introduced.

## Suggested follow-up milestones

1. Keep typed error mapping and multipart cleanup covered when upgrading FastAPI/Starlette.
2. Add ingress timeouts, concurrency limits and rate controls alongside the application body-size cap.
3. Validate actual PDF structure in a constrained parser or isolated worker, with defensive limits on pages, decompression, and processing time.
4. Design tenant-scoped storage keys, content hashes, upload state transitions, and transactional document metadata.
5. Introduce asynchronous ingestion with retries, idempotency, authorization rechecks where required, and observability.
6. Add integration tests for storage failures, duplicate uploads, interrupted uploads, tenant isolation, and malformed PDFs.

## Definition of done for this milestone

- [x] Authenticated, tenant-scoped validation endpoint registered.
- [x] Filename, size, empty-file, and header checks implemented.
- [x] Validation stream rewound after size/signature reads.
- [x] Negative authentication and cross-tenant API scenarios tested.
- [x] Reported Level 4 regression: 90 tests passed.
- [x] Application total-body limit, typed errors and cursor-independent validation.
- [ ] Production ingress limits, deep PDF validation, scanning, and persistence — intentionally out of scope.
- [x] Independent security/code review and validation-only fixes; remaining deployment risks recorded above.
