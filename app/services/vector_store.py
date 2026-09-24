from pathlib import Path
import chromadb

class VectorStore:
    def __init__(self, persist_directory="data/chroma", collection_name="documents_cosine"):
        Path(persist_directory).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(
            path=persist_directory
        )

        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            configuration={
                "hsnw": {
                    "space": "cosine"
                }
            }
        )

    def upsert_chunks(self, chunks, embeddings, source):
        ids = [f"{source}_chunk_{index}" for index in range(len(chunks))]
        metadatas = [
            {
                "chunk_index": index,
                "source": source
            }
            for index in range(len(chunks))
        ]

        self.collection.upsert(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas
        )

    def search(self, query_embedding, top_k=2):
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=[
                "documents",
                "metadatas",
                "distances"
            ]
        )
