import logging
from uuid import UUID, uuid4
from sqlalchemy.orm import Session
from typing import BinaryIO
from app.models.document import Document, DocumentVersion
from services.document_storage import (
    DocumentStorage,
    generate_storage_key,
)

logger = logging.getLogger(__name__)

def create_pending_document(
    *,
    session: Session,
    tenant_id: UUID,
    user_id: UUID,
    title: str,
) -> tuple[Document, DocumentVersion]:
    document = Document(
        id=uuid4(),
        tenant_id=tenant_id,
        owner_user_id=user_id,
        title=title,
    )

    version = DocumentVersion(
        id=uuid4(),
        document_id=document.id,
        version_number=1,
        status="PENDING",
    )

    session.add(document)
    session.add(version)
    session.flush()

    return document, version


def persist_document_upload(
    *,
    session: Session,
    storage: DocumentStorage,
    tenant_id: UUID,
    user_id: UUID,
    title: str,
    source: BinaryIO,
) -> tuple[Document, DocumentVersion]:

    storage_key = None
    upload_attempted = False
    commit_started = False

    try:
        document, version = create_pending_document(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
        )

        storage_key = generate_storage_key(
            tenant_id=tenant_id,
            document_id=document.id,
            version_id=version.id,
        )

        source.seek(0)

        upload_attempted = True
        storage.save(
            key=storage_key,
            source=source,
        )

        version.storage_key = storage_key
        version.status = "READY"

        # From this point, commit outcome may be uncertain.
        commit_started = True
        session.commit()

        return document, version

    except Exception:
        try:
            session.rollback()
        except Exception:
            logger.exception(
                "Database rollback failed during document upload"
            )

        if commit_started:
            logger.exception(
                "Document upload commit outcome uncertain; "
                "preserving storage object for reconciliation",
                extra={"storage_key": storage_key},
            )

        elif upload_attempted and storage_key is not None:
            try:
                storage.delete(key=storage_key)
            except Exception:
                logger.exception(
                    "Failed to clean up uploaded document object",
                    extra={"storage_key": storage_key},
                )

        raise
