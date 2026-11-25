from typing import BinaryIO, Protocol
from uuid import UUID

class DocumentStorage(Protocol):
    def save(
        self,
        *,
        key: str,
        source: BinaryIO,
    ) -> None:
        pass

    def open(self, *, key: str) -> BinaryIO:
        pass

    def delete(self, *, key: str) -> None:
        pass

    from uuid import UUID

def generate_storage_key(
    *,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
) -> str:
    return (
        f"tenants/{tenant_id}/"
        f"documents/{document_id}/"
        f"versions/{version_id}/source.pdf"
    )

class ObjectMissing(FileNotFoundError):
    """The requested object key does not exist (not a missing bucket)."""


class ObjectAccessDenied(PermissionError):
    """Storage refused access; never interpret this as a missing object."""
