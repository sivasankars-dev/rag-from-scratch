
class ParentChildRetrievalService:
    def __init__(
        self,
        embedding_service,
        child_vector_store,
        parent_store,
    ):
        self.embedding_service = embedding_service
        self.child_vector_store = child_vector_store
        self.parent_store = parent_store

    def retrieve(self, question, top_k=2):
        query_embedding = self.embedding_service.embed_text(question)

        children = self.child_vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
        )

        results = []
        seen_parent_ids = set()

        for child in children:
            parent_id = child["metadata"]["parent_id"]

            if parent_id in seen_parent_ids:
                continue

            seen_parent_ids.add(parent_id)

            parent = self.parent_store.get_parent(parent_id)

            if parent is None:
                continue

            results.append(parent)

        return results
