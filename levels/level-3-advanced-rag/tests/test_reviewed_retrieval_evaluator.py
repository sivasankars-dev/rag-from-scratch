import pytest

from services.reviewed_retrieval_evaluator import (
    find_relevant_chunk_rank,
)


SOURCE = "handbook.pdf"


def metadata(*indices, source=SOURCE):
    return [
        {"source": source, "chunk_index": index}
        for index in indices
    ]


def test_accepts_alternative_relevant_chunk():
    rank = find_relevant_chunk_rank(
        metadata(11, 13, 22),
        relevant_chunks=[13, 25],
        expected_source=SOURCE,
    )

    assert rank == 2


def test_returns_first_relevant_rank():
    rank = find_relevant_chunk_rank(
        metadata(26, 1, 15),
        relevant_chunks=[1, 26],
        expected_source=SOURCE,
    )

    assert rank == 1


def test_same_index_from_different_source_is_not_a_hit():
    results = (
        metadata(13, source="other.pdf")
        + metadata(25)
    )

    assert find_relevant_chunk_rank(
        results,
        relevant_chunks=[13, 25],
        expected_source=SOURCE,
    ) == 2


def test_ignores_relevant_chunk_outside_cutoff():
    assert find_relevant_chunk_rank(
        metadata(11, 22, 24, 25),
        relevant_chunks=[25],
        expected_source=SOURCE,
        top_k=3,
    ) is None


def test_returns_none_when_no_relevant_chunk():
    assert find_relevant_chunk_rank(
        metadata(11, 22),
        relevant_chunks=[13, 25],
        expected_source=SOURCE,
    ) is None


def test_empty_results_return_none():
    assert find_relevant_chunk_rank(
        [],
        relevant_chunks=[13],
        expected_source=SOURCE,
    ) is None


def test_zero_is_a_valid_chunk_index():
    assert find_relevant_chunk_rank(
        metadata(0),
        relevant_chunks=[0],
        expected_source=SOURCE,
    ) == 1


@pytest.mark.parametrize("top_k", [0, -1, True, 1.5])
def test_rejects_invalid_cutoff(top_k):
    with pytest.raises(ValueError, match="top_k"):
        find_relevant_chunk_rank(
            [],
            relevant_chunks=[13],
            expected_source=SOURCE,
            top_k=top_k,
        )


@pytest.mark.parametrize(
    "relevant_chunks",
    [[], None, [True], [-1], ["13"]],
)
def test_rejects_invalid_labels(relevant_chunks):
    with pytest.raises(ValueError, match="relevant_chunks"):
        find_relevant_chunk_rank(
            [],
            relevant_chunks=relevant_chunks,
            expected_source=SOURCE,
        )


@pytest.mark.parametrize("source", ["", " ", None])
def test_rejects_invalid_source(source):
    with pytest.raises(ValueError, match="expected_source"):
        find_relevant_chunk_rank(
            [],
            relevant_chunks=[13],
            expected_source=source,
        )