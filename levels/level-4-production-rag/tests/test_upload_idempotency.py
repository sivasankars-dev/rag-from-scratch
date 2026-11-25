import hashlib
from io import BytesIO

import pytest

from services.upload_idempotency import fingerprint_pdf_upload


def fingerprint(content=b"%PDF-1.7\npayload", title="report.pdf"):
    return fingerprint_pdf_upload(source=BytesIO(content), size_bytes=len(content), title=title)


def test_identical_inputs_are_deterministic():
    result = fingerprint()
    assert result == fingerprint()
    assert result.version == 1
    assert result.content_sha256 == hashlib.sha256(b"%PDF-1.7\npayload").hexdigest()
    assert len(result.fingerprint) == 64


def test_different_bytes_same_size_change_fingerprint():
    assert fingerprint(b"%PDF-a").fingerprint != fingerprint(b"%PDF-b").fingerprint


def test_different_title_changes_fingerprint():
    assert fingerprint(title="a.pdf").fingerprint != fingerprint(title="b.pdf").fingerprint


def test_ambiguous_concatenation_is_separated():
    # Both naive title + decimal size encodings are "report.pdf123".
    assert "report.pdf1" + str(23) == "report.pdf" + str(123)
    assert fingerprint(b"%PDF-" + b"x" * 18, "report.pdf1").fingerprint != fingerprint(b"%PDF-" + b"x" * 118, "report.pdf").fingerprint


def test_encoding_contract_is_length_prefixed():
    content = b"%PDF-data"
    title = "résumé.pdf"
    fields = [title.encode(), str(len(content)).encode(), hashlib.sha256(content).digest()]
    encoded = b"production-rag/pdf-upload/v1\x00" + b"".join(len(f).to_bytes(8, "big") + f for f in fields)
    assert fingerprint(content, title).fingerprint == hashlib.sha256(encoded).hexdigest()


@pytest.mark.parametrize("declared", [1, 100])
def test_size_mismatch_restores_position(declared):
    source = BytesIO(b"%PDF-data")
    source.seek(3)
    with pytest.raises(ValueError, match="size"):
        fingerprint_pdf_upload(source=source, size_bytes=declared, title="a.pdf")
    assert source.tell() == 3


def test_success_hashes_whole_stream_and_restores_position():
    source = BytesIO(b"%PDF-data")
    source.seek(4)
    assert fingerprint_pdf_upload(source=source, size_bytes=9, title="report.pdf") == fingerprint(b"%PDF-data")
    assert source.tell() == 4


def test_v1_golden_vector():
    result = fingerprint(b"%PDF-data", "résumé.pdf")
    assert result.version == 1
    assert result.size_bytes == 9
    assert result.fingerprint == "51a7aa9d7b33f9d2346333f51b10eba210bd5e1fd8a93940e4df0518aa5005f6"
