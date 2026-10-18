
from services.rrf import reciprocal_rank_fusion


def get_chunk_id(chunk: dict) -> tuple:
    metadata = chunk["metadata"]
    return (
        metadata["source"],
        metadata["chunk_index"],
    )


class HybridRetriever:
    def __init__(self, vector_retriever, bm25_retriever):
        self.vector_retriever = vector_retriever
        self.bm25_retriever = bm25_retriever

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        if top_k <= 0:
            return []

        vector_results = self.vector_retriever.retrieve(
            query,
            top_k=top_k,
        )
        bm25_results = self.bm25_retriever.search(
            query,
            top_k=top_k,
        )

        # Keep the chunk data and use stable IDs for fusion.
        chunks_by_id = {}
        vector_ranking = []
        bm25_ranking = []

        for chunk in vector_results:
            chunk_id = get_chunk_id(chunk)
            chunks_by_id[chunk_id] = chunk
            vector_ranking.append(chunk_id)

        for chunk in bm25_results:
            chunk_id = get_chunk_id(chunk)
            chunks_by_id.setdefault(chunk_id, chunk)
            bm25_ranking.append(chunk_id)

        fused_results = reciprocal_rank_fusion(
            [vector_ranking, bm25_ranking]
        )

        results = []
        for chunk_id, fused_score in fused_results[:top_k]:
            result = dict(chunks_by_id[chunk_id])
            result["score"] = fused_score
            results.append(result)

        return results

    def diagnose(self, query: str, top_k: int = 3) -> list[dict]:
        """Return every candidate with its source ranks and RRF score."""
        if top_k <= 0:
            return []

        vector_results = self.vector_retriever.retrieve(
            query, top_k=top_k
        )
        bm25_results = self.bm25_retriever.search(
            query, top_k=top_k
        )

        candidates = {}

        for rank, chunk in enumerate(vector_results, start=1):
            chunk_id = get_chunk_id(chunk)
            candidates.setdefault(
                chunk_id,
                {"chunk": chunk, "vector_rank": None, "bm25_rank": None},
            )
            candidates[chunk_id]["vector_rank"] = rank

        for rank, chunk in enumerate(bm25_results, start=1):
            chunk_id = get_chunk_id(chunk)
            candidates.setdefault(
                chunk_id,
                {"chunk": chunk, "vector_rank": None, "bm25_rank": None},
            )
            candidates[chunk_id]["bm25_rank"] = rank

        for item in candidates.values():
            score = 0.0

            if item["vector_rank"] is not None:
                score += 1 / (60 + item["vector_rank"])

            if item["bm25_rank"] is not None:
                score += 1 / (60 + item["bm25_rank"])

            item["chunk_id"] = get_chunk_id(item["chunk"])
            item["rrf_score"] = score

        return sorted(
            candidates.values(),
            key=lambda item: item["rrf_score"],
            reverse=True,
        )

