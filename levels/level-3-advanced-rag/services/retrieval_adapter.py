class RetrievalAdapter:
    def __init__(self, retrieval_service):
        self.retrieval_service = retrieval_service

    def retrieve(
        self,
        query_embedding,
        top_k=2,
        metadata_filter=None,
    ):
        response = self.retrieval_service.retrieve(
            query_embedding=query_embedding,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )

        documents = response.get("documents", [[]])
        metadatas = response.get("metadatas", [[]])
        distances = response.get("distances", [[]])

        documents = documents[0] if documents else []
        metadatas = metadatas[0] if metadatas else []
        distances = distances[0] if distances else []

        if not (
            len(documents) == len(metadatas) == len(distances)
        ):
            raise ValueError(
                "Chroma result counts do not match: "
                "documents, metadatas, and distances must align."
            )

        results = []

        for document, metadata, distance in zip(
            documents, metadatas, distances
        ):
            results.append(
                {
                    "document": document,
                    "metadata": metadata,
                    "distance": distance,
                }
            )

        return results
