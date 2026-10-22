from sentence_transformers import CrossEncoder


class CrossEncoderReranker:
    def __init__(self, model):
        if model is None:
            raise ValueError("model must not be None")

        self.model = model

    @classmethod
    def from_pretrained(
        cls,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ):
        return cls(model=CrossEncoder(model_name))

    def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_n: int = 3,
    ) -> list[dict]:
        if (
            not isinstance(top_n, int)
            or isinstance(top_n, bool)
            or top_n <= 0
        ):
            raise ValueError("top_n must be a positive integer")

        if not candidates:
            return []

        pairs = [
            (query, candidate["document"])
            for candidate in candidates
        ]

        scores = list(self.model.predict(pairs))

        if len(scores) != len(candidates):
            raise ValueError(
                "Number of reranker scores must match number of candidates"
            )

        reranked_results = []

        for candidate, score in zip(candidates, scores):
            result = dict(candidate)
            result["reranker_score"] = float(score)
            reranked_results.append(result)

        reranked_results.sort(
            key=lambda result: result["reranker_score"],
            reverse=True,
        )

        return reranked_results[:top_n]
