import pytest
from services.source_citation import (
    build_source_citation,
    build_source_citations,
)


def test_build_source_citation():
    metadata = {
        "source": "employee_handbook.pdf",
        "page_number": 2,
        "chunk_index": 3,
    }

    citation = build_source_citation(metadata)

    assert citation == (
        "Source: employee_handbook.pdf, Page: 2, Chunk: 3"
    )
    
def test_build_source_citation_raises_error_when_chunk_index_is_missing():
    metadata = {
        "source": "employee_handbook.pdf",
        "page_number": 2,
    }

    with pytest.raises(KeyError):
        build_source_citation(metadata)
        
def test_build_multiple_source_citations():
    metadata_list = [
        {
            "source": "employee_handbook.pdf",
            "page_number": 2,
            "chunk_index": 3,
        },
        {
            "source": "leave_policy.pdf",
            "page_number": 1,
            "chunk_index": 0,
        },
    ]

    citations = [
        build_source_citation(metadata)
        for metadata in metadata_list
    ]

    assert citations == [
        "Source: employee_handbook.pdf, Page: 2, Chunk: 3",
        "Source: leave_policy.pdf, Page: 1, Chunk: 0",
    ]
    
from services.source_citation import (
    build_source_citation,
    build_source_citations,
)


def test_build_source_citations():
    metadata_list = [
        {
            "source": "employee_handbook.pdf",
            "page_number": 2,
            "chunk_index": 3,
        },
        {
            "source": "leave_policy.pdf",
            "page_number": 1,
            "chunk_index": 0,
        },
    ]

    citations = build_source_citations(metadata_list)

    assert citations == [
        "Source: employee_handbook.pdf, Page: 2, Chunk: 3",
        "Source: leave_policy.pdf, Page: 1, Chunk: 0",
    ]
    
def test_build_source_citations_with_empty_list():
    citations = build_source_citations([])

    assert citations == []
    
def test_build_source_citations_from_retrieval_results():
    results = {
        "metadatas": [
            [
                {
                    "source": "employee_handbook.pdf",
                    "page_number": 2,
                    "chunk_index": 3,
                },
                {
                    "source": "leave_policy.pdf",
                    "page_number": 1,
                    "chunk_index": 0,
                },
            ]
        ]
    }

    citations = build_source_citations(results["metadatas"][0])

    assert citations == [
        "Source: employee_handbook.pdf, Page: 2, Chunk: 3",
        "Source: leave_policy.pdf, Page: 1, Chunk: 0",
    ]