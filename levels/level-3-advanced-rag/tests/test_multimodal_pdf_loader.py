from pathlib import Path

import pymupdf
import pytest

from services.multimodal.multimodal_pdf_loader import load_pdf_records
from services.multimodal.table_serializer import normalize_cell, serialize_table


def test_normalize_cell_repairs_whitespace_and_severity():
    assert normalize_cell("Criticalcustomerorbusinessimpact") == (
        "Criticalcustomerorbusinessimpact"
    )
    assert normalize_cell("SEV1\n-") == "SEV-1"
    assert normalize_cell("  customer \n impact  ") == "customer impact"


def test_serialize_table_preserves_header_value_relationships():
    result = serialize_table(
        [
            ["Severity", "Typical Meaning", "Initial Response"],
            [
                "SEV1\n-",
                "Critical customer or business impact",
                "Immediate response and incident leadership",
            ],
        ]
    )

    assert "Severity: SEV-1" in result
    assert "Typical Meaning: Critical customer or business impact" in result
    assert "Initial Response: Immediate response and incident leadership" in result


def test_serialize_table_handles_empty_input():
    assert serialize_table([]) == ""
    assert serialize_table(None) == ""


def test_serialize_table_rejects_invalid_rows():
    with pytest.raises(ValueError):
        serialize_table([["Header"], "not-a-row"])


def test_load_pdf_records_extracts_handbook_page_eight():
    pdf_path = Path("data/documents/rag_practice_employee_handbook.pdf")
    if not pdf_path.is_file():
        pytest.skip("Sample handbook PDF is not available")

    records = load_pdf_records(pdf_path)

    table_records = [
        record
        for record in records
        if record["page_number"] == 8 and record["content_type"] == "table"
    ]

    assert len(table_records) == 1

    table_record = table_records[0]
    assert table_record["source"] == pdf_path.name
    assert "Severity: SEV-1" in table_record["text"]
    assert "Critical customer or business impact" in table_record["text"]
    assert "Initial response and incident leadership" not in table_record["text"]


def test_load_pdf_records_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pdf_records(tmp_path / "missing.pdf")


def test_load_pdf_records_has_unique_record_ids():
    pdf_path = Path("data/documents/rag_practice_employee_handbook.pdf")
    if not pdf_path.is_file():
        pytest.skip("Sample handbook PDF is not available")

    records = load_pdf_records(pdf_path)
    record_ids = [record["record_id"] for record in records]

    assert len(record_ids) == len(set(record_ids))


def test_load_pdf_records_preserves_page_and_content_type_metadata():
    pdf_path = Path("data/documents/rag_practice_employee_handbook.pdf")
    if not pdf_path.is_file():
        pytest.skip("Sample handbook PDF is not available")

    records = load_pdf_records(pdf_path)

    assert all(record["source"] == pdf_path.name for record in records)
    assert all(record["page_number"] >= 1 for record in records)
    assert all(record["content_type"] in {"text", "table", "table_row"} for record in records)
    assert all(record["text"].strip() for record in records)
    row_records = [
        record for record in records
        if record["content_type"] == "table_row"
    ]

    assert row_records
    assert all(record["table_id"] for record in row_records)
    assert all(record["row_number"] >= 1 for record in row_records)

def test_table_record_preserves_column_relationships():
    pdf_path = Path("data/documents/rag_practice_employee_handbook.pdf")
    if not pdf_path.is_file():
        pytest.skip("Sample handbook PDF is not available")

    records = load_pdf_records(pdf_path)
    table_records = [record for record in records if record["content_type"] == "table"]

    assert table_records

    table_text = "\n".join(record["text"] for record in table_records)

    assert "Severity: SEV-1" in table_text
    assert "Typical Meaning: Critical customer or business impact" in table_text
    assert "Initial Response: Immediate response and incident leadership" in table_text


def test_load_pdf_records_deduplicates_table_content_from_page_text():
    pdf_path = Path("data/documents/rag_practice_employee_handbook.pdf")
    if not pdf_path.is_file():
        pytest.skip("Sample handbook PDF is not available")

    records = load_pdf_records(pdf_path)

    page_eight_text = next(
        record["text"]
        for record in records
        if record["page_number"] == 8 and record["content_type"] == "text"
    )
    page_eight_table = next(
        record["text"]
        for record in records
        if record["page_number"] == 8 and record["content_type"] == "table"
    )

    assert "7.1 Severity" in page_eight_text
    assert "7.2 Incident Process" in page_eight_text
    assert "Immediate response and incident leadership" not in page_eight_text

    assert "Immediate response and incident leadership" in page_eight_table
    assert "Severity: SEV-1" in page_eight_table
