from services.hybrid_search import (
    merge_search_results,
    convert_distance_to_similarity,
    normalize_keyword_scores,
    calculate_hybrid_scores,
    hybrid_search
)

def test_merge_search_results_combines_results_from_both_searches():
    semantic_results = [
        {
            "chunk": {
                "chunk": "annual leave policy",
                "chunk_index": 1,
                "source": "employee_handbook.pdf",
            },
            "score": 0.90,
        },
        {
            "chunk": {
                "chunk": "health insurance",
                "chunk_index": 2,
                "source": "employee_handbook.pdf",
            },
            "score": 0.80,
        },
    ]

    keyword_results = [
        {
            "chunk": {
                "chunk": "annual leave policy",
                "chunk_index": 1,
                "source": "employee_handbook.pdf",
            },
            "score": 3,
        },
        {
            "chunk": {
                "chunk": "remote work policy",
                "chunk_index": 3,
                "source": "employee_handbook.pdf",
            },
            "score": 2,
        },
    ]

    results = merge_search_results(
        semantic_results,
        keyword_results,
    )
    
    assert len(results) == 3

    assert results[0]["semantic_score"] == 0.90
    assert results[0]["keyword_score"] == 3

    assert results[1]["semantic_score"] == 0.80
    assert results[1]["keyword_score"] == 0

    assert results[2]["semantic_score"] == 0
    assert results[2]["keyword_score"] == 2
    
def test_merge_search_results_keeps_same_chunk_index_from_different_sources_separate():
    semantic_results = [
        {
            "chunk": {
                "chunk": "annual leave",
                "source": "employee_handbook.pdf",
                "chunk_index": 1,
            },
            "score": 0.90,
        }
    ]

    keyword_results = [
        {
            "chunk": {
                "chunk": "annual leave",
                "source": "leave_policy.pdf",
                "chunk_index": 1,
            },
            "score": 2,
        }
    ]

    results = merge_search_results(
        semantic_results,
        keyword_results,
    )

    assert len(results) == 2

def test_normalize_keyword_scores():
    results = [
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 1},
            "semantic_score": 0.8,
            "keyword_score": 3,
        },
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 2},
            "semantic_score": 0.7,
            "keyword_score": 2,
        },
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 3},
            "semantic_score": 0.6,
            "keyword_score": 1,
        },
    ]

    normalized = normalize_keyword_scores(results)

    assert normalized[0]["keyword_score"] == 1.0
    assert normalized[1]["keyword_score"] == 2 / 3
    assert normalized[2]["keyword_score"] == 1 / 3
    
def test_normalize_keyword_scores_handles_empty_results():
    assert normalize_keyword_scores([]) == []
    
def test_convert_distance_to_similarity():
    results = [
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 1},
            "semantic_score": 0.10,
            "keyword_score": 0,
        },
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 2},
            "semantic_score": 0.30,
            "keyword_score": 0,
        },
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 3},
            "semantic_score": 0.60,
            "keyword_score": 0,
        },
    ]

    converted = convert_distance_to_similarity(results)

    assert converted[0]["semantic_score"] == 0.90
    assert converted[1]["semantic_score"] == 0.70
    assert converted[2]["semantic_score"] == 0.40

def test_calculate_hybrid_scores():
    results = [
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 1},
            "semantic_score": 0.90,
            "keyword_score": 0.33,
        },
        {
            "chunk": {"source": "doc.pdf", "chunk_index": 2},
            "semantic_score": 0.70,
            "keyword_score": 1.00,
        },
    ]

    scored = calculate_hybrid_scores(results)

    assert scored[0]["chunk"]["chunk_index"] == 2
    assert scored[0]["hybrid_score"] == 0.85

    assert scored[1]["chunk"]["chunk_index"] == 1
    assert scored[1]["hybrid_score"] == 0.615
    
def test_hybrid_search_combines_and_ranks_results():
    semantic_results = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
            },
            "score": 0.10,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 1,
            },
            "score": 0.30,
        },
    ]

    keyword_results = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
            },
            "score": 2,
            "matched_words": ["leave", "policy"],
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 2,
            },
            "score": 3,
            "matched_words": ["leave", "policy", "approval"],
        },
    ]

    results = hybrid_search(
        semantic_results,
        keyword_results,
        top_k=2,
    )

    assert len(results) == 2

    assert results[0]["chunk"]["chunk_index"] == 2
    assert results[0]["hybrid_score"] > results[1]["hybrid_score"]