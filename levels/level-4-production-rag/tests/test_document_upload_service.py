import io
from io import BytesIO
from uuid import uuid4
from unittest.mock import Mock

import pytest
from services.document_upload_service import persist_document_upload

def test_cleanup_failure_logs_and_preserves_original_error(caplog):
    session = Mock()
    storage = Mock()

    storage.save.side_effect = RuntimeError("MinIO upload failed")
    storage.delete.side_effect = RuntimeError("MinIO delete failed")

    with pytest.raises(
        RuntimeError,
        match="MinIO upload failed",
    ):
        persist_document_upload(
            session=session,
            storage=storage,
            tenant_id=uuid4(),
            user_id=uuid4(),
            title="test.pdf",
            source=BytesIO(b"%PDF-1.7"),
        )

    session.rollback.assert_called_once()
    session.commit.assert_not_called()
    storage.save.assert_called_once()
    storage.delete.assert_called_once()

    assert "Failed to clean up uploaded document object" in caplog.text
    assert "MinIO delete failed" in caplog.text


def test_commit_failure_preserves_uploaded_object():
    session = Mock()
    storage = Mock()

    session.commit.side_effect = RuntimeError(
        "Commit outcome unknown"
    )

    with pytest.raises(
        RuntimeError,
        match="Commit outcome unknown",
    ):
        persist_document_upload(
            session=session,
            storage=storage,
            tenant_id=uuid4(),
            user_id=uuid4(),
            title="failure.pdf",
            source=BytesIO(b"%PDF-1.7\nTest"),
        )

    session.commit.assert_called_once()
    session.rollback.assert_called_once()
    storage.save.assert_called_once()

    # Commit may have succeeded.
    # Never delete an object when commit outcome is unknown.
    storage.delete.assert_not_called()