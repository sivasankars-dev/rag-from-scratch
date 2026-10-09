import pytest
from services.retrieval_evaluator import (
    is_expected_chunk_retrieved,
    calculate_hit_rate,
    evaluate_hit_rate,
    evaluate_retrieval_hit_rate,
    calculate_mrr,
    calculate_reciprocal_rank,
    find_expected_chunk_rank,
)

class FakeEmbeddingService:
    def embed_text(self, text):
        return [1.0, 0.0, 0.0]

class FakeRetrievalService:
    def __init__(self, results):
        self.results = results
        self.call_count = 0

    def retrieve(self, query_embedding, top_k=2):
        result = self.results[self.call_count]
        self.call_count += 1
        return result


def test_expected_source_and_chunk_matched():
    retrieved_metadata = [
        {"source": "company_policy.pdf", "chunk_index": 0},
        {"source": "employee_handbook.pdf", "chunk_index": 2},
        {"source": "company_policy.pdf", "chunk_index": 2},
    ]

    expected_source = "company_policy.pdf"
    expected_chunk = 2

    result = is_expected_chunk_retrieved(retrieved_metadata, expected_source, expected_chunk)

    assert result == True

def test_expected_chunk_matched_but_source_not():
    retrieved_metadata = [
        {"source": "company_policy.pdf", "chunk_index": 0},
        {"source": "employee_handbook.pdf", "chunk_index": 2},
        {"source": "employee_handbook.pdf", "chunk_index": 2},
    ]

    expected_source = "company_policy.pdf"
    expected_chunk = 2

    result = is_expected_chunk_retrieved(retrieved_metadata, expected_source, expected_chunk)

    assert result == False

def test_retrieved_metadata_is_empty():
    retrieved_metadata = []

    expected_source = "company_policy.pdf"
    expected_chunk = 2

    result = is_expected_chunk_retrieved(retrieved_metadata, expected_source, expected_chunk)

    assert result == False

def test_calculate_hit_rate():
    hit_results = [True, True, False, True, False]

    result = calculate_hit_rate(hit_results)

    assert result == pytest.approx(0.6)

def test_calculate_hit_rate_when_hit_results_are_true():
    hit_results = [True, True]

    result = calculate_hit_rate(hit_results)

    assert result == pytest.approx(1.0)

def test_calculate_hit_rate_when_hit_results_are_false():
    hit_results = [False, False, False]

    result = calculate_hit_rate(hit_results)

    assert result == pytest.approx(0.0)

def test_calculate_hit_rate_when_hit_results_are_empty():
    hit_results = []

    result = calculate_hit_rate(hit_results)

    assert result == pytest.approx(0.0)

def test_evaluate_hit_rate():
    evaluation_cases = [
        {
        "expected_source": "company_policy.pdf",
        "expected_chunk": 2,
        },
        {
        "expected_source": "company_policy.pdf",
        "expected_chunk": 3,
        },
    ]

    retrieved_metadata_by_case = [
    [
        {"source": "company_policy.pdf", "chunk_index": 2},
        {"source": "company_policy.pdf", "chunk_index": 0},
    ],
    [
        {"source": "employee_handbook.pdf", "chunk_index": 3},
    ],
]

    result = evaluate_hit_rate(
        evaluation_cases,
        retrieved_metadata_by_case,
    )

    assert result == pytest.approx(0.5)

def test_evaluate_hit_rate_when_all_questions_match():
    evaluation_cases = [
        {
        "expected_source": "company_policy.pdf",
        "expected_chunk": 2,
        },
        {
        "expected_source": "company_policy.pdf",
        "expected_chunk": 3,
        },
    ]

    retrieved_metadata_by_case = [
        [{"source": "company_policy.pdf", "chunk_index": 2}],
        [{"source": "company_policy.pdf", "chunk_index": 3}],
    ]

    result = evaluate_hit_rate(
        evaluation_cases,
        retrieved_metadata_by_case,
    )

    assert result == pytest.approx(1.0)

def test_evaluate_hit_rate_when_no_questions_match():
    evaluation_cases = [
        {
        "expected_source": "company_policy.pdf",
        "expected_chunk": 2,
        },
        {
        "expected_source": "company_policy.pdf",
        "expected_chunk": 3,
        },
    ]

    retrieved_metadata_by_case = [
        [{"source": "employee_handbook.pdf", "chunk_index": 2}],
        [{"source": "company_policy.pdf", "chunk_index": 1}],
    ]

    result = evaluate_hit_rate(
        evaluation_cases,
        retrieved_metadata_by_case,
    )

    assert result == pytest.approx(0.0)

def test_extract_retrieved_metadata_from_vector_store_result():
    retrieval_result = {
        "documents": [["Annual leave policy"]],
        "metadatas": [[
            {
            "source": "company_policy.pdf",
            "chunk_index": 2,
            "page_number": 1,
            }
        ]],
    }

    retrieved_metadata = retrieval_result["metadatas"][0]

    assert retrieved_metadata[0]["source"] == "company_policy.pdf"
    assert retrieved_metadata[0]["chunk_index"] == 2

def test_evaluate_retrieval_hit_rate():
    evaluation_cases = [
        {
        "question": "What is the policy name?",
        "expected_source": "company_policy.pdf",
        "expected_chunk": 0,
        },
        {
        "question": "How many sick leave days?",
        "expected_source": "company_policy.pdf",
        "expected_chunk": 2,
        },
    ]

    fake_results = [
        {
            "metadatas": [[
                {
                    "source": "company_policy.pdf",
                    "chunk_index": 0,
                }
            ]]
        },
        {
            "metadatas": [[
                {
                    "source": "company_policy.pdf",
                    "chunk_index": 1,
                }
            ]]
        },
    ]

    embedding_service = FakeEmbeddingService()
    retrieval_service = FakeRetrievalService(fake_results)

    result = evaluate_retrieval_hit_rate(
        evaluation_cases,
        embedding_service,
        retrieval_service,
        top_k=2,
    )

    assert result == pytest.approx(0.5)
    assert retrieval_service.call_count == 2

def test_evaluate_retrieval_hit_rate_with_empty_dataset():
    result = evaluate_retrieval_hit_rate(
        evaluation_cases=[],
        embedding_service=FakeEmbeddingService(),
        retrieval_service=FakeRetrievalService([]),
    )

    assert result == pytest.approx(0.0)

def test_mrr_when_all_expected_chunks_are_rank_one():
    reciprocal_ranks = [1.0, 1.0, 1.0]

    assert calculate_mrr(reciprocal_ranks) == 1.0


def test_mrr_when_expected_chunks_have_different_ranks():
    reciprocal_ranks = [1.0, 0.5, 1 / 3]

    expected = (1.0 + 0.5 + 1 / 3) / 3

    assert calculate_mrr(reciprocal_ranks) == expected


def test_mrr_when_expected_chunk_is_not_found():
    reciprocal_ranks = [1.0, 0.0, 0.0]
    assert calculate_mrr(reciprocal_ranks) == pytest.approx(1 / 3)

def test_reciprocal_rank_when_expected_chunk_is_first():
    assert calculate_reciprocal_rank(1) == 1.0


def test_reciprocal_rank_when_expected_chunk_is_second():
    assert calculate_reciprocal_rank(2) == 0.5


def test_reciprocal_rank_when_expected_chunk_is_third():
    assert calculate_reciprocal_rank(3) == 1 / 3


def test_reciprocal_rank_when_expected_chunk_is_not_found():
    assert calculate_reciprocal_rank(None) == 0.0

def test_expected_chunk_is_rank_one():
    assert find_expected_chunk_rank([12, 13, 4], 12) == 1


def test_expected_chunk_is_rank_two():
    assert find_expected_chunk_rank([12, 13, 4], 13) == 2


def test_expected_chunk_is_rank_three():
    assert find_expected_chunk_rank([12, 13, 4], 4) == 3


def test_expected_chunk_is_not_found():
    assert find_expected_chunk_rank([12, 13, 4], 99) is None


def test_mrr_for_multiple_retrieval_results():
    retrieved_chunks_by_question = [
        [10, 11, 12],  # Expected chunk is rank 1
        [20, 21, 22],  # Expected chunk is rank 2
        [30, 31, 32],  # Expected chunk is missing
    ]
    expected_chunks = [10, 21, 99]

    reciprocal_ranks = []

    for retrieved_chunks, expected_chunk in zip(
        retrieved_chunks_by_question,
        expected_chunks,
    ):
        rank = find_expected_chunk_rank(retrieved_chunks, expected_chunk)
        reciprocal_ranks.append(calculate_reciprocal_rank(rank))

    assert reciprocal_ranks == [1.0, 0.5, 0.0]
    assert calculate_mrr(reciprocal_ranks) == 0.5


def test_mrr_is_zero_when_all_expected_chunks_are_missing():
    reciprocal_ranks = [
        calculate_reciprocal_rank(
            find_expected_chunk_rank([1, 2, 3], 99)
        ),
        calculate_reciprocal_rank(
            find_expected_chunk_rank([4, 5, 6], 88)
        ),
    ]

    assert calculate_mrr(reciprocal_ranks) == 0.0


def test_mrr_is_zero_for_empty_input():
    assert calculate_mrr([]) == 0.0


@pytest.mark.parametrize("rank", [0, -1, 1.5, True, "2"])
def test_reciprocal_rank_rejects_invalid_rank(rank):
    with pytest.raises(ValueError, match="positive integer"):
        calculate_reciprocal_rank(rank)


@pytest.mark.parametrize("position", [0, 1, 2])
def test_rank_matches_source_and_chunk(position):
    metadata = [{"source": "other.pdf", "chunk_index": 2} for _ in range(3)]
    metadata[position] = {"source": "expected.pdf", "chunk_index": 2}
    assert find_expected_chunk_rank(metadata, 2, "expected.pdf") == position + 1


def test_rank_rejects_matching_index_from_wrong_source():
    assert find_expected_chunk_rank(
        [{"source": "other.pdf", "chunk_index": 2}], 2, "expected.pdf"
    ) is None


def test_rank_empty_and_first_duplicate():
    assert find_expected_chunk_rank([], 2, "doc.pdf") is None
    assert find_expected_chunk_rank([2, 2], 2) == 1


@pytest.mark.parametrize("cases, results", [([], [[]]), ([{}], [])])
def test_evaluate_hit_rate_rejects_misaligned_cases(cases, results):
    with pytest.raises(ValueError, match="one retrieval result"):
        evaluate_hit_rate(cases, results)


def test_evaluate_hit_rate_empty():
    assert evaluate_hit_rate([], []) == 0.0
