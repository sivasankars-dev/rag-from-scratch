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

    def upsert_processed_chunks(self, processed_chunks, embeddings):
        
        if not processed_chunks:
            return

        ids = []
        metadatas = []
        documents = []

        for chunk in processed_chunks:
            ids.append(f"{chunk['source']}_chunk_{chunk['chunk_index']}")
            metadatas.append(
                {
                    "chunk_index": chunk["chunk_index"],
                    "source": chunk["source"],
                    "page_number": chunk["page_number"],
                    "document_type": chunk["document_type"],
                }
            )
            documents.append(chunk["chunk"])

        self.collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        
    def search(self, query_embedding, top_k=2, where=None):
        return self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=[
                "documents",
                "metadatas",
                "distances",
            ],
        )
