from io import BytesIO
from unittest.mock import Mock

from services.minio_storage import MinIOStorage


def test_save_uploads_pdf():
    client = Mock()
    storage = MinIOStorage(
        client=client,
        bucket="rag-documents",
    )

    pdf = BytesIO(b"%PDF-1.7\nfake test content")
    key = "tenants/123/documents/456/versions/789/source.pdf"

    storage.save(key=key, source=pdf)

    client.upload_fileobj.assert_called_once_with(
        Fileobj=pdf,
        Bucket="rag-documents",
        Key=key,
        ExtraArgs={"ContentType": "application/pdf"},
    )

def test_delete_removes_object():
    client = Mock()

    storage = MinIOStorage(
        client=client,
        bucket="rag-documents"
    )

    key = "tenants/123/documents/456/versions/789/source.pdf"

    storage.delete(key=key)

    client.delete_object.assert_called_once_with(
        Bucket="rag-documents",
        Key=key,
    )


def test_open_returns_pdf_stream():
    client = Mock()

    storage = MinIOStorage(
        client=client,
        bucket="rag-documents"
    )

    key = "tenants/123/documents/456/versions/789/source.pdf"
    pdf = BytesIO(b"%PDF-1.7\nfake test content")

    client.get_object.return_value = {
        "Body": pdf,
    }

    result = storage.open(key=key)

    assert result is pdf
    assert result.read() == b"%PDF-1.7\nfake test content"

    result.close()





def test_open_classifies_only_explicit_missing_key():
    import pytest
    from botocore.exceptions import ClientError
    from services.document_storage import ObjectMissing, ObjectAccessDenied
    for code, expected in [
        ("NoSuchKey", ObjectMissing), ("AccessDenied", ObjectAccessDenied),
        ("NoSuchBucket", ClientError), ("404", ClientError), ("SlowDown", ClientError),
    ]:
        client = Mock()
        client.get_object.side_effect = ClientError({"Error": {"Code": code}}, "GetObject")
        with pytest.raises(expected):
            MinIOStorage(client, "bucket").open(key="key")
