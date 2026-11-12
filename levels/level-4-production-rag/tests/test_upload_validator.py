
from io import BytesIO

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from uuid import uuid4
from starlette import formparsers

from app.routers import documents
from app.tenant_auth import TenantPrincipal, get_current_tenant_member

from services.upload_validator import (
    MAX_FILE_SIZE,
    FileTooLargeError,
    validate_file_size,
    validate_pdf_extension,
    validate_pdf_signature,
    validate_pdf_upload
)

@pytest.mark.parametrize(
    "filename",
    ["report.pdf", "REPORT.PDF", "report.PdF"],
)
def test_valid_pdf_extension(filename):
    validate_pdf_extension(filename)


@pytest.mark.parametrize(
    "filename",
    ["malware.exe", "report.pdf.exe", "report", "", None],
)
def test_invalid_pdf_extension(filename):
    with pytest.raises(
        ValueError,
        match="Only PDF files are allowed",
    ):
        validate_pdf_extension(filename)

class CountingUpload:
    def __init__(self, content: bytes):
        self.file = BytesIO(content)
        self.read_calls = 0
        self.bytes_read = 0

    async def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        chunk = self.file.read(size)
        self.bytes_read += len(chunk)
        return chunk

    async def seek(self, offset: int) -> None:
        self.file.seek(offset)

@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_upload(content: bytes) -> UploadFile:
    return UploadFile(
        filename="test.pdf",
        file=BytesIO(content),
    )


# Test 1: Normal valid file
@pytest.mark.anyio
async def test_valid_file_size():
    content = b"A" * (5 * 1024 * 1024)
    file = make_upload(content)

    result = await validate_file_size(file)

    assert result == len(content)
    assert file.file.tell() == 0


# Test 2: Exactly at maximum boundary
@pytest.mark.anyio
async def test_exactly_max_file_size_accepted():
    content = b"A" * MAX_FILE_SIZE
    file = make_upload(content)

    result = await validate_file_size(file)

    assert result == MAX_FILE_SIZE
    assert file.file.tell() == 0


# Test 3: Just one byte above limit
@pytest.mark.anyio
async def test_one_byte_over_limit_rejected():
    content = b"A" * (MAX_FILE_SIZE + 1)
    file = make_upload(content)

    with pytest.raises(ValueError, match="File too large"):
        await validate_file_size(file)

    assert file.file.tell() == 0


# Test 4: Oversized upload
@pytest.mark.anyio
async def test_oversized_file_rejected():
    content = b"A" * (15 * 1024 * 1024)
    file = make_upload(content)

    with pytest.raises(ValueError, match="File too large"):
        await validate_file_size(file)

    assert file.file.tell() == 0


# Test 5: Empty file
@pytest.mark.anyio
async def test_empty_file_rejected():
    file = make_upload(b"")

    with pytest.raises(ValueError, match="Empty file"):
        await validate_file_size(file)

    assert file.file.tell() == 0


# Test 6: Small file, less than one chunk
@pytest.mark.anyio
async def test_small_file_accepted():
    content = b"ABC"
    file = make_upload(content)

    result = await validate_file_size(file)

    assert result == 3
    assert file.file.tell() == 0


# Test 7: Custom maximum file size
@pytest.mark.anyio
async def test_custom_file_size_limit():
    content = b"A" * 1025
    file = make_upload(content)

    with pytest.raises(ValueError, match="File too large"):
        await validate_file_size(
            file,
            max_file_size=1024,
        )

    assert file.file.tell() == 0


# Test 8: Invalid configuration
@pytest.mark.anyio
async def test_invalid_max_file_size():
    file = make_upload(b"ABC")

    with pytest.raises(
        ValueError,
        match="Invalid maximum file size",
    ):
        await validate_file_size(
            file,
            max_file_size=0,
        )


# Test 9: File can be read again after validation
@pytest.mark.anyio
async def test_file_readable_after_validation():
    content = b"Hello PDF"
    file = make_upload(content)

    await validate_file_size(file)

    reread_content = await file.read()

    assert reread_content == content


# Test 10: Early rejection avoids reading entire file
@pytest.mark.anyio
async def test_oversized_file_stops_reading_early():
    content = b"A" * (20 * 1024 * 1024)
    file = make_upload(content)

    with pytest.raises(ValueError, match="File too large"):
        await validate_file_size(file)

    # This confirms pointer reset, not early-stop behavior.
    assert file.file.tell() == 0

@pytest.mark.anyio
async def test_oversized_file_early_stopping():
    content = b"A" * (20 * 1024 * 1024)
    file = CountingUpload(content)

    with pytest.raises(ValueError, match="File too large"):
        await validate_file_size(file)

    assert file.bytes_read == 11 * 1024 * 1024
    assert file.read_calls == 11
    assert file.file.tell() == 0

@pytest.mark.anyio
async def test_valid_pdf_signature():
    file = make_upload(b"%PDF-1.7\nSample content")

    await validate_pdf_signature(file)

    assert file.file.tell() == 0


@pytest.mark.anyio
async def test_fake_pdf_signature_rejected():
    file = make_upload(b"MZ executable content")

    with pytest.raises(
        ValueError,
        match="Invalid PDF signature",
    ):
        await validate_pdf_signature(file)

    assert file.file.tell() == 0


@pytest.mark.anyio
async def test_empty_pdf_signature_rejected():
    file = make_upload(b"")

    with pytest.raises(
        ValueError,
        match="Invalid PDF signature",
    ):
        await validate_pdf_signature(file)

    assert file.file.tell() == 0


@pytest.mark.anyio
async def test_short_pdf_signature_rejected():
    file = make_upload(b"%PDF")

    with pytest.raises(
        ValueError,
        match="Invalid PDF signature",
    ):
        await validate_pdf_signature(file)

    assert file.file.tell() == 0

@pytest.mark.anyio
async def test_valid_pdf_upload():
    content = b"%PDF-1.7\n" + b"A" * 1024
    file = make_upload(content)

    result = await validate_pdf_upload(file)

    assert result == len(content)
    assert file.file.tell() == 0


@pytest.mark.anyio
async def test_pdf_upload_rejects_fake_content():
    file = make_upload(b"MZ executable content")

    with pytest.raises(ValueError, match="Invalid PDF signature"):
        await validate_pdf_upload(file)

    assert file.file.tell() == 0


@pytest.mark.anyio
async def test_pdf_upload_rejects_wrong_extension():
    file = UploadFile(
        filename="malware.exe",
        file=BytesIO(b"%PDF-1.7\n"),
    )

    with pytest.raises(ValueError, match="Only PDF files are allowed"):
        await validate_pdf_upload(file)


@pytest.mark.anyio
async def test_pdf_upload_rejects_oversized_file():
    content = b"%PDF-1.7\n" + b"A" * MAX_FILE_SIZE
    file = make_upload(content)

    with pytest.raises(ValueError, match="File too large"):
        await validate_pdf_upload(file)

    assert file.file.tell() == 0


@pytest.mark.anyio
async def test_size_counts_entire_file_after_prior_read():
    file = make_upload(b"%PDF-" + b"A" * MAX_FILE_SIZE)
    await file.seek(MAX_FILE_SIZE)
    with pytest.raises(FileTooLargeError):
        await validate_file_size(file)
    assert file.file.tell() == 0


@pytest.mark.anyio
@pytest.mark.parametrize("content,offset,valid", [
    (b"%PDF-1.7", 5, True),
    (b"junk%PDF-1.7", 4, False),
])
async def test_signature_always_checks_start(content, offset, valid):
    file = make_upload(content)
    await file.seek(offset)
    if valid:
        await validate_pdf_signature(file)
    else:
        with pytest.raises(ValueError, match="Invalid PDF signature"):
            await validate_pdf_signature(file)
    assert file.file.tell() == 0


@pytest.mark.anyio
@pytest.mark.parametrize("validator", [validate_file_size, validate_pdf_signature])
async def test_read_error_rewinds_without_hiding_failure(validator):
    class BrokenUpload(CountingUpload):
        async def read(self, size=-1):
            self.file.seek(2)
            raise OSError("read failed")

    file = BrokenUpload(b"%PDF-1.7")
    with pytest.raises(OSError, match="read failed"):
        await validator(file)
    assert file.file.tell() == 0


@pytest.fixture
def upload_app():
    app = FastAPI()
    app.include_router(documents.router)
    principal = TenantPrincipal(user_id=uuid4(), tenant_id=uuid4())
    app.dependency_overrides[get_current_tenant_member] = lambda: principal
    return app, f"/tenants/{principal.tenant_id}/documents/upload"


@pytest.fixture
def spooled_files(monkeypatch):
    created = []
    original = formparsers.SpooledTemporaryFile

    def track(*args, **kwargs):
        file = original(*args, **kwargs)
        created.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track)
    return created


@pytest.mark.parametrize("failure,status", [
    (FileTooLargeError("Changed size message"), 413),
    (ValueError("internal sensitive detail"), 500),
])
def test_route_uses_error_type_not_message(upload_app, monkeypatch, failure, status):
    async def fail(file):
        raise failure

    monkeypatch.setattr(documents, "validate_pdf_upload", fail)
    app, path = upload_app
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(path, files={"file": ("test.pdf", b"%PDF-")})
    assert response.status_code == status
    assert "internal sensitive detail" not in response.text


@pytest.mark.parametrize("content,denied,status", [
    (b"%PDF-1.7", False, 200),
    (b"invalid", False, 400),
    (b"%PDF-1.7", True, 403),
])
def test_framework_closes_uploads(upload_app, spooled_files, content, denied, status):
    app, path = upload_app
    if denied:
        def deny():
            raise HTTPException(403, "Tenant access denied")
        app.dependency_overrides[get_current_tenant_member] = deny
    with TestClient(app) as client:
        response = client.post(path, files={"file": ("test.pdf", content)})
    assert response.status_code == status
    assert spooled_files and all(file.closed for file in spooled_files)


@pytest.mark.anyio
@pytest.mark.parametrize("declared_length", [None, b"1", b"99999999"])
async def test_body_limit_before_auth_with_untrusted_length(
    upload_app, spooled_files, declared_length,
):
    app, path = upload_app
    def must_not_authorize():
        pytest.fail("Oversized request reached authorization")
    app.dependency_overrides[get_current_tenant_member] = must_not_authorize
    headers = [(b"content-type", b"multipart/form-data; boundary=test")]
    if declared_length is not None:
        headers.append((b"content-length", declared_length))
    prefix = (b'--test\r\nContent-Disposition: form-data; name="file"; '
              b'filename="test.pdf"\r\n\r\n%PDF-')
    chunks = iter([prefix] + [b"A" * (1024 * 1024)] * 12)
    reads = 0
    async def receive():
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": next(chunks), "more_body": True}
    messages = []
    async def send(message):
        messages.append(message)
    await app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "POST", "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": headers,
        "client": ("127.0.0.1", 1), "server": ("test", 80),
    }, receive, send)
    assert next(m["status"] for m in messages if m["type"] == "http.response.start") == 413
    assert reads <= 12
    if declared_length != b"99999999":
        assert spooled_files
    assert all(file.closed for file in spooled_files)
