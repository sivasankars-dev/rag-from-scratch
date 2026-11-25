from typing import BinaryIO

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from services.document_storage import ObjectMissing, ObjectAccessDenied


class MinIOStorage:
    def __init__(self, client: BaseClient, bucket: str):
        self.client = client
        self.bucket = bucket

    def save(self, *, key: str, source: BinaryIO) -> None:
        self.client.upload_fileobj(
            Fileobj=source,
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={
                "ContentType": "application/pdf",
            },
        )

    def delete(self, *, key) -> None:
        self.client.delete_object(
            Bucket=self.bucket,
            Key=key,
        )

    def open(self, *, key) -> BinaryIO:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "NoSuchKey":
                raise ObjectMissing("Object key does not exist") from exc
            if code in {"AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
                raise ObjectAccessDenied("Object access denied") from exc
            # Missing bucket, generic 404, network/service errors remain errors.
            raise
        return response["Body"]