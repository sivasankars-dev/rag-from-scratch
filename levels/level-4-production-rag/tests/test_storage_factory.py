from unittest.mock import patch

import pytest

from services.minio_storage import MinIOStorage
from services.storage_factory import (
    StorageSettings,
    create_document_storage,
    load_storage_settings,
)


def test_missing_storage_configuration(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("MINIO_ACCESS_KEY", "test-access")
    monkeypatch.setenv("MINIO_SECRET_KEY", "test-secret")
    monkeypatch.setenv("MINIO_REGION", "us-east-1")

    monkeypatch.delenv("MINIO_BUCKET", raising=False)

    with pytest.raises(ValueError, match="bucket"):
        load_storage_settings()


def test_create_document_storage():
    settings = StorageSettings(
        endpoint="http://localhost:9000",
        access_key="test-access",
        secret_key="test-secret",
        bucket="test-bucket",
        region="us-east-1",
    )

    with patch("services.storage_factory.boto3.client") as mock_client:
        storage = create_document_storage(settings)

    assert isinstance(storage, MinIOStorage)
    assert storage.bucket == "test-bucket"
    assert storage.client is mock_client.return_value

    mock_client.assert_called_once_with(
        "s3",
        endpoint_url="http://localhost:9000",
        aws_access_key_id="test-access",
        aws_secret_access_key="test-secret",
        region_name="us-east-1",
    )