
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    ROOT
    / "levels"
    / "level-3-advanced-rag"
    / "scripts"
    / "run_graph_ingestion.py"
)

spec = importlib.util.spec_from_file_location(
    "graph_ingestion_script",
    SCRIPT_PATH,
)
graph_ingestion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_ingestion)


@pytest.fixture
def sections():
    return [
        {
            "section_id": "handbook::preamble",
            "document_id": "handbook.pdf",
            "section_number": None,
            "section_title": "Introduction",
            "section_type": "preamble",
            "section_path": "Introduction",
            "start_page": 1,
            "end_page": 1,
            "text": "Introduction text.",
        },
        {
            "section_id": "handbook::section::2_2",
            "document_id": "handbook.pdf",
            "section_number": "2.2",
            "section_title": "Remote Work",
            "section_type": "section",
            "section_path": "Working Arrangements > Remote Work",
            "start_page": 3,
            "end_page": 3,
            "text": "Remote employees must protect company information.",
        },
        {
            "section_id": "handbook::section::3",
            "document_id": "handbook.pdf",
            "section_number": "3",
            "section_title": "Leave Policy",
            "section_type": "section",
            "section_path": "Leave Policy",
            "start_page": 4,
            "end_page": 5,
            "text": "Employees can request leave.",
        },
        {
            "section_id": "handbook::faq",
            "document_id": "handbook.pdf",
            "section_number": "4",
            "section_title": "Frequently Asked Questions",
            "section_type": "faq",
            "section_path": "Frequently Asked Questions",
            "start_page": 6,
            "end_page": 7,
            "text": "FAQ introduction.",
        },
        {
            "section_id": "handbook::faq::1",
            "document_id": "handbook.pdf",
            "section_number": None,
            "section_title": "How do I request leave?",
            "section_type": "faq_item",
            "section_path": "Frequently Asked Questions > How do I request leave?",
            "start_page": 6,
            "end_page": 6,
            "text": "Submit a leave request through the HR system.",
        },
    ]


def test_selects_only_requested_numbered_section(sections):
    selected = graph_ingestion.select_sections(
        sections,
        section_number="2.2",
    )

    assert len(selected) == 1
    assert selected[0]["section_title"] == "Remote Work"


def test_all_sections_excludes_preamble_and_faq_parent(sections):
    selected = graph_ingestion.select_sections(
        sections,
        all_sections=True,
    )

    assert [item["section_type"] for item in selected] == [
        "section",
        "section",
        "faq_item",
    ]


def test_missing_section_number_raises_helpful_error(sections):
    with pytest.raises(ValueError, match="not found"):
        graph_ingestion.select_sections(
            sections,
            section_number="99",
        )


def test_selection_requires_explicit_scope(sections):
    with pytest.raises(ValueError, match="Choose"):
        graph_ingestion.select_sections(sections)


def test_build_metadata_preserves_source_and_page_information(sections):
    metadata = graph_ingestion.build_metadata(sections[1])

    assert metadata["source"] == "handbook.pdf"
    assert metadata["section_id"] == "handbook::section::2_2"
    assert metadata["section_path"] == (
        "Working Arrangements > Remote Work"
    )
    assert metadata["start_page"] == 3
    assert metadata["end_page"] == 3
