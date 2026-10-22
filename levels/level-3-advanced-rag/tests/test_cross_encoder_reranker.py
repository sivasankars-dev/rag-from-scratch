
import pytest

from services.cross_encoder_reranker import CrossEncoderReranker


class FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.received_pairs = None
        self.predict_calls = 0

    def predict(self, pairs):
        self.predict_calls += 1
        self.received_pairs = pairs
        return self.scores


def make_candidate(index, document, score=0.01):
    return {
        "document": document,
        "metadata": {
            "source": "handbook.pdf",
            "chunk_index": index,
        },
        "score": score,
    }


def test_rerank_sorts_by_cross_encoder_score():
    candidates = [
        make_candidate(0, "Annual leave is 12 days.", 0.03),
        make_candidate(1, "Sick leave is 10 days.", 0.02),
        make_candidate(2, "Annual leave requires approval.", 0.01),
    ]
    model = FakeCrossEncoder([1.2, 0.4, 4.8])
    reranker = CrossEncoderReranker(model)

    results = reranker.rerank(
        query="What is the annual leave policy?",
        candidates=candidates,
        top_n=3,
    )

    assert [item["metadata"]["chunk_index"] for item in results] == [
        2, 0, 1
    ]
    assert [item["reranker_score"] for item in results] == [
        4.8, 1.2, 0.4
    ]


def test_rerank_passes_query_document_pairs_to_model():
    candidates = [
        make_candidate(0, "Annual leave is 12 days."),
        make_candidate(1, "Sick leave is 10 days."),
    ]
    model = FakeCrossEncoder([0.8, 0.3])
    reranker = CrossEncoderReranker(model)

    reranker.rerank(
        "How many annual leave days?",
        candidates,
        top_n=2,
    )

    assert model.received_pairs == [
        ("How many annual leave days?", "Annual leave is 12 days."),
        ("How many annual leave days?", "Sick leave is 10 days."),
    ]


def test_rerank_preserves_existing_fields_without_mutating_candidates():
    candidate = make_candidate(0, "Annual leave is 12 days.", 0.025)
    original = {
        **candidate,
        "metadata": dict(candidate["metadata"]),
    }
    reranker = CrossEncoderReranker(FakeCrossEncoder([2.5]))

    results = reranker.rerank("annual leave", [candidate], top_n=1)

    assert results[0]["score"] == 0.025
    assert results[0]["metadata"] == candidate["metadata"]
    assert results[0]["reranker_score"] == 2.5
    assert candidate == original
    assert "reranker_score" not in candidate


def test_rerank_returns_only_top_n_candidates():
    candidates = [
        make_candidate(0, "Document A"),
        make_candidate(1, "Document B"),
        make_candidate(2, "Document C"),
    ]
    reranker = CrossEncoderReranker(FakeCrossEncoder([1.0, 5.0, 3.0]))

    results = reranker.rerank("query", candidates, top_n=2)

    assert len(results) == 2
    assert [item["metadata"]["chunk_index"] for item in results] == [1, 2]


def test_empty_candidates_return_empty_without_calling_model():
    model = FakeCrossEncoder([])
    reranker = CrossEncoderReranker(model)

    assert reranker.rerank("query", [], top_n=3) == []
    assert model.predict_calls == 0


@pytest.mark.parametrize("top_n", [0, -1, 1.5, True])
def test_invalid_top_n_raises_value_error(top_n):
    reranker = CrossEncoderReranker(FakeCrossEncoder([]))

    with pytest.raises(ValueError, match="top_n must be a positive integer"):
        reranker.rerank("query", [], top_n=top_n)


def test_none_model_is_rejected():
    with pytest.raises(ValueError, match="model must not be None"):
        CrossEncoderReranker(None)


def test_mismatched_score_count_raises_value_error():
    candidates = [
        make_candidate(0, "Document A"),
        make_candidate(1, "Document B"),
    ]
    reranker = CrossEncoderReranker(FakeCrossEncoder([0.8]))

    with pytest.raises(
        ValueError,
        match="Number of reranker scores must match number of candidates",
    ):
        reranker.rerank("query", candidates, top_n=2)


def test_top_n_larger_than_candidates_returns_all():
    candidates = [
        make_candidate(0, "Document A"),
        make_candidate(1, "Document B"),
    ]
    reranker = CrossEncoderReranker(FakeCrossEncoder([0.8, 0.3]))

    results = reranker.rerank("query", candidates, top_n=5)

    assert len(results) == 2
