import re


def calculate_reranker_score(query, chunk):
    query_words = set(re.findall(r"\b\w+\b", query.lower()))
    chunk_words = set(re.findall(r"\b\w+\b", chunk.lower()))

    return len(query_words.intersection(chunk_words))

def rerank(query, candidates, top_k=2):
    reranked_results = []

    for candidate in candidates:
        chunk = candidate["chunk"]

        score = calculate_reranker_score(
            query,
            chunk["chunk"],
        )

        result = candidate.copy()
        result["reranker_score"] = score

        reranked_results.append(result)

    reranked_results.sort(
        key=lambda result: result["reranker_score"],
        reverse=True,
    )

    return reranked_results[:top_k]

def rerank_with_cross_encoder(query, candidates, model, top_k=2):
    if not candidates:
        return []

    pairs = [
        (query, candidate["chunk"]["chunk"])
        for candidate in candidates
    ]

    scores = model.predict(pairs)
    
    if len(scores) != len(candidates):
        raise ValueError(
            "Number of reranker scores must match number of candidates"
        )

    reranked_results = []

    for candidate, score in zip(candidates, scores):
        result = candidate.copy()
        result["reranker_score"] = float(score)

        reranked_results.append(result)

    reranked_results.sort(
        key=lambda result: result["reranker_score"],
        reverse=True,
    )

    return reranked_results[:top_k]

