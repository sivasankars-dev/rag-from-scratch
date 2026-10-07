import re


def search_keywords(query, chunks, top_k=2):
    query_words = set(re.findall(r"\b\w+\b", query.lower()))

    results = []

    for chunk in chunks:
        chunk_words = set(
            re.findall(r"\b\w+\b", chunk["chunk"].lower())
        )

        matched_words = query_words.intersection(chunk_words)
        score = len(matched_words)

        if score > 0:
            results.append(
                {
                    "chunk": chunk,
                    "score": score,
                    "matched_words": sorted(matched_words),
                }
            )

    results.sort(key=lambda result: result["score"], reverse=True)

    return results[:top_k]