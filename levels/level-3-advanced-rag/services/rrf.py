def reciprocal_rank_fusion(rankings, k=60):
    scores = {}

    for ranking in rankings:
        seen_in_ranking = set()

        for rank, chunk_id in enumerate(ranking, start=1):
            if chunk_id in seen_in_ranking:
                continue

            seen_in_ranking.add(chunk_id)

            score = 1 / (k + rank)
            scores[chunk_id] = scores.get(chunk_id, 0) + score

    return sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )
