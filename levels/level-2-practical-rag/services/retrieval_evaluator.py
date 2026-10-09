def is_expected_chunk_retrieved(
    retrieved_metadata,
    expected_source,
    expected_chunk,
):
    return find_expected_chunk_rank(
        retrieved_metadata, expected_chunk, expected_source
    ) is not None


def calculate_hit_rate(hit_results):
    if len(hit_results) < 1:
        return 0.0

    hit_count = sum(1 for result in hit_results if result)

    return hit_count/len(hit_results)

def evaluate_hit_rate(evaluation_cases, retrieved_metadata_by_case):
    if len(evaluation_cases) != len(retrieved_metadata_by_case):
        raise ValueError("Each evaluation case must have one retrieval result")

    hit_results = []

    for index, case in enumerate(evaluation_cases):
        retrieved_metadata = retrieved_metadata_by_case[index]

        result = is_expected_chunk_retrieved(
            retrieved_metadata,
            case["expected_source"],
            case["expected_chunk"],
        )

        hit_results.append(result)

    return calculate_hit_rate(hit_results)

def evaluate_retrieval_hit_rate(
    evaluation_cases,
    embedding_service,
    retrieval_service,
    top_k=2,
):
    hit_results = []

    for case in evaluation_cases:
        query_embedding = embedding_service.embed_text(
            case["question"]
        )

        retrieval_result = retrieval_service.retrieve(
            query_embedding=query_embedding,
            top_k=top_k,
        )

        retrieved_metadata = retrieval_result["metadatas"][0]

        result = is_expected_chunk_retrieved(
            retrieved_metadata,
            case["expected_source"],
            case["expected_chunk"],
        )

        hit_results.append(result)

    return calculate_hit_rate(hit_results)

def calculate_mrr(reciprocal_ranks):
    if len(reciprocal_ranks) < 1:
        return 0.0

    return sum(reciprocal_ranks) / len(reciprocal_ranks)

def calculate_reciprocal_rank(rank):
    if rank is None:
        return 0.0

    if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
        raise ValueError("rank must be a positive integer or None")

    return 1 / rank

def find_expected_chunk_rank(retrieved_chunks, expected_chunk, expected_source=None):
    """Find the first match; supply metadata and source for multi-document safety.

    Without expected_source, retrieved_chunks is a list of indices for the
    earlier single-document examples. The handbook runner always matches both.
    """
    for rank, chunk in enumerate(retrieved_chunks, start=1):
        if expected_source is None:
            matches = chunk == expected_chunk
        else:
            matches = (
                chunk["source"] == expected_source
                and chunk["chunk_index"] == expected_chunk
            )
        if matches:
            return rank

    return None
