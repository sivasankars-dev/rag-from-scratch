from pathlib import Path

import chromadb


CHILD_METADATA_FIELDS = (
    "parent_id",
    "source",
    "page_number",
    "document_id",
    "section_id",
    "section_number",
    "section_title",
    "section_type",
    "parent_section_id",
    "section_path",
    "section_start_page",
    "section_end_page",
)

REQUIRED_METADATA_FIELDS = (
    "parent_id",
    "source",
    "page_number",
)


class ChildVectorStore:
    def __init__(
        self,
        persist_directory="data/parent_child_chroma",
        collection_name="parent_child_children",
    ):
        Path(persist_directory).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_directory)

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
        )

    def store_children(self, children, embeddings):
        if not children:
            return

        if len(children) != len(embeddings):
            raise ValueError(
                "Number of children must match number of embeddings"
            )

        ids = []
        documents = []
        metadatas = []

        for child in children:
            missing = [
                field
                for field in REQUIRED_METADATA_FIELDS
                if field not in child or child[field] is None
            ]
            if missing:
                raise ValueError(
                    f"Child is missing required metadata fields: {missing}"
                )

            ids.append(child["child_id"])
            documents.append(child["text"])

            # Preserve known hierarchy fields and omit None values.
            # Chroma metadata supports scalar values, not Python None.
            metadata = {
                field: child[field]
                for field in CHILD_METADATA_FIELDS
                if field in child and child[field] is not None
            }
            metadatas.append(metadata)

        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def get_child_by_id(self, child_id):
        result = self.collection.get(
            ids=[child_id],
            include=["documents", "metadatas"],
        )

        if not result["ids"]:
            return None

        return {
            "child_id": result["ids"][0],
            "text": result["documents"][0],
            "metadata": result["metadatas"][0],
        }

    def search(self, query_embedding, top_k=2):
        if self.collection.count() == 0:
            return []

        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        children = []

        for i, child_id in enumerate(result["ids"][0]):
            children.append(
                {
                    "child_id": child_id,
                    "text": result["documents"][0][i],
                    "metadata": result["metadatas"][0][i],
                    "distance": result["distances"][0][i],
                }
            )

        return children
