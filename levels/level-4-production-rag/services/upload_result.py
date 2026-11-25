"""Shared completed-result validation. Caller holds authorization and operation locks."""
from sqlalchemy import select
from app.models import Document, DocumentVersion, UploadAttempt


def valid_completed_result(s, op, tenant_id, user_id):
    attempts = s.scalars(select(UploadAttempt).where(
        UploadAttempt.operation_id == op.id, UploadAttempt.tenant_id == tenant_id)
        .order_by(UploadAttempt.lease_generation, UploadAttempt.id).with_for_update()).all()
    if not attempts or len(attempts) != op.lease_generation:
        return False
    first, current = attempts[0], attempts[-1]
    for generation, a in enumerate(attempts, 1):
        key = f"tenants/{tenant_id}/documents/{first.reserved_document_id}/versions/{first.reserved_version_id}/attempts/{a.id}/source.pdf"
        if (a.lease_generation != generation or a.storage_key != key
            or (a.reserved_document_id, a.reserved_version_id) != (first.reserved_document_id, first.reserved_version_id)
            or (a.expected_size_bytes, a.expected_sha256) != (op.request_size_bytes, op.request_content_sha256)):
            return False
    if (op.status != "COMPLETED" or op.requesting_user_id != user_id or op.tenant_id != tenant_id
        or current.lease_token != op.lease_token
        or (op.document_id, op.version_id) != (first.reserved_document_id, first.reserved_version_id)):
        return False
    return s.scalar(select(Document.id).join(DocumentVersion, DocumentVersion.document_id == Document.id)
        .where(Document.id == op.document_id, DocumentVersion.id == op.version_id,
               Document.tenant_id == tenant_id, Document.owner_user_id == user_id,
               Document.deleted_at.is_(None), DocumentVersion.status == "READY",
               DocumentVersion.storage_key == current.storage_key)) is not None
