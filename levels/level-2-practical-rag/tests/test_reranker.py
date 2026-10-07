from services.reranker import (
    calculate_reranker_score,
    rerank,
    rerank_with_cross_encoder,
)

class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.received_pairs = None

    def predict(self, pairs):
        self.received_pairs = pairs
        return self.scores

def test_calculate_reranker_score_counts_matching_words():
    query = "annual leave days"
    chunk = "Employees receive 18 days of annual leave per year."

    score = calculate_reranker_score(query, chunk)

    assert score == 3


def test_calculate_reranker_score_is_case_insensitive():
    query = "Annual Leave"
    chunk = "Employees receive annual leave every year."

    score = calculate_reranker_score(query, chunk)

    assert score == 2


def test_calculate_reranker_score_returns_zero_for_no_match():
    query = "annual leave"
    chunk = "Employees can access the HR portal."

    score = calculate_reranker_score(query, chunk)

    assert score == 0


def test_calculate_reranker_score_counts_unique_matching_words():
    query = "leave leave annual"
    chunk = "Annual leave leave policy."

    score = calculate_reranker_score(query, chunk)

    assert score == 2


def test_rerank_adds_reranker_score():
    query = "annual leave days"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Employees receive annual leave days.",
            },
            "hybrid_score": 0.80,
        }
    ]

    results = rerank(query, candidates)

    assert results[0]["reranker_score"] == 3
    assert results[0]["hybrid_score"] == 0.80


def test_rerank_sorts_by_reranker_score():
    query = "annual leave days"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Employees can request leave.",
            },
            "hybrid_score": 0.90,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 1,
                "chunk": "Employees receive annual leave days.",
            },
            "hybrid_score": 0.70,
        },
    ]

    results = rerank(query, candidates)

    assert results[0]["chunk"]["chunk_index"] == 1
    assert results[0]["reranker_score"] == 3
    assert results[1]["chunk"]["chunk_index"] == 0
    assert results[1]["reranker_score"] == 1


def test_rerank_respects_top_k():
    query = "leave"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Annual leave policy.",
            },
            "hybrid_score": 0.80,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 1,
                "chunk": "Sick leave policy.",
            },
            "hybrid_score": 0.70,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 2,
                "chunk": "Holiday calendar.",
            },
            "hybrid_score": 0.60,
        },
    ]

    results = rerank(query, candidates, top_k=2)

    assert len(results) == 2             
    
def test_rerank_with_cross_encoder_sends_query_chunk_pairs():
    query = "annual leave days"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Employees receive annual leave days.",
            },
            "hybrid_score": 0.80,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 1,
                "chunk": "Employees can request leave.",
            },
            "hybrid_score": 0.70,
        },
    ]

    model = FakeCrossEncoder([0.9, 0.2])

    rerank_with_cross_encoder(query, candidates, model)

    assert model.received_pairs == [
        (
            "annual leave days",
            "Employees receive annual leave days.",
        ),
        (
            "annual leave days",
            "Employees can request leave.",
        ),
    ]


def test_rerank_with_cross_encoder_adds_scores_and_sorts():
    query = "annual leave days"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Employees can request leave.",
            },
            "hybrid_score": 0.90,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 1,
                "chunk": "Employees receive annual leave days.",
            },
            "hybrid_score": 0.70,
        },
    ]

    model = FakeCrossEncoder([0.2, 0.9])

    results = rerank_with_cross_encoder(
        query,
        candidates,
        model,
    )

    assert results[0]["chunk"]["chunk_index"] == 1
    assert results[0]["reranker_score"] == 0.9

    assert results[1]["chunk"]["chunk_index"] == 0
    assert results[1]["reranker_score"] == 0.2


def test_rerank_with_cross_encoder_preserves_existing_fields():
    query = "annual leave"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Annual leave policy.",
            },
            "hybrid_score": 0.85,
        }
    ]

    model = FakeCrossEncoder([0.95])

    results = rerank_with_cross_encoder(
        query,
        candidates,
        model,
    )

    assert results[0]["hybrid_score"] == 0.85
    assert results[0]["reranker_score"] == 0.95


def test_rerank_with_cross_encoder_respects_top_k():
    query = "leave"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Annual leave policy.",
            },
            "hybrid_score": 0.80,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 1,
                "chunk": "Sick leave policy.",
            },
            "hybrid_score": 0.70,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 2,
                "chunk": "Holiday calendar.",
            },
            "hybrid_score": 0.60,
        },
    ]

    model = FakeCrossEncoder([0.8, 0.7, 0.1])

    results = rerank_with_cross_encoder(
        query,
        candidates,
        model,
        top_k=2,
    )

    assert len(results) == 2
    assert results[0]["chunk"]["chunk_index"] == 0
    assert results[1]["chunk"]["chunk_index"] == 1
    
def test_rerank_with_cross_encoder_returns_empty_for_no_candidates():
    model = FakeCrossEncoder([])

    results = rerank_with_cross_encoder(
        "annual leave",
        [],
        model,
    )

    assert results == []
    assert model.received_pairs is None
    
def test_rerank_with_cross_encoder_rejects_score_count_mismatch():
    query = "annual leave"

    candidates = [
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 0,
                "chunk": "Annual leave policy.",
            },
            "hybrid_score": 0.80,
        },
        {
            "chunk": {
                "source": "handbook",
                "chunk_index": 1,
                "chunk": "Sick leave policy.",
            },
            "hybrid_score": 0.70,
        },
    ]

    model = FakeCrossEncoder([0.95])

    try:
        rerank_with_cross_encoder(
            query,
            candidates,
            model,
        )
        assert False, "Expected ValueError"
    except ValueError as error:
        assert str(error) == (
            "Number of reranker scores must match number of candidates"
        )