# Document access and versioning

In this checkpoint, PostgreSQL tracks who owns a document, which workspace it belongs to, and which version is published. We'll follow Siva's `handbook.pdf` in the Acme workspace.

## Who can read the handbook?

| Table | Example | What it tells us |
|---|---|---|
| `users` | Siva | Who the person is |
| `tenants` | Acme | Which workspace the request targets |
| `memberships` | Siva belongs to Acme and is `ACTIVE` | Whether Siva has an active membership in this workspace |
| `documents` | Acme handbook, owned by Siva | Who owns the document and whether it was soft-deleted |

For an owner-only read, the user and workspace must be active, the user must have an active membership in that workspace, and the document must belong to the workspace and be owned by that user. The document must also have `deleted_at IS NULL`.

Priya can be an active Acme member and still be denied access to Siva's handbook. If Acme revokes Siva's membership, Siva remains the recorded owner and loses read access in Acme. If Siva soft-deletes the handbook, only that file becomes ineligible for reads.

The document's foreign key ties its tenant and owner to an existing membership row. The read query checks that row's current status.

## What happens when Siva updates the handbook?

The implemented schema allows multiple `document_versions` rows under the same document ID. Version numbers are unique within each document, so Acme and Beta can each have a `handbook.pdf` with a version 1. Tests currently insert these rows and assign their numbers and statuses directly. Automatic uploads, version-number allocation and processing are planned; changing a document does not automatically create a version today.

| Event | Published version |
|---|---|
| First version exists and has yet to be published | None |
| V1 is `READY` and published | V1 |
| V2 is `PENDING` or `FAILED` | V1 |
| V2 is `READY` and has yet to be published | V1 |
| V2 is `READY` and published | V2 |

`READY` is intended to mean processing has completed; the current checkpoint stores the status but does not implement or verify that processing workflow. Publishing updates `documents.active_version_id` in the database transaction. PostgreSQL ensures the pointer refers to a version of the same document. The publish service checks that the version is `READY`. V1 stays in the version history when V2 becomes active.

`publish_document_version()` is a trusted internal helper, not an authorization boundary. It checks that the document is not soft-deleted, the version belongs to it, and the version is READY. It does not check caller identity or active user, tenant or membership status. A future user-facing caller must enforce authorization before calling it.

The helper calls `session.flush()`, not `session.commit()`. The caller owns the transaction and must commit to make publication durable or roll back to discard it. Current version tests inspect the change within their transaction and roll it back afterward.

The active-version lookup checks document access and returns the published version ID. It returns `None` if access is denied or if the document has no published version.

## Run locally

Run these commands from the repository root with Docker and `uv` available. The database URL below uses the local Docker Compose credentials.

```bash
docker compose -p rag-level4 \
  -f levels/level-4-production-rag/compose.yaml up -d --wait postgres

export DATABASE_URL='postgresql+psycopg://rag_app:local_dev_password@127.0.0.1:5433/rag_level4'
export PYTHONPATH=levels/level-4-production-rag

uv run alembic -c levels/level-4-production-rag/alembic.ini upgrade head
uv run pytest levels/level-4-production-rag/tests -q
```

In a **previous local run**, the full Level 4 suite reported **29 passed** with one Starlette/AnyIO deprecation warning. This documentation update did not rerun the tests. The document version tests cover multiple versions per document, duplicate version rejection, rejection of a pointer to another document's version, publishing rules, and the owner reading the published version.

Access-denial coverage remains incomplete: neither document-read nor active-version tests exercise disabled users, disabled tenants, revoked memberships or soft-deleted documents. Active-version lookup also lacks same-tenant non-owner and cross-tenant denial tests, although the document-read test covers those two cases. These are test coverage gaps, not evidence that the existing query predicates fail.

## What's next

Add the missing access-denial tests. Then link ingested chunks to their document version so retrieval can search only chunks from an authorized, published version. Automatic upload/version processing, PDF ingestion and vector retrieval are later steps in this Level 4 implementation.
