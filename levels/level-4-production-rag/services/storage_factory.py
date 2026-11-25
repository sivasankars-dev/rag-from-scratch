import os
from dataclasses import dataclass

import boto3

from services.minio_storage import MinIOStorage


@dataclass(frozen=True)
class StorageSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str


def load_storage_settings() -> StorageSettings:
    values = {
        "endpoint": os.getenv("MINIO_ENDPOINT", "").strip(),
        "access_key": os.getenv("MINIO_ACCESS_KEY", "").strip(),
        "secret_key": os.getenv("MINIO_SECRET_KEY", "").strip(),
        "bucket": os.getenv("MINIO_BUCKET", "").strip(),
        "region": os.getenv("MINIO_REGION", "").strip(),
    }

    for name, value in values.items():
        if not value:
            raise ValueError(f"Storage setting '{name}' is required")

    return StorageSettings(**values)


def create_document_storage(
    settings: StorageSettings,
) -> MinIOStorage:
    client = boto3.client(
        "s3",
        endpoint_url=settings.endpoint,
        aws_access_key_id=settings.access_key,
        aws_secret_access_key=settings.secret_key,
        region_name=settings.region,
    )

    return MinIOStorage(
        client=client,
        bucket=settings.bucket,
    )