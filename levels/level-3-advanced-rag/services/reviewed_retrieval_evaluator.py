"""Evaluate ranked metadata using reviewed relevance labels."""


def find_relevant_chunk_rank(
    retrieved_metadata,
    relevant_chunks,
    expected_source,
    top_k=3,
):
    """Return the first relevant rank within top_k, or None."""
    if (
        isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k <= 0
    ):
        raise ValueError("top_k must be a positive integer")

    if not isinstance(expected_source, str) or not expected_source.strip():
        raise ValueError("expected_source must be a nonempty string")

    if not isinstance(relevant_chunks, list) or not relevant_chunks:
        raise ValueError("relevant_chunks must be a nonempty list")

    if any(
        isinstance(index, bool)
        or not isinstance(index, int)
        or index < 0
        for index in relevant_chunks
    ):
        raise ValueError("relevant_chunks must contain nonnegative integers")

    accepted = set(relevant_chunks)

    for rank, metadata in enumerate(
        retrieved_metadata[:top_k],
        start=1,
    ):
        if (
            metadata["source"] == expected_source
            and metadata["chunk_index"] in accepted
        ):
            return rank

    return None