class RetrievalEvaluator:
    def hit_rate_at_k(
        self,
        evaluation_cases,
        embedding_service,
        vector_store,
        k=3,
    ):
        if k <= 0:
            raise ValueError("k must be greater than 0")

        if not evaluation_cases:
            return 0.0

        hits = 0

        for case in evaluation_cases:
            query_embedding = embedding_service.embed_text(
                case["question"]
            )

            results = vector_store.search(
                query_embedding=query_embedding,
                top_k=k,
            )

            retrieved_metadata = results["metadatas"][0]

            retrieved_chunks = [
                metadata["chunk_index"]
                for metadata in retrieved_metadata
            ]

            if case["expected_chunk"] in retrieved_chunks:
                hits += 1

        return hits / len(evaluation_cases)
    
    def mean_reciprocal_rank(
        self,
        evaluation_cases,
        embedding_service,
        vector_store,
        k=3,
    ):
        if k <= 0:
            raise ValueError("k must be greater than 0")

        if not evaluation_cases:
            return 0.0

        reciprocal_ranks = []

        for case in evaluation_cases:
            query_embedding = embedding_service.embed_text(
                case["question"]
            )

            results = vector_store.search(
                query_embedding=query_embedding,
                top_k=k,
            )

            retrieved_chunks = [
                metadata["chunk_index"]
                for metadata in results["metadatas"][0]
            ]

            reciprocal_rank = 0.0

            for rank, chunk_index in enumerate(
                retrieved_chunks,
                start=1,
            ):
                if chunk_index == case["expected_chunk"]:
                    reciprocal_rank = 1 / rank
                    break

            reciprocal_ranks.append(reciprocal_rank)

        return sum(reciprocal_ranks) / len(reciprocal_ranks)