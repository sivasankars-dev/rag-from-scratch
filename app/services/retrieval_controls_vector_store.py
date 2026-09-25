from pathlib import Path
import chromadb


class VectorStore:
    def __init__(
        self, persist_directory="data/chroma", collection_name="documents_cosine"
    ):
        Path(persist_directory).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_directory)

        self.collection = self.client.get_or_create_collection(
            name=collection_name, configuration={"hnsw": {"space": "cosine"}}
        )

        if self.collection.configuration["hnsw"]["space"] != "cosine":
            raise ValueError(
                "Existing collection does not use cosine distance. "
                "Preserve the old database and re-ingest into a fresh cosine collection."
            )

    def upsert_chunks(self, chunks, embeddings, source):
        ids = [f"{source}_chunk_{index}" for index in range(len(chunks))]
        metadatas = [
            {"chunk_index": index, "source": source} for index in range(len(chunks))
        ]

        self.collection.upsert(
            ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas
        )

    def search(self, query_embedding, top_k=2, source=None, similarity_threshold=0.50):
        where = None
        if source:
            where = {"source": source}
            
        collections = self.collection.query(
            query_embeddings=[query_embedding],
            where=where,
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        results = []

        for document, metadata, distance in zip(
            collections["documents"][0],
            collections["metadatas"][0],
            collections["distances"][0],
        ):
            cosine_similarity = 1 - distance

            if cosine_similarity < similarity_threshold:
                continue

            results.append(
                {
                    "document": document,
                    "metadata": metadata,
                    "distance": distance,
                    "similarity": cosine_similarity,
                }
            )

        return results
