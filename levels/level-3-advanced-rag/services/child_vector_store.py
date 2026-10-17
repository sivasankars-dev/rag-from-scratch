
from pathlib import Path

import chromadb


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
            ids.append(child["child_id"])
            documents.append(child["text"])
            metadatas.append(
                {
                    "parent_id": child["parent_id"],
                    "source": child["source"],
                    "page_number": child["page_number"],
                }
            )

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
