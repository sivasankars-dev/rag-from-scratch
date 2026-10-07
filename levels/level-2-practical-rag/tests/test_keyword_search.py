from services.keyword_search import search_keywords


def test_search_keywords_returns_matching_chunks():
    chunks = [
        {"chunk": "Employees receive annual leave."},
        {"chunk": "Employees receive health insurance."},
    ]

    results = search_keywords("annual leave", chunks)

    assert len(results) == 1
    assert results[0]["chunk"]["chunk"] == "Employees receive annual leave."
    assert results[0]["score"] == 2


def test_search_keywords_ranks_by_match_score():
    chunks = [
        {"chunk": "Employees receive annual leave."},
        {"chunk": "Employees receive annual leave according to company policy."},
        {"chunk": "Health insurance is provided."},
    ]

    results = search_keywords("annual leave policy", chunks)

    assert len(results) == 2
    assert results[0]["score"] == 3
    assert results[1]["score"] == 2


def test_search_keywords_is_case_insensitive():
    chunks = [
        {"chunk": "Annual Leave is available to employees."},
    ]

    results = search_keywords("annual leave", chunks)

    assert len(results) == 1
    assert results[0]["score"] == 2


def test_search_keywords_respects_top_k():
    chunks = [
        {"chunk": "annual leave policy"},
        {"chunk": "annual leave"},
        {"chunk": "annual policy"},
    ]

    results = search_keywords("annual leave policy", chunks, top_k=2)

    assert len(results) == 2


def test_search_keywords_returns_empty_for_no_match():
    chunks = [
        {"chunk": "Employees receive health insurance."},
    ]

    results = search_keywords("annual leave", chunks)

    assert results == []
    
def test_search_keywords_preserves_chunk_metadata():
    chunks = [
        {
            "chunk": "Employees receive annual leave.",
            "source": "employee_handbook.pdf",
            "document_type": "hr_policy",
            "page_number": 2,
            "chunk_index": 3,
        }
    ]

    results = search_keywords("annual leave", chunks)

    assert len(results) == 1

    result_chunk = results[0]["chunk"]

    assert result_chunk["source"] == "employee_handbook.pdf"
    assert result_chunk["document_type"] == "hr_policy"
    assert result_chunk["page_number"] == 2
    assert result_chunk["chunk_index"] == 3