"""Fingerprint foundation only; callers remain responsible for PDF validation."""
from dataclasses import dataclass
import hashlib
from typing import BinaryIO

FINGERPRINT_VERSION = 1
_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class UploadFingerprint:
    version: int
    fingerprint: str
    content_sha256: str
    size_bytes: int


def fingerprint_pdf_upload(*, source: BinaryIO, size_bytes: int, title: str) -> UploadFingerprint:
    """Hash the entire validated upload, restoring its original stream position.

    V1 encoding: domain tag followed by three uint64-length-prefixed fields:
    exact UTF-8 title, ASCII decimal byte count, and raw SHA-256 content digest.
    No filename normalization is performed; title must equal the stored title.
    """
    if not isinstance(title, str) or not 1 <= len(title) <= 255 or "\x00" in title:
        raise ValueError("Title must contain 1 to 255 characters and no NUL")
    if type(size_bytes) is not int or size_bytes <= 0:
        raise ValueError("Size must be a positive integer")
    title_bytes = title.encode("utf-8")
    original_position = source.tell()
    digest = hashlib.sha256()
    actual_size = 0
    try:
        source.seek(0)
        while chunk := source.read(_CHUNK_SIZE):
            actual_size += len(chunk)
            if actual_size > size_bytes:
                raise ValueError("Upload size does not match validated size")
            digest.update(chunk)
        if actual_size != size_bytes:
            raise ValueError("Upload size does not match validated size")
    finally:
        source.seek(original_position)

    fingerprint = hashlib.sha256(b"production-rag/pdf-upload/v1\x00")
    for field in (title_bytes, str(actual_size).encode("ascii"), digest.digest()):
        fingerprint.update(len(field).to_bytes(8, "big"))
        fingerprint.update(field)
    return UploadFingerprint(FINGERPRINT_VERSION, fingerprint.hexdigest(), digest.hexdigest(), actual_size)
