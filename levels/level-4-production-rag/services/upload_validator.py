from fastapi import UploadFile
from pathlib import Path

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MiB
CHUNK_SIZE = 1024 * 1024          # 1 MiB


class UploadValidationError(ValueError):
    """An expected rejection of client-provided upload content."""


class FileTooLargeError(UploadValidationError):
    pass


def validate_pdf_extension(filename: str | None) -> None:
    if not filename or Path(filename).suffix.lower() != ".pdf":
        raise UploadValidationError("Only PDF files are allowed")

async def validate_file_size(
    file: UploadFile,
    max_file_size: int = MAX_FILE_SIZE,
) -> int:
    if max_file_size <= 0:
        raise ValueError("Invalid maximum file size")

    total_size = 0

    try:
        await file.seek(0)
        while True:
            chunk = await file.read(CHUNK_SIZE)

            if not chunk:
                break

            total_size += len(chunk)

            if total_size > max_file_size:
                raise FileTooLargeError("File too large")

        if total_size == 0:
            raise UploadValidationError("Empty file")

        return total_size

    finally:
        await file.seek(0)

async def validate_pdf_signature(file: UploadFile) -> None:
    try:
        await file.seek(0)
        header = await file.read(5)

        if header != b"%PDF-":
            raise UploadValidationError("Invalid PDF signature")

    finally:
        await file.seek(0)

async def validate_pdf_upload(file: UploadFile) -> int:
    validate_pdf_extension(file.filename)

    file_size = await validate_file_size(file)

    await validate_pdf_signature(file)

    return file_size
