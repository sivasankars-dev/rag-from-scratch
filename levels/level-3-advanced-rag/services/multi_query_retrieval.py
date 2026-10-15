from services.rrf import reciprocal_rank_fusion


class MultiQueryRetrievalService:
    def __init__(self, query_generator, embedding_service, retrieval_service):
        self.query_generator = query_generator
        self.embedding_service = embedding_service
        self.retrieval_service = retrieval_service

    def _build_queries(self, question):
        generated_queries = self.query_generator.generate_queries(question)

        queries = []
        seen = set()

        for query in [question, *generated_queries]:
            if not isinstance(query, str):
                continue

            query = query.strip()

            if not query:
                continue

            normalized_query = query.casefold()

            if normalized_query in seen:
                continue

            seen.add(normalized_query)
            queries.append(query)

        return queries

    def retrieve(self, question, top_k=2, metadata_filter=None):
        queries = self._build_queries(question)

        merged_results = {}
        rankings = []

        for query in queries:
            query_embedding = self.embedding_service.embed_text(query)

            chunks = self.retrieval_service.retrieve(
                query_embedding=query_embedding,
                top_k=top_k,
                metadata_filter=metadata_filter,
            )

            ranking = []

            for chunk in chunks:
                metadata = chunk.get("metadata", {})
                source = metadata.get("source")
                chunk_index = metadata.get("chunk_index")

                if source is None or chunk_index is None:
                    raise ValueError(
                        "Each retrieved chunk must contain "
                        "'source' and 'chunk_index' metadata."
                    )

                chunk_key = (source, chunk_index)
                ranking.append(chunk_key)

                if chunk_key not in merged_results:
                    merged_chunk = dict(chunk)
                    merged_chunk["retrieved_by"] = [query]
                    merged_chunk["retrieval_count"] = 1
                    merged_results[chunk_key] = merged_chunk
                else:
                    existing_chunk = merged_results[chunk_key]

                    if query not in existing_chunk["retrieved_by"]:
                        existing_chunk["retrieved_by"].append(query)
                        existing_chunk["retrieval_count"] += 1

            # After processing ALL chunks for this query:
            rankings.append(ranking)

        # After processing ALL queries:
        fused_results = reciprocal_rank_fusion(rankings)

        return [
            {
                **merged_results[chunk_id],
                "rrf_score": score,
            }
            for chunk_id, score in fused_results[:top_k]
        ]
